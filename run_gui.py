#!/usr/bin/env python
"""Launch the Matrix G2 Performance dashboard (local web GUI).

Usage:
    python run_gui.py [--host 127.0.0.1] [--port 5000] [--no-browser]

Opens a browser at the dashboard, where you can launch test runs, browse past
results, and publish sanitized reports to the public site - all without the CLI.
"""

import argparse
import threading
import webbrowser

from gui.app import app


def main() -> None:
    parser = argparse.ArgumentParser(description="Matrix G2 Performance dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind (default: 5000)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open a browser")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    print(f"Matrix G2 Performance dashboard running at {url}")
    print("Press Ctrl+C to stop.")
    # threaded=True so the log-polling requests aren't blocked by a running test.
    app.run(host=args.host, port=args.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
