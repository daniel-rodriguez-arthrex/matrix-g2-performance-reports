#!/usr/bin/env python
"""Convert a Matrix G2 performance report.html into a PDF for sharing.

Usage:
    python tools/html_to_pdf.py <path-to-report.html> [output.pdf]

If output.pdf is omitted, the PDF is written alongside the HTML file with the
same name (report.html -> report.pdf).

The report is a wide dashboard (1400px container + a wide actions table), so the
PDF is rendered in landscape and automatically scaled down just enough to fit the
full content width on the page. This preserves the layout, gradients, and colors
(print_background=True) without clipping the right-hand columns.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

# A4 landscape printable width at 96 CSS px/in, minus the left+right margins below.
MARGIN_IN = 0.4
A4_LANDSCAPE_WIDTH_IN = 11.69
PRINTABLE_WIDTH_PX = (A4_LANDSCAPE_WIDTH_IN - 2 * MARGIN_IN) * 96


def convert(html_path: Path, pdf_path: Path) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(html_path.resolve().as_uri())

        # Measure the real rendered content width and scale to fit the page width so
        # nothing is clipped. Cap at 1.0 so narrow reports are never enlarged.
        content_width = page.evaluate(
            "() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)"
        )
        scale = min(1.0, PRINTABLE_WIDTH_PX / content_width) if content_width else 1.0
        scale = max(0.1, round(scale, 2))  # Playwright requires scale in [0.1, 2]

        page.pdf(
            path=str(pdf_path),
            format="A4",
            landscape=True,
            scale=scale,
            print_background=True,
            margin={
                "top": f"{MARGIN_IN}in",
                "bottom": f"{MARGIN_IN}in",
                "left": f"{MARGIN_IN}in",
                "right": f"{MARGIN_IN}in",
            },
        )
        browser.close()


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python tools/html_to_pdf.py <path-to-report.html> [output.pdf]")
        sys.exit(1)

    html_path = Path(sys.argv[1])
    if not html_path.exists():
        print(f"File not found: {html_path}")
        sys.exit(1)

    pdf_path = Path(sys.argv[2]) if len(sys.argv) > 2 else html_path.with_suffix(".pdf")
    convert(html_path, pdf_path)
    print(f"PDF saved to: {pdf_path}")


if __name__ == "__main__":
    main()
