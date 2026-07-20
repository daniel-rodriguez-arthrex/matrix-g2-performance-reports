"""Routing workflow: route and unroute a source to/from a display.

This workflow uses the Matrix API to perform real routing actions and then
polls the display state to verify the UI/backend reflects the change."""

from typing import Any, Dict, List, Optional

import time

from core.matrix_client import MatrixClient
from workflows._util import label


def _get_display_slot_source(display: Dict[str, Any]) -> str:
    """Return the currently routed source id for the first display slot."""
    slots = display.get("attributes", {}).get("slots", [])
    if slots:
        return slots[0].get("routedSourceId", "") or ""
    return ""


def _find_first_source(sources: List[Dict[str, Any]]) -> Optional[str]:
    """Return the first available source id."""
    if sources:
        return sources[0].get("id")
    return None


def _get_display_ids(displays: List[Dict[str, Any]]) -> List[str]:
    """Return every display id."""
    return [d.get("id") for d in displays if d.get("id")]


def _get_name(items: List[Dict[str, Any]], item_id: str) -> str:
    """Return the display/source name for an id, or empty string if not found."""
    for item in items:
        if item.get("id") == item_id:
            return item.get("attributes", {}).get("name", "") or ""
    return ""


def _get_routed_state(client: MatrixClient) -> Dict[str, Any]:
    """Capture current displays and sources for state comparison."""
    displays = client.get_displays()
    sources = client.get_video_sources()
    return {
        "displays": displays,
        "sources": sources,
        "display_ids": _get_display_ids(displays),
        "first_source_id": _find_first_source(sources),
    }


async def _navigate_to_app(page, room) -> None:
    """Navigate to the app and complete room selection/passcode flow."""
    await page.goto(
        f"{room.base_url}/app",
        wait_until="domcontentloaded",
        timeout=30000,
    )
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


async def run(session, interceptor, ui_monitor=None, **kwargs: Any) -> Dict[str, Any]:
    """Route and unroute a source to every display while recording action metrics."""
    page = session.page
    room = session.room
    action_collector = kwargs.get("action_collector")

    await _navigate_to_app(page, room)

    client = MatrixClient(
        room.base_url,
        room.username,
        room.password,
        room.id,
        passcode=room.passcode,
    )
    client.authenticate()

    before_state = _get_routed_state(client)
    display_ids = before_state["display_ids"]
    source_id = before_state["first_source_id"]
    source_label = label(_get_name(before_state["sources"], source_id), source_id) if source_id else source_id

    actions = []

    if not display_ids or not source_id:
        print(f"[routing] Cannot route: display_ids={display_ids}, source_id={source_id}")
        client.close()
        return {"workflow": "routing", "display_ids": display_ids, "source_id": source_id, "actions": actions}

    for display_id in display_ids:
        display_label = label(_get_name(before_state["displays"], display_id), display_id)

        # Action: Route source to this display
        action = action_collector.start_action(
            name=f"Route {source_label} to {display_label}",
            action_type="route",
            before_state={"display_id": display_id},
            details={"source_id": source_id, "display_id": display_id, "slot": "1"},
        )
        api_start = time.perf_counter()
        try:
            client.route_source(source_id, display_id)
            api_end = time.perf_counter()
            api_duration_ms = (api_end - api_start) * 1000

            # Poll display state for up to 5 seconds to verify UI/backend reflects change
            ui_start = time.perf_counter()
            updated_source = ""
            for _ in range(50):
                displays = client.get_displays()
                for display in displays:
                    if display.get("id") == display_id:
                        updated_source = _get_display_slot_source(display)
                        break
                if updated_source == source_id:
                    break
                await page.wait_for_timeout(100)
            ui_end = time.perf_counter()
            ui_duration_ms = (ui_end - ui_start) * 1000

            action_collector.end_action(
                success=True,
                after_state={"display_id": display_id, "routed_source_id": updated_source},
                api_calls=["POST /api/room/route"],
                api_duration_ms=api_duration_ms,
                ui_duration_ms=ui_duration_ms,
                error=None if updated_source == source_id else "Note: display state did not reflect route within 5s (API call succeeded)",
            )
        except Exception as exc:
            api_end = time.perf_counter()
            action_collector.end_action(
                success=False,
                error=str(exc),
                api_calls=["POST /api/room/route"],
                api_duration_ms=(api_end - api_start) * 1000,
            )
        actions.append(action.to_dict())

        # Action: Unroute from this display
        action = action_collector.start_action(
            name=f"Unroute from {display_label}",
            action_type="unroute",
            before_state={"display_id": display_id},
            details={"display_id": display_id, "slot": "1"},
        )
        api_start = time.perf_counter()
        try:
            client.unroute_source(display_id)
            api_end = time.perf_counter()
            api_duration_ms = (api_end - api_start) * 1000

            ui_start = time.perf_counter()
            updated_source = source_id
            for _ in range(50):
                displays = client.get_displays()
                for display in displays:
                    if display.get("id") == display_id:
                        updated_source = _get_display_slot_source(display)
                        break
                if updated_source != source_id:
                    break
                await page.wait_for_timeout(100)
            ui_end = time.perf_counter()
            ui_duration_ms = (ui_end - ui_start) * 1000

            action_collector.end_action(
                success=True,
                after_state={"display_id": display_id, "routed_source_id": updated_source},
                api_calls=["POST /api/room/unroute"],
                api_duration_ms=api_duration_ms,
                ui_duration_ms=ui_duration_ms,
                error=None if updated_source != source_id else "Note: display state did not reflect unroute within 5s (API call succeeded)",
            )
        except Exception as exc:
            api_end = time.perf_counter()
            action_collector.end_action(
                success=False,
                error=str(exc),
                api_calls=["POST /api/room/unroute"],
                api_duration_ms=(api_end - api_start) * 1000,
            )
        actions.append(action.to_dict())

    client.close()

    return {
        "workflow": "routing",
        "display_ids": display_ids,
        "source_id": source_id,
        "actions": actions,
    }
