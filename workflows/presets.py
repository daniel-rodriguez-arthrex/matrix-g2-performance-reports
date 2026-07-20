"""Presets workflow: apply a room preset."""

import time
from typing import Any, Dict

from core.matrix_client import MatrixClient


async def _navigate_to_presets(page, room) -> None:
    """Navigate to the Presets page."""
    await page.goto(
        f"{room.base_url}/presets",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    await page.wait_for_timeout(1000)


async def run(session, interceptor, ui_monitor=None, **kwargs: Any) -> Dict[str, Any]:
    """Call a room preset via API and record action metrics."""
    page = session.page
    room = session.room
    action_collector = kwargs.get("action_collector")
    actions = []

    await _navigate_to_presets(page, room)

    client = MatrixClient(
        room.base_url,
        room.username,
        room.password,
        room.id,
        passcode=room.passcode,
    )
    client.authenticate()

    presets = client.get("api/room/presets") or []
    preset_index = None
    if presets:
        # Prefer a non-zero preset index (0 means sleep/unroute all)
        for preset in presets:
            idx = str(preset.get("index", ""))
            if idx and idx != "0":
                preset_index = idx
                break

    if not preset_index:
        print("[presets] No callable presets found")
        client.close()
        return {"workflow": "presets", "actions": [], "presets_found": len(presets)}

    action = action_collector.start_action(
        name=f"Call room preset {preset_index}",
        action_type="room_preset_call",
        before_state={"presets": presets},
        details={"preset_index": preset_index},
    )
    api_start = time.perf_counter()
    try:
        response = client.call_room_preset(preset_index)
        api_end = time.perf_counter()
        api_duration_ms = (api_end - api_start) * 1000

        # Verify room displays are still reachable after the preset call
        ui_start = time.perf_counter()
        displays = client.get_displays()
        ui_end = time.perf_counter()
        ui_duration_ms = (ui_end - ui_start) * 1000

        action_collector.end_action(
            success=True,
            after_state={"displays": displays},
            api_calls=["POST /api/room/presets/call"],
            api_duration_ms=api_duration_ms,
            ui_duration_ms=ui_duration_ms,
            error=None if displays else "Note: displays not reachable after preset call (API call succeeded)",
        )
    except Exception as exc:
        api_end = time.perf_counter()
        action_collector.end_action(
            success=False,
            error=str(exc),
            api_calls=["POST /api/room/presets/call"],
            api_duration_ms=(api_end - api_start) * 1000,
        )
    actions.append(action.to_dict())

    client.close()

    return {"workflow": "presets", "actions": actions, "presets_found": len(presets)}
