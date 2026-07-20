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
        "status": status,
        "actions_passed": actions_passed,
        "actions_total": actions_total,
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


def _render_index(reports: list) -> str:
    cards = []
    for r in reports:
        title = r.get("title") or f"{(r.get('workflow') or 'Report').upper()} — Room {r.get('room','')}"
        status = r.get("status", "UNKNOWN")
        badge_class = "badge-pass" if status == "PASS" else "badge-fail" if status == "FAIL" else "badge-unknown"
        actions = f"{r.get('actions_passed', 0)}/{r.get('actions_total', 0)} actions"
        slug = r.get("slug", "")
        cards.append(f"""
        <div class="card">
            <div class="card-head">
                <span class="badge {badge_class}">{status}</span>
                <span class="card-date">{r.get('timestamp','')}</span>
            </div>
            <h3>{title}</h3>
            <div class="card-meta">{actions} &bull; published {r.get('published_at','')}</div>
            <div class="card-links">
                <a class="btn" href="reports/{slug}/report.html">View Report &rarr;</a>
                <a class="btn btn-ghost" href="reports/{slug}/report.pdf">PDF</a>
            </div>
        </div>""")

    empty = "" if cards else '<p class="empty">No reports published yet.</p>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Matrix G2 Performance Reports</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 2rem 1rem; color: #2d3748; }}
        .container {{ max-width: 1100px; margin: 0 auto; }}
        .hero {{ color: #fff; padding: 1rem 0 2rem; }}
        .hero h1 {{ font-size: 2.5rem; font-weight: 800; letter-spacing: -0.5px; margin-bottom: 0.5rem; }}
        .hero p {{ opacity: 0.9; font-size: 1.05rem; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1.25rem; margin-top: 1.5rem; }}
        .card {{ background: #fff; border-radius: 14px; padding: 1.5rem; box-shadow: 0 10px 30px rgba(0,0,0,0.15); transition: transform 0.2s, box-shadow 0.2s; }}
        .card:hover {{ transform: translateY(-3px); box-shadow: 0 16px 40px rgba(0,0,0,0.22); }}
        .card-head {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem; }}
        .card h3 {{ font-size: 1.15rem; font-weight: 700; margin-bottom: 0.4rem; }}
        .card-meta {{ font-size: 0.8rem; color: #718096; margin-bottom: 1.1rem; }}
        .card-date {{ font-size: 0.75rem; color: #a0aec0; }}
        .badge {{ display: inline-block; padding: 0.3rem 0.7rem; border-radius: 6px; font-size: 0.72rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px; }}
        .badge-pass {{ background: #c6f6d5; color: #22543d; }}
        .badge-fail {{ background: #fed7d7; color: #742a2a; }}
        .badge-unknown {{ background: #e2e8f0; color: #4a5568; }}
        .card-links {{ display: flex; gap: 0.6rem; }}
        .btn {{ flex: 1; text-align: center; text-decoration: none; padding: 0.6rem 1rem; border-radius: 8px; font-weight: 700; font-size: 0.85rem; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: #fff; }}
        .btn-ghost {{ flex: 0 0 auto; background: #edf2f7; color: #4a5568; }}
        .empty {{ color: #fff; opacity: 0.9; margin-top: 1rem; }}
        .footer {{ color: #fff; opacity: 0.75; font-size: 0.8rem; margin-top: 2.5rem; text-align: center; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="hero">
            <h1>Matrix G2 Performance Reports</h1>
            <p>Automated workflow performance runs. Internal network details are redacted for public sharing.</p>
        </div>
        <div class="grid">{''.join(cards)}</div>
        {empty}
        <div class="footer">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</div>
    </div>
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
