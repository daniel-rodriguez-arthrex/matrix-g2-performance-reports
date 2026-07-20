#!/usr/bin/env python
"""Publish a Matrix G2 performance report to the GitHub Pages site directory.

Security model (mirrors the ORC reports setup):
  * The site/ directory is a SEPARATE, publishable artifact - only sanitized report
    HTML/PDF and small metadata files ever land there.
  * Raw run artifacts (CSVs with response bodies/tokens, .env, source) are NEVER copied.
  * Report HTML is sanitized (internal IPs / URL credentials masked) before publishing,
    and the PDF is regenerated from the sanitized HTML so it matches.

Usage:
    python tools/publish_report.py <results_report_dir> [--slug SLUG] [--title TITLE]
                                   [--site-dir site] [--no-pdf]

Example:
    python tools/publish_report.py results/retry_verify/all_OR1_2026-07-20_09-17-33
"""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from tools.sanitize_report import sanitize_file, sanitize_html

try:
    from tools.html_to_pdf import convert as html_to_pdf_convert
except Exception:  # pragma: no cover - PDF is optional
    html_to_pdf_convert = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_META_RE = re.compile(r'<div class="meta">([^<]+)</div>')
_STATUS_RE = re.compile(r"<h3>Status</h3>\s*<div class=\"value (status-pass|status-fail)\"")
_ACTIONS_RE = re.compile(r"<h2>Actions \((\d+)/(\d+) successful\)</h2>")


def _card_value(html: str, heading: str) -> str:
    """Extract a summary-card value (e.g. '96ms', '0') by its <h3> heading."""
    m = re.search(
        r"<h3>" + re.escape(heading) + r"</h3>\s*<div class=\"value[^\"]*\">\s*([^<\s][^<]*?)\s*</div>",
        html,
    )
    return m.group(1).strip() if m else ""


def _friendly_date(timestamp: str) -> str:
    """Turn '2026-07-20T09:19:13' into 'Jul 20, 2026' (falls back to raw input)."""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(timestamp, fmt).strftime("%b %d, %Y")
        except ValueError:
            continue
    return timestamp


def _extract_metadata(html: str, slug: str) -> dict:
    """Pull display metadata from the (already sanitized) report HTML."""
    workflow, room, timestamp = "", "", ""
    meta = _META_RE.search(html)
    if meta:
        parts = [p.strip() for p in meta.group(1).split("\u2022")]
        if len(parts) == 3:
            workflow, room_raw, timestamp = parts
            room = room_raw.replace("Room", "").strip()

    status_match = _STATUS_RE.search(html)
    status = "PASS" if (status_match and status_match.group(1) == "status-pass") else \
        ("FAIL" if status_match else "UNKNOWN")

    actions_match = _ACTIONS_RE.search(html)
    actions_passed = int(actions_match.group(1)) if actions_match else 0
    actions_total = int(actions_match.group(2)) if actions_match else 0

    return {
        "slug": slug,
        "workflow": workflow,
        "room": room,
        "timestamp": timestamp,
        "date": _friendly_date(timestamp),
        "status": status,
        "actions_passed": actions_passed,
        "actions_total": actions_total,
        "avg_api": _card_value(html, "Avg API Time"),
        "p95_api": _card_value(html, "P95 API Time"),
        "workflow_api_calls": _card_value(html, "Workflow API Calls"),
        "errors": _card_value(html, "Errors"),
        "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


def publish(results_dir: Path, site_dir: Path, slug: str, title: str, make_pdf: bool) -> dict:
    report_html = results_dir / "report.html"
    if not report_html.exists():
        raise FileNotFoundError(f"No report.html found in {results_dir}")

    dest_dir = site_dir / "reports" / slug
    dest_html = dest_dir / "report.html"

    masked = sanitize_file(report_html, dest_html)
    print(f"  Sanitized report.html ({masked} IP references masked)")

    if make_pdf and html_to_pdf_convert is not None:
        html_to_pdf_convert(dest_html, dest_dir / "report.pdf")
        print("  Regenerated sanitized report.pdf")

    html = dest_html.read_text(encoding="utf-8")
    meta = _extract_metadata(html, slug)
    if title:
        meta["title"] = title
    (dest_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def _load_all_reports(site_dir: Path) -> list:
    reports = []
    reports_root = site_dir / "reports"
    if not reports_root.exists():
        return reports
    for meta_file in reports_root.glob("*/meta.json"):
        try:
            reports.append(json.loads(meta_file.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    reports.sort(key=lambda m: m.get("timestamp", ""), reverse=True)
    return reports


def _metric_cell(label: str, value: str) -> str:
    return (
        f'<div class="metric"><span class="m-label">{label}</span>'
        f'<span class="m-value">{value or "&mdash;"}</span></div>'
    )


def _render_card(r: dict) -> str:
    title = r.get("title") or f"{(r.get('workflow') or 'Report').upper()} - Room {r.get('room','')}"
    status = r.get("status", "UNKNOWN")
    badge_class = {"PASS": "badge-pass", "FAIL": "badge-fail"}.get(status, "badge-unknown")
    slug = r.get("slug", "")

    metrics = "".join([
        _metric_cell("Room", r.get("room", "")),
        _metric_cell("Workflow", r.get("workflow", "")),
        _metric_cell("Date", r.get("date") or r.get("timestamp", "")),
        _metric_cell("Actions", f"{r.get('actions_passed', 0)}/{r.get('actions_total', 0)}"),
        _metric_cell("Avg API", r.get("avg_api", "")),
        _metric_cell("P95 API", r.get("p95_api", "")),
    ])
    return f"""
        <div class="card">
            <div class="card-header">
                <span class="card-title">{title}</span>
                <span class="badge {badge_class}">{status}</span>
            </div>
            <div class="card-body">
                <div class="metrics">{metrics}</div>
                <a class="btn" href="reports/{slug}/report.html">View Full Report &rarr;</a>
                <a class="pdf-link" href="reports/{slug}/report.pdf">Download PDF</a>
            </div>
        </div>"""


def _render_index(reports: list) -> str:
    cards = "".join(_render_card(r) for r in reports)
    empty = "" if cards else '<p class="empty">No reports published yet.</p>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Matrix G2 Performance Hub</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; background: #eef1f5; color: #1a202c; }}
        .hub-header {{ background: linear-gradient(120deg, #1a2233 0%, #2b3a55 100%); color: #fff; padding: 2rem 1.5rem; }}
        .hub-header-inner {{ max-width: 1080px; margin: 0 auto; display: flex; align-items: center; gap: 1rem; }}
        .hub-header h1 {{ font-size: 1.75rem; font-weight: 800; letter-spacing: -0.3px; }}
        .hub-header p {{ opacity: 0.8; font-size: 0.95rem; margin-top: 0.2rem; }}
        .container {{ max-width: 1080px; margin: 0 auto; padding: 2rem 1.5rem 3rem; }}
        .section-label {{ font-size: 0.72rem; font-weight: 800; letter-spacing: 1px; text-transform: uppercase; color: #8a93a2; margin-bottom: 1rem; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 1.5rem; }}
        .card {{ background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 14px rgba(20,30,50,0.08); transition: transform 0.15s, box-shadow 0.15s; }}
        .card:hover {{ transform: translateY(-2px); box-shadow: 0 10px 26px rgba(20,30,50,0.14); }}
        .card-header {{ background: linear-gradient(120deg, #1f2a3d 0%, #2b3a55 100%); color: #fff; padding: 1rem 1.25rem; display: flex; justify-content: space-between; align-items: center; gap: 0.75rem; }}
        .card-title {{ font-size: 1.02rem; font-weight: 700; }}
        .badge {{ display: inline-block; padding: 0.3rem 0.6rem; border-radius: 5px; font-size: 0.68rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px; white-space: nowrap; }}
        .badge-pass {{ background: #d1f4dd; color: #1a7a42; }}
        .badge-fail {{ background: #fdd8d8; color: #b02525; }}
        .badge-unknown {{ background: #e2e8f0; color: #4a5568; }}
        .card-body {{ padding: 1.25rem; }}
        .metrics {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.6rem; margin-bottom: 1.1rem; }}
        .metric {{ background: #f4f6f9; border-radius: 8px; padding: 0.7rem 0.8rem; display: flex; flex-direction: column; gap: 0.25rem; }}
        .m-label {{ font-size: 0.62rem; font-weight: 700; letter-spacing: 0.5px; text-transform: uppercase; color: #8a93a2; }}
        .m-value {{ font-size: 0.98rem; font-weight: 700; color: #1a202c; }}
        .btn {{ display: block; text-align: center; text-decoration: none; padding: 0.7rem 1rem; border-radius: 8px; font-weight: 700; font-size: 0.9rem; background: #2563eb; color: #fff; }}
        .btn:hover {{ background: #1d4ed8; }}
        .pdf-link {{ display: block; text-align: center; margin-top: 0.6rem; font-size: 0.8rem; font-weight: 600; color: #64748b; text-decoration: none; }}
        .pdf-link:hover {{ color: #2563eb; }}
        .empty {{ color: #64748b; }}
        .footer {{ max-width: 1080px; margin: 0 auto; padding: 0 1.5rem 2rem; color: #8a93a2; font-size: 0.78rem; }}
        @media (max-width: 520px) {{ .grid {{ grid-template-columns: 1fr; }} }}
    </style>
</head>
<body>
    <header class="hub-header">
        <div class="hub-header-inner">
            <div>
                <h1>Matrix G2 Performance Hub</h1>
                <p>Automated workflow performance results &mdash; internal network details redacted</p>
            </div>
        </div>
    </header>
    <main class="container">
        <div class="section-label">Test Reports</div>
        <div class="grid">{cards}</div>
        {empty}
    </main>
    <div class="footer">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</div>
</body>
</html>"""


def rebuild_index(site_dir: Path) -> int:
    reports = _load_all_reports(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "index.html").write_text(_render_index(reports), encoding="utf-8")
    return len(reports)


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish a sanitized report to the Pages site.")
    parser.add_argument("results_dir", help="Path to the results report directory (contains report.html)")
    parser.add_argument("--slug", help="URL slug for the report (default: results dir name)")
    parser.add_argument("--title", default="", help="Optional display title for the hub card")
    parser.add_argument("--site-dir", default="site", help="Publish root (default: site)")
    parser.add_argument("--no-pdf", action="store_true", help="Skip regenerating the sanitized PDF")
    args = parser.parse_args()

    results_dir = Path(args.results_dir).resolve()
    site_dir = (PROJECT_ROOT / args.site_dir).resolve() if not Path(args.site_dir).is_absolute() else Path(args.site_dir)
    slug = args.slug or results_dir.name

    print(f"Publishing '{slug}' -> {site_dir}")
    publish(results_dir, site_dir, slug, args.title, make_pdf=not args.no_pdf)
    count = rebuild_index(site_dir)
    print(f"Done. Hub index rebuilt with {count} report(s): {site_dir / 'index.html'}")


if __name__ == "__main__":
    main()
