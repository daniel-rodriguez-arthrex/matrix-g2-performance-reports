"""Flask app for the Matrix G2 Performance dashboard.

Run via ``python run_gui.py`` (which also opens a browser). Routes are intentionally
thin: they translate GUI actions into the same operations teammates run from the CLI.
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, render_template, request, send_from_directory

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from config.environments import _load_rooms_from_env  # noqa: E402
from config.workflows import WORKFLOWS  # noqa: E402

from . import publisher, results  # noqa: E402
from .runner import TestRunner, build_cli_args  # noqa: E402

app = Flask(__name__)
runner = TestRunner()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config")
def api_config():
    try:
        rooms = sorted(_load_rooms_from_env().keys())
    except Exception:
        rooms = []
    workflows = [
        {"name": name, "description": cfg.description}
        for name, cfg in WORKFLOWS.items()
    ]
    return jsonify({"rooms": rooms, "workflows": workflows})


@app.route("/api/run", methods=["POST"])
def api_run():
    payload = request.get_json(force=True, silent=True) or {}
    try:
        cli_args = build_cli_args(payload)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    try:
        job = runner.start(cli_args)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    return jsonify(job.snapshot())


@app.route("/api/run/status")
def api_run_status():
    since = request.args.get("since", default=0, type=int)
    job = runner.job
    if job is None:
        return jsonify({"status": "idle", "lines": [], "total_lines": 0})
    return jsonify(job.snapshot(since=since))


@app.route("/api/run/stop", methods=["POST"])
def api_run_stop():
    stopped = runner.stop()
    return jsonify({"stopped": stopped})


@app.route("/api/results")
def api_results():
    return jsonify({"reports": results.list_reports()})


@app.route("/reports/<path:subpath>")
def serve_report(subpath: str):
    # Only ever serve files from within results/. send_from_directory blocks traversal.
    full = (PROJECT_ROOT / subpath).resolve()
    results_root = (PROJECT_ROOT / "results").resolve()
    if results_root != full and results_root not in full.parents:
        abort(403)
    return send_from_directory(PROJECT_ROOT, subpath)


@app.route("/api/publish/stage", methods=["POST"])
def api_publish_stage():
    payload = request.get_json(force=True, silent=True) or {}
    rel_dir = (payload.get("dir") or "").strip()
    title = (payload.get("title") or "").strip()
    make_pdf = bool(payload.get("make_pdf", True))
    if not rel_dir:
        return jsonify({"error": "Missing report directory."}), 400
    try:
        summary = publisher.stage_publish(rel_dir, title=title, make_pdf=make_pdf)
    except (ValueError, FileNotFoundError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # pragma: no cover - surface publish errors to the UI
        return jsonify({"error": f"Publish failed: {exc}"}), 500
    return jsonify(summary)


@app.route("/api/publish/status")
def api_publish_status():
    return jsonify(publisher.git_status())


@app.route("/api/publish/push", methods=["POST"])
def api_publish_push():
    payload = request.get_json(force=True, silent=True) or {}
    message = (payload.get("message") or "").strip()
    allow_ip_override = bool(payload.get("allow_ip_override", False))
    result = publisher.commit_and_push(message, allow_ip_override=allow_ip_override)
    return jsonify(result), (200 if result.get("ok") else 400)
