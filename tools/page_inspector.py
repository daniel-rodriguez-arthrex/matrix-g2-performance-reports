#!/usr/bin/env python
"""Headless page inspector: dump selectors and data-testid values from a live page."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv()

from core.session_manager import SessionManager


async def inspect(room_id: str, headless: bool, path: str = "/app", selector: str = None) -> None:
    async with SessionManager(room_id=room_id, headless=headless, output_dir="results") as session:
        page = session.page
        if path and path != "/app":
            await page.goto(f"{session.room.base_url}{path}", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        title = await page.title()
        url = page.url
        print(f"URL: {url}")
        print(f"Title: {title}")

        if selector:
            try:
                count = await page.locator(selector).count()
                print(f"\nSelector '{selector}' count: {count}")
                if count > 0:
                    html = await page.locator(selector).first.inner_html()
                    print(f"\nInner HTML of '{selector}':\n{html[:2000]}")
                return
            except Exception as exc:
                print(f"\nError locating selector '{selector}': {exc}")
                return

        testids = await page.evaluate(
            """() => {
                const ids = new Set();
                document.querySelectorAll('[data-testid]').forEach(el => ids.add(el.dataset.testid));
                return Array.from(ids);
            }"""
        )
        print("\n[data-testid] values:")
        print(json.dumps(testids, indent=2))

        ids = await page.evaluate(
            """() => {
                const ids = new Set();
                document.querySelectorAll('[id]').forEach(el => ids.add(el.id));
                return Array.from(ids).slice(0, 50);
            }"""
        )
        print("\n[id] values (first 50):")
        print(json.dumps(ids, indent=2))

        classes = await page.evaluate(
            """() => {
                const set = new Set();
                document.querySelectorAll('[class]').forEach(el => {
                    el.classList.forEach(c => set.add(c));
                });
                return Array.from(set).slice(0, 50);
            }"""
        )
        print("\nClass names (first 50):")
        print(json.dumps(classes, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Matrix G2 page selectors")
    parser.add_argument("--room", default="OR1", help="Room ID")
    parser.add_argument("--path", default="/app", help="Path to open (relative to base_url)")
    parser.add_argument("--selector", default=None, help="Selector to dump inner HTML for")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    args = parser.parse_args()
    asyncio.run(inspect(args.room, args.headless, args.path, args.selector))


if __name__ == "__main__":
    main()
