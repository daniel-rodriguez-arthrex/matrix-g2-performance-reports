#!/usr/bin/env python
"""Matrix G2 Performance Test Suite

Entry point for passive monitoring and automated workflow scenarios.
"""

import argparse
import asyncio
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load environment variables before importing project modules
load_dotenv()

ROOT = Path(__file__).parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_environment, get_room_config, get_workflow, list_workflows
from core import SessionManager, WorkflowRunner
from metrics import ApiInterceptor, SelectorValidator, UiMonitor
from metrics.websocket_monitor import WebSocketMonitor
from reporting import Aggregator, CsvExporter, HtmlReport


def _session_dir(output_dir: Path, room: str, mode: str, timestamp: str) -> Path:
    return output_dir / f"{mode}_{room}_{timestamp}"


async def _auto_login(page, room) -> None:
    """Navigate to the app and complete room selection/passcode entry via the real UI.

    Mirrors the proven flow used by automated workflows (e.g. workflows/routing.py's
    _navigate_to_app). The app's own init handshake (getAccessToken/pair) does not
    accept a pre-seeded localStorage token, so this drives the actual passcode keyboard
    instead of trying to short-circuit it.
    """
    await page.goto(f"{room.base_url}/app", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(1500)

    room_list = page.locator("#room-selection-rooms li")
    if await room_list.count() > 0:
        for i in range(await room_list.count()):
            item = room_list.nth(i)
            text = await item.text_content()
            if text and text.strip() == room.id:
                try:
                    await item.locator("span").first.click()
                except Exception:
                    await item.click()
                break
        await page.wait_for_timeout(1000)

        if room.passcode:
            for digit in room.passcode:
                for key in await page.locator(".keyboard li button").all():
                    key_text = await key.text_content()
                    if key_text and key_text.strip() == digit:
                        await key.dispatch_event("click")
                        await page.wait_for_timeout(100)
                        break
            await page.wait_for_timeout(500)
            done_button = page.locator("#room-selection-done-button button")
            try:
                for _ in range(20):
                    if await done_button.count() > 0 and await done_button.is_enabled():
                        break
                    await page.wait_for_timeout(250)
                if await done_button.count() > 0 and await done_button.is_enabled():
                    await done_button.dispatch_event("click")
                    await page.wait_for_timeout(1500)
            except Exception:
                pass

    control_tab = page.locator("#control-tab")
    if await control_tab.count() > 0:
        try:
            await control_tab.click()
            await page.wait_for_timeout(1000)
        except Exception:
            pass


async def _wait_for_stop(duration: Optional[float] = None) -> None:
    """Block until the user interrupts with Ctrl+C, or until `duration` seconds have
    elapsed (whichever comes first). A duration allows the session to auto-stop and
    export cleanly when run in contexts where a real Ctrl+C/SIGINT can't be delivered
    (e.g. a background/non-interactive process)."""
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    handler = lambda: stop_event.set()  # noqa: E731

    try:
        loop.add_signal_handler(signal.SIGINT, handler)
    except (NotImplementedError, ValueError):
        # Windows fallback: use signal.signal and marshal to the loop thread
        def fallback_handler(signum, frame):
            loop.call_soon_threadsafe(stop_event.set)

        signal.signal(signal.SIGINT, fallback_handler)

    try:
        if duration is not None:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=duration)
            except asyncio.TimeoutError:
                pass
        else:
            await stop_event.wait()
    finally:
        try:
            loop.remove_signal_handler(signal.SIGINT)
        except (NotImplementedError, ValueError):
            signal.signal(signal.SIGINT, signal.default_int_handler)


async def passive_mode(args: argparse.Namespace) -> None:
    """Run a headed browser session and capture traffic while the user navigates."""
    env = get_environment()
    room_id = args.room or env["room_id"]
    room = get_room_config(room_id)
    output_dir = Path(args.output_dir or env["output_dir"])
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session_dir = _session_dir(output_dir, room_id, "passive", timestamp)
    session_dir.mkdir(parents=True, exist_ok=True)

    async with SessionManager(
        room_id=room_id,
        headless=False,
        output_dir=session_dir,
        skip_auth_injection=True,
    ) as session:
        page = session.page
        interceptor = ApiInterceptor(page, room.base_url, api_threshold_ms=args.api_threshold)
        await interceptor.start()
        ws_monitor = WebSocketMonitor(page)
        ws_monitor.start()

        if args.skip_login:
            print(f"Passive monitoring started: {room.login_url()}")
            print("Auto-completing room selection/passcode via the UI...")
            await _auto_login(page, room)
            print("Logged in - continue navigating manually.")
        else:
            print(f"Passive monitoring started: {room.login_url()}")
            print("Log in manually and navigate Matrix G2.")
        if args.duration:
            print(f"Will auto-stop and generate reports after {args.duration}s (or Ctrl+C sooner).")
        else:
            print("Press Ctrl+C to stop and generate reports.")

        try:
            await _wait_for_stop(args.duration)
        except asyncio.CancelledError:
            pass

        print("\nGenerating reports...")
        await interceptor.stop()

        timestamp_str = datetime.now().isoformat(timespec="seconds")
        calls = [c.to_dict() for c in interceptor.get_calls()]
        endpoints = interceptor.get_unique_endpoints()
        ws_frames = ws_monitor.get_frames()

        # Validate selectors for all known workflows on the current page state
        validator = SelectorValidator(page)
        selectors = []
        for wf_name in list_workflows():
            for sel in get_workflow(wf_name).selectors:
                selectors.append({"selector": sel, "strategy": "css"})
        selector_results = [r.to_dict() for r in await validator.validate_list(selectors)]

        exporter = CsvExporter(session_dir)
        exporter.export_api_calls(calls, timestamp_str, room_id, "passive")
        exporter.export_endpoints(endpoints)
        exporter.export_selectors(selector_results)
        exporter.export_summary(interceptor.get_summary(), timestamp_str, room_id, "passive")
        if ws_frames:
            exporter.export_websocket_frames(ws_frames, timestamp_str, room_id, "passive")

        report_data = {
            "session": {
                "room": room_id,
                "workflow": "passive",
                "timestamp": timestamp_str,
            },
            "api_calls": calls,
            "endpoints": endpoints,
            "selectors": selector_results,
            "ws_frames": ws_frames,
            "summary": interceptor.get_summary(),
        }
        HtmlReport().generate(session_dir / "report.html", report_data)
        print(f"Reports saved to: {session_dir}")


async def scenario_mode(args: argparse.Namespace) -> None:
    """Run an automated workflow scenario and export metrics."""
    env = get_environment()
    room_id = args.room or env["room_id"]
    room = get_room_config(room_id)
    headless = args.headless if args.headless is not None else env["headless"]
    output_dir = Path(args.output_dir or env["output_dir"])
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session_dir = _session_dir(output_dir, room_id, args.scenario, timestamp)
    session_dir.mkdir(parents=True, exist_ok=True)

    async with SessionManager(room_id=room_id, headless=headless, output_dir=session_dir) as session:
        page = session.page
        interceptor = ApiInterceptor(page, room.base_url, api_threshold_ms=args.api_threshold)
        await interceptor.start()
        ws_monitor = WebSocketMonitor(page)
        ws_monitor.start()
        ui_monitor = UiMonitor(page)

        runner = WorkflowRunner(session, interceptor, ui_monitor)
        results = await runner.run(
            args.scenario,
            iterations=args.iterations,
            api_threshold=args.api_threshold,
        )

        aggregator = Aggregator()
        summary = aggregator.aggregate(results)

        # Collect API calls across all iterations from the runner summaries
        all_calls = [c for r in results for c in r.get("calls", [])]
        # Collect action-level metrics (the real workflow operations, with the API
        # endpoint(s) each one called) across all iterations.
        all_actions = [a for r in results for a in r.get("actions", [])]
        endpoints = interceptor.get_unique_endpoints()
        ws_frames = ws_monitor.get_frames()

        # Validate selectors for the workflow on the final page state
        validator = SelectorValidator(page)
        if args.scenario == "all":
            selector_items = [
                {"selector": sel, "strategy": "css"}
                for wf in list_workflows()
                for sel in get_workflow(wf).selectors
            ]
        else:
            selector_items = [
                {"selector": sel, "strategy": "css"}
                for sel in get_workflow(args.scenario).selectors
            ]
        selector_results = [r.to_dict() for r in await validator.validate_list(selector_items)]

        exporter = CsvExporter(session_dir)
        timestamp_str = datetime.now().isoformat(timespec="seconds")
        exporter.export_api_calls(all_calls, timestamp_str, room_id, args.scenario)
        exporter.export_endpoints(endpoints)
        exporter.export_selectors(selector_results)
        exporter.export_ui_timings(ui_monitor.get_summary(), timestamp_str, room_id, args.scenario)
        exporter.export_actions(all_actions, timestamp_str, room_id, args.scenario)
        exporter.export_actions_json(all_actions, timestamp_str, room_id, args.scenario)
        exporter.export_summary(summary, timestamp_str, room_id, args.scenario)
        if ws_frames:
            exporter.export_websocket_frames(ws_frames, timestamp_str, room_id, args.scenario)

        report_data = {
            "session": {
                "room": room_id,
                "workflow": args.scenario,
                "timestamp": timestamp_str,
            },
            "api_calls": all_calls,
            "endpoints": endpoints,
            "selectors": selector_results,
            "ws_frames": ws_frames,
            "summary": summary,
        }
        HtmlReport().generate(session_dir / "report.html", report_data)
        print(f"Scenario '{args.scenario}' complete. Reports saved to: {session_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Matrix G2 Performance Test Suite")
    parser.add_argument(
        "--mode",
        choices=["passive", "scenario"],
        default="passive",
        help="Run mode: passive monitoring or automated scenario",
    )
    parser.add_argument(
        "--scenario",
        default="routing",
        help="Workflow scenario to run (used with --mode scenario)",
    )
    parser.add_argument("--room", default=None, help="Room ID")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (only for scenario mode)",
    )
    parser.add_argument(
        "--skip-login",
        action="store_true",
        help="Passive mode only: pre-authenticate via the API and inject the token, "
        "landing directly on the app instead of the manual room-selection/passcode flow.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Passive mode only: auto-stop and generate reports after this many seconds "
        "instead of waiting for Ctrl+C. Useful when running as a background process where "
        "a real Ctrl+C/SIGINT can't be delivered.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of iterations for scenario mode",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for reports",
    )
    parser.add_argument(
        "--api-threshold",
        type=int,
        default=None,
        help="API SLA threshold in milliseconds",
    )
    args = parser.parse_args()

    if args.mode == "passive":
        asyncio.run(passive_mode(args))
    else:
        asyncio.run(scenario_mode(args))


if __name__ == "__main__":
    main()
