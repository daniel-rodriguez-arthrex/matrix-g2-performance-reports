#!/usr/bin/env python
"""Interactive selector inspector for Matrix G2.

Validates selectors against a live page or enables interactive click-to-pick
mode. In interactive mode, press Alt+I to toggle inspection, then click any
element to print a Playwright selector for it.
"""

import argparse
import asyncio
import json
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv()

from config import get_room_config
from core.session_manager import SessionManager
from metrics.selector_validator import SelectorValidator


SELECTOR_PICKER_JS = """
(() => {
  let inspectMode = false;

  const buildSelector = (el) => {
    if (el.dataset && el.dataset.testid) return `[data-testid="${el.dataset.testid}"]`;
    if (el.id) return `#${el.id}`;
    const classes = Array.from(el.classList).filter(Boolean).join('.');
    if (classes) return `${el.tagName.toLowerCase()}.${classes}`;
    return el.tagName.toLowerCase();
  };

  const highlight = (el) => {
    const original = el.style.outline;
    el.style.outline = '3px solid magenta';
    setTimeout(() => { el.style.outline = original; }, 1000);
  };

  document.addEventListener('keydown', (e) => {
    if (e.altKey && e.key.toLowerCase() === 'i') {
      inspectMode = !inspectMode;
      console.log('Selector inspector mode:', inspectMode ? 'ON' : 'OFF');
      e.preventDefault();
    }
  }, true);

  document.addEventListener('mouseover', (e) => {
    if (!inspectMode) return;
    e.target.style.outline = '2px dashed cyan';
  }, true);

  document.addEventListener('mouseout', (e) => {
    if (!inspectMode) return;
    e.target.style.outline = '';
  }, true);

  document.addEventListener('click', (e) => {
    if (!inspectMode) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    const selector = buildSelector(e.target);
    const text = (e.target.textContent || '').trim().slice(0, 80);
    window.onSelectorPicked(selector, text);
    highlight(e.target);
    console.log('Selector picked:', selector);
  }, true);

  console.log('Selector inspector loaded. Press Alt+I to toggle, click to pick.');
})();
"""


async def validate_selector(room_id: str, selector: str, strategy: str, headless: bool) -> None:
    room = get_room_config(room_id)
    async with SessionManager(room_id=room.id, headless=headless, output_dir="results") as session:
        validator = SelectorValidator(session.page)
        result = await validator.validate(selector, strategy)
        print(json.dumps(result.to_dict(), indent=2))


async def interactive_mode(room_id: str, headless: bool) -> None:
    room = get_room_config(room_id)
    async with SessionManager(room_id=room.id, headless=headless, output_dir="results") as session:
        page = session.page

        await page.expose_function("onSelectorPicked", lambda selector, text: print(
            f"SELECTOR: {selector}  TEXT: {text}"
        ))
        await page.evaluate(SELECTOR_PICKER_JS)
        print("Interactive selector inspector loaded.")
        print("Navigate to Matrix G2, press Alt+I to toggle inspection, then click elements.")

        stop = asyncio.Event()
        page.on("close", lambda: stop.set())

        def signal_handler(signum, frame):
            loop = asyncio.get_event_loop()
            loop.call_soon_threadsafe(stop.set)

        signal.signal(signal.SIGINT, signal_handler)
        await stop.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description="Matrix G2 selector inspector")
    parser.add_argument("--room", default=None, help="Room ID")
    parser.add_argument("--selector", default=None, help="Selector to validate")
    parser.add_argument("--strategy", default="css", help="Selector strategy (css, xpath, id, text, role, testid)")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    args = parser.parse_args()

    room_id = args.room or "OR1"
    if args.selector:
        asyncio.run(validate_selector(room_id, args.selector, args.strategy, args.headless))
    else:
        asyncio.run(interactive_mode(room_id, args.headless))


if __name__ == "__main__":
    main()
