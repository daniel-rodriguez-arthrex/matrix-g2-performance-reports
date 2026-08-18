"""Publish orchestration for the GUI.

Wraps the existing ``tools/publish_report.py`` pipeline and adds the safety checks
described in ``docs/PUBLISHING.md`` (leftover-IP scan, git status preview) before any
push to the public ``gh-pages`` repo. The GUI performs the publish in two explicit
steps: (1) sanitize + stage into ``site/`` and show what changed, (2) commit + push
only after the user confirms.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional

from tools.publish_report import publish, rebuild_index
from tools.sanitize_report import _IPV4_PORT

from .results import resolve_report_dir

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = PROJECT_ROOT / "site"


def _git(site_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(site_dir),
        capture_output=True,
        text=True,
    )


def scan_for_ips(site_dir: Path) -> List[str]:
    """Return report files under site/ that still contain raw IPv4 addresses."""
    offenders: List[str] = []
    reports_root = site_dir / "reports"
    if not reports_root.exists():
        return offenders
    for html in reports_root.rglob("report.html"):
        text = html.read_text(encoding="utf-8", errors="ignore")
        if _IPV4_PORT.search(text):
            offenders.append(html.relative_to(site_dir).as_posix())
    return offenders


def stage_publish(rel_dir: str, title: str = "", make_pdf: bool = True) -> dict:
    """Sanitize + copy the report into site/ and rebuild the hub index.

    Returns a summary including the leftover-IP scan result and the pending git
    changes, so the UI can show the user exactly what will be committed before push.
    """
    report_dir = resolve_report_dir(rel_dir)
    slug = report_dir.name

    meta = publish(report_dir, SITE_DIR, slug=slug, title=title, make_pdf=make_pdf)
    count = rebuild_index(SITE_DIR)

    ip_offenders = scan_for_ips(SITE_DIR)
    status = git_status()

    return {
        "slug": slug,
        "title": meta.get("title") or slug,
        "report_count": count,
        "ip_offenders": ip_offenders,
        "safe_to_push": not ip_offenders,
        "git": status,
    }


def git_status() -> dict:
    """Return the git state of the site/ repo (or a reason it can't be read)."""
    if not (SITE_DIR / ".git").exists():
        return {
            "available": False,
            "reason": "site/ is not a git repo yet. See docs/PUBLISHING.md Step 5 to "
            "initialize it and add the gh-pages remote.",
            "changes": [],
        }
    porcelain = _git(SITE_DIR, "status", "--porcelain")
    if porcelain.returncode != 0:
        return {"available": False, "reason": porcelain.stderr.strip(), "changes": []}
    changes = [line for line in porcelain.stdout.splitlines() if line.strip()]
    branch = _git(SITE_DIR, "rev-parse", "--abbrev-ref", "HEAD")
    return {
        "available": True,
        "branch": branch.stdout.strip() if branch.returncode == 0 else "",
        "changes": changes,
    }


def commit_and_push(message: str, allow_ip_override: bool = False) -> dict:
    """Commit staged site/ changes and push. Blocks if leftover IPs are detected."""
    if not (SITE_DIR / ".git").exists():
        return {"ok": False, "error": "site/ is not a git repo. See docs/PUBLISHING.md Step 5."}

    offenders = scan_for_ips(SITE_DIR)
    if offenders and not allow_ip_override:
        return {
            "ok": False,
            "error": "Leftover internal IPs detected in published reports; push blocked.",
            "ip_offenders": offenders,
        }

    steps: List[dict] = []

    add = _git(SITE_DIR, "add", ".")
    steps.append({"cmd": "git add .", "code": add.returncode, "out": (add.stdout + add.stderr).strip()})
    if add.returncode != 0:
        return {"ok": False, "error": "git add failed", "steps": steps}

    commit = _git(SITE_DIR, "commit", "-m", message or "Publish Matrix G2 performance report")
    steps.append({"cmd": "git commit", "code": commit.returncode, "out": (commit.stdout + commit.stderr).strip()})
    # A non-zero commit code with "nothing to commit" is not fatal - still try to push.
    nothing_to_commit = "nothing to commit" in (commit.stdout + commit.stderr).lower()
    if commit.returncode != 0 and not nothing_to_commit:
        return {"ok": False, "error": "git commit failed", "steps": steps}

    push = _git(SITE_DIR, "push")
    steps.append({"cmd": "git push", "code": push.returncode, "out": (push.stdout + push.stderr).strip()})
    if push.returncode != 0:
        return {"ok": False, "error": "git push failed", "steps": steps}

    return {"ok": True, "steps": steps}
