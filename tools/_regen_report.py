"""One-off helper: regenerate report.html for an existing results/ session directory
from its already-exported actions.json / api_calls.csv / summary.csv, using the
current HtmlReport rendering. Used to refresh already-published reports after a
report-format change, without re-running the full Playwright session.

Usage:
    python tools/_regen_report.py results/<session_dir>
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reporting.html_report import HtmlReport


def _load_api_calls(csv_path: Path):
    calls = []
    if not csv_path.exists():
        return calls
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            calls.append({
                "method": row.get("Method"),
                "url": row.get("Url"),
                "status": int(row["Status"]) if row.get("Status") not in (None, "") else None,
                "duration_ms": float(row["DurationMs"]) if row.get("DurationMs") not in (None, "") else None,
                "is_valid": (row.get("IsValid") or "").strip().lower() == "true",
                "api_error": row.get("ApiError") or None,
                "error": row.get("Error") or None,
            })
    return calls


def _load_summary_row(csv_path: Path) -> dict:
    if not csv_path.exists():
        return {}
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return rows[0] if rows else {}


def main() -> None:
    session_dir = Path(sys.argv[1]).resolve()
    actions_json = json.loads((session_dir / "actions.json").read_text(encoding="utf-8"))
    api_calls = _load_api_calls(session_dir / "api_calls.csv")
    summary_row = _load_summary_row(session_dir / "summary.csv")

    api_threshold_ms = float(summary_row["ApiThresholdMs"]) if summary_row.get("ApiThresholdMs") else None

    report_data = {
        "session": {
            "room": actions_json.get("room", ""),
            "workflow": actions_json.get("workflow", ""),
            "timestamp": actions_json.get("timestamp", ""),
        },
        "api_calls": api_calls,
        "endpoints": [],
        "selectors": [],
        "ws_frames": [],
        "summary": {
            "actions": actions_json.get("actions", []),
            "api_threshold_ms": api_threshold_ms,
        },
    }
    out = HtmlReport().generate(session_dir / "report.html", report_data)
    print(f"Regenerated {out}")


if __name__ == "__main__":
    main()
