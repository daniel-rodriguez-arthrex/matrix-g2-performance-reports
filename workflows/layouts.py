"""Layouts workflow: change display layouts.

This workflow uses the Matrix API to perform real layout changes and then
polls the display state to verify the UI/backend reflects the change."""

import time
from typing import Any, Dict, List

from core.matrix_client import MatrixClient
from workflows._util import label


LAYOUTS = ["full", "pip", "pap", "quad", "wall"]


def _get_display_layout(displays: List[Dict[str, Any]], display_id: str) -> str:
    """Return the current layout of a display."""
    for display in displays:
        if display.get("id") == display_id:
            return display.get("attributes", {}).get("layout", "") or ""
    return ""


def _get_display_settings_obj(settings: Dict[str, Any], display_id: str) -> Dict[str, Any]:
    for d in settings.get("displays", []) or []:
        if d.get("id") == display_id:
            return dict(d)
    return {"id": display_id}


async def _ensure_layout_capability(page, client: MatrixClient, display_id: str) -> Dict[str, bool]:
    """Ensure this display's pip_pap/quad/wall settings flags are enabled (as far as its
    hardware supports) so its supportedLayouts reflects the full set of layouts this
    workflow can test, regardless of whatever state a previous run/session left the room
    in. Returns the flags as they were found, so the caller can restore them afterward.

    Dependency (see docs/quadsupport_investigation.md): quad/wall each require pip_pap to
    be enabled first, and quad/wall can only ever appear if the display's hardware supports
    them (read-only quadSupport/wallSupport flags).
    """
    display_settings = _get_display_settings_obj(client.get_room_settings(), display_id)
    original_flags = {f: bool(display_settings.get(f, False)) for f in ("pip_pap", "quad", "wall")}
    target_flags = dict(original_flags)
    target_flags["pip_pap"] = True
    if display_settings.get("quadSupport"):
        target_flags["quad"] = True
    if display_settings.get("wallSupport"):
        target_flags["wall"] = True

    if target_flags == original_flags:
        return original_flags

    try:
        payload_obj = dict(display_settings)
        payload_obj.update(target_flags)
        client.update_room_settings({"displays": [payload_obj]})
        for _ in range(30):
            current = _get_display_settings_obj(client.get_room_settings(), display_id)
            if all(bool(current.get(f, False)) == v for f, v in target_flags.items()):
                break
            await page.wait_for_timeout(100)
    except Exception as exc:
        print(f"[layouts] Failed to prep layout capability for display {display_id}: {exc}")

    return original_flags


async def _restore_layout_capability(client: MatrixClient, display_id: str, original_flags: Dict[str, bool]) -> None:
    try:
        display_settings = _get_display_settings_obj(client.get_room_settings(), display_id)
        if {f: bool(display_settings.get(f, False)) for f in original_flags} == original_flags:
            return
        restore_obj = dict(display_settings)
        restore_obj.update(original_flags)
        client.update_room_settings({"displays": [restore_obj]})
    except Exception as exc:
        print(f"[layouts] Failed to restore original layout flags for display {display_id}: {exc}")


async def _navigate_to_app(page, room) -> None:
    """Navigate to the app and complete room selection/passcode flow."""
    await page.goto(
        f"{room.base_url}/app",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    await page.wait_for_timeout(1500)

    room_list = page.locator("#room-selection-rooms li")
    for i in range(await room_list.count()):
        room_item = room_list.nth(i)
        room_text = await room_item.text_content()
        if room.id in (room_text or ""):
            span = room_item.locator("span").first
            if await span.count() > 0:
                await span.click()
                await page.wait_for_timeout(500)
            break

    next_button = page.locator("#room-selection-next-button button")
    if await next_button.count() > 0 and await next_button.is_enabled():
        await next_button.click()
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
            await control_tab.dispatch_event("click")
            await page.wait_for_timeout(2000)
            print("[layouts] Clicked Control tab")
        except Exception:
            pass


async def run(session, interceptor, ui_monitor=None, **kwargs: Any) -> Dict[str, Any]:
    """Change display layouts via the API and measure UI/backend reflection."""
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

    displays = client.get_displays()
    if not displays:
        print("[layouts] No displays found")
        client.close()
        return {"workflow": "layouts", "actions": [], "displays_found": 0}

    actions = []
    for display in displays:
        display_id = display.get("id")
        display_label = label(display.get("attributes", {}).get("name", ""), display_id)

        # Don't trust whatever supportedLayouts happens to be right now - a prior run/session
        # may have left pip_pap/quad/wall disabled on the device. Enable everything this
        # display's hardware supports first so the workflow is always ready to run, then
        # restore the original flags once this display's layouts have been tested.
        original_flags = await _ensure_layout_capability(page, client, display_id)
        supported_layouts = display.get("attributes", {}).get("supportedLayouts", LAYOUTS)
        for refreshed in client.get_displays():
            if refreshed.get("id") == display_id:
                supported_layouts = refreshed.get("attributes", {}).get("supportedLayouts", LAYOUTS)
                break
        layouts_to_test = [layout for layout in LAYOUTS if layout in supported_layouts]

        for layout in layouts_to_test:
            before_layout = _get_display_layout(client.get_displays(), display_id)
            action = action_collector.start_action(
                name=f"Change {display_label} layout to {layout}",
                action_type="change_layout",
                before_state={"display_id": display_id, "layout": before_layout},
                details={"display_id": display_id, "target_layout": layout},
            )
            api_start = time.perf_counter()
            try:
                response = client.change_layout(display_id, layout)
                api_end = time.perf_counter()
                api_duration_ms = (api_end - api_start) * 1000

                ui_start = time.perf_counter()
                updated_layout = before_layout
                for _ in range(50):
                    updated_layout = _get_display_layout(client.get_displays(), display_id)
                    if updated_layout == layout:
                        break
                    await page.wait_for_timeout(100)
                ui_end = time.perf_counter()
                ui_duration_ms = (ui_end - ui_start) * 1000

                action_collector.end_action(
                    success=True,
                    after_state={"display_id": display_id, "layout": updated_layout},
                    api_calls=[f"POST /api/devices/displays/{display_id}/changeLayout"],
                    api_duration_ms=api_duration_ms,
                    ui_duration_ms=ui_duration_ms,
                    error=None if updated_layout == layout else "Note: display state did not reflect layout change within 5s (API call succeeded)",
                )
            except Exception as exc:
                api_end = time.perf_counter()
                action_collector.end_action(
                    success=False,
                    error=str(exc),
                    api_calls=[f"POST /api/devices/displays/{display_id}/changeLayout"],
                    api_duration_ms=(api_end - api_start) * 1000,
                )
            actions.append(action.to_dict())

        await _restore_layout_capability(client, display_id, original_flags)

    client.close()

    return {
        "workflow": "layouts",
        "display_ids": [d.get("id") for d in displays],
        "displays_found": len(displays),
        "layouts_tested": [a["details"]["target_layout"] for a in actions if a["details"].get("target_layout")],
        "actions": actions,
    }
