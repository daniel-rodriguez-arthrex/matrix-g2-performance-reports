"""Discover and summarize past runs under ``results/`` for the GUI Results tab.

Reuses the same metadata-extraction logic the publish pipeline uses so cards in the
GUI match what eventually lands on the public hub.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from tools.publish_report import _extract_metadata

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _rel(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def list_reports(results_dir: Optional[Path] = None) -> List[dict]:
    """Return metadata for every ``report.html`` found under ``results/``.

    Sorted newest-first by directory modification time.
    """
    root = results_dir or (PROJECT_ROOT / "results")
    reports: List[dict] = []
    if not root.exists():
        return reports

    for report_html in root.rglob("report.html"):
        report_dir = report_html.parent
        try:
            html = report_html.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        meta = _extract_metadata(html, slug=report_dir.name)
        meta["dir"] = _rel(report_dir)
        meta["report_url"] = "/reports/" + _rel(report_dir)
        meta["mtime"] = report_html.stat().st_mtime
        reports.append(meta)

    reports.sort(key=lambda m: m.get("mtime", 0), reverse=True)
    return reports


def resolve_report_dir(rel_dir: str) -> Path:
    """Safely resolve a results-relative report dir, preventing path traversal."""
    candidate = (PROJECT_ROOT / rel_dir).resolve()
    results_root = (PROJECT_ROOT / "results").resolve()
    if results_root not in candidate.parents and candidate != results_root:
        raise ValueError("Report path is outside the results directory.")
    if not candidate.is_dir():
        raise FileNotFoundError(f"No such report directory: {rel_dir}")
    return candidate
