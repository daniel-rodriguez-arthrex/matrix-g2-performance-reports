#!/usr/bin/env python
"""Sanitize a Matrix G2 performance report before publishing it publicly.

Removes internal infrastructure details (currently: IPv4 addresses, optionally with
a port, and any embedded credentials in URLs) so reports can be safely hosted on a
public GitHub Pages site. Device friendly names and IDs are intentionally preserved.

Usage (standalone):
    python tools/sanitize_report.py <input.html> [output.html]

Or import `sanitize_html(text)` for use in the publish pipeline.
"""

import re
import sys
from pathlib import Path

# IPv4 address, optionally followed by :port  ->  redacted host placeholder.
_IPV4_PORT = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b")

# Credentials embedded in a URL, e.g. https://user:pass@host  ->  strip the creds.
_URL_CREDS = re.compile(r"(https?://)[^/\s:@]+:[^/\s:@]+@")

REDACTED_HOST = "[internal-host]"


def sanitize_html(text: str) -> str:
    """Return a copy of `text` with internal IPs and URL-embedded credentials masked."""
    text = _URL_CREDS.sub(r"\1", text)
    text = _IPV4_PORT.sub(REDACTED_HOST, text)
    return text


def sanitize_file(input_path: Path, output_path: Path) -> int:
    """Sanitize a file in place or to a new path. Returns the number of IPs masked."""
    raw = input_path.read_text(encoding="utf-8")
    ip_count = len(_IPV4_PORT.findall(raw))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(sanitize_html(raw), encoding="utf-8")
    return ip_count


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python tools/sanitize_report.py <input.html> [output.html]")
        sys.exit(1)
    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"File not found: {input_path}")
        sys.exit(1)
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else input_path
    masked = sanitize_file(input_path, output_path)
    print(f"Sanitized {input_path} -> {output_path} ({masked} IP references masked)")


if __name__ == "__main__":
    main()
