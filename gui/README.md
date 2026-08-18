# Matrix G2 Performance Dashboard (GUI)

A local web dashboard over the existing CLI. It lets teammates launch test runs,
browse past results, and publish sanitized reports without using the command line.
It never reimplements test/publish logic - it shells out to the same `run_perf.py`
and `tools/publish_report.py` you would run by hand.

## Launch

```powershell
pip install -r requirements.txt   # first time (adds flask)
python run_gui.py                 # or double-click run_gui.bat
```

The dashboard opens at http://127.0.0.1:5000/.

Options: `--host`, `--port`, `--no-browser`.

## Tabs

- **Run Test** — pick mode (scenario/passive), room, scenario, iterations, headless,
  and thresholds. Mirrors `run_perf.py` flags. Live log streams as the run executes;
  **Stop** sends a graceful interrupt (same as Ctrl+C) so reports are still exported.
  Only one run at a time (a run drives a single browser).
- **Results** — cards for every `report.html` under `results/`. **View Report** opens
  the interactive report; **Publish** jumps to the Publish tab preloaded.
- **Publish** — runs the full `docs/PUBLISHING.md` pipeline in two explicit steps:
  1. **Sanitize & Stage** — sanitizes the report, copies it into `site/`, rebuilds the
     hub index, runs a leftover-IP scan, and shows pending git changes.
  2. **Confirm & Push** — `git add/commit/push` in `site/`. Push is **blocked** if the
     IP scan finds anything (override requires an explicit checkbox).

## Prerequisites for publishing

The `site/` folder must already be a git repo with a `gh-pages` remote configured
(see `docs/PUBLISHING.md` Steps 4-5). The GUI does not set up git auth; git errors
(e.g. no remote, auth prompt) are surfaced in the UI.

## Notes

- Localhost only, no auth — matches the current trust model. Bind to `0.0.0.0` only on
  a trusted LAN if teammates need remote access.
- Credentials/IPs still come only from `.env`; nothing sensitive is added by the GUI.
