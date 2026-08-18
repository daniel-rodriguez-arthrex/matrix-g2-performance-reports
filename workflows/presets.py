"""Presets workflow: apply a room preset, and rename a preset then revert it.

Both endpoints use the same rooms.preset.add command against POST /api/room/presets, confirmed
via passive capture of the Presets page's "Save"/rename flows - but the HTTP verb changes the
behavior: POST overwrites the target preset's routing/layout with whatever is currently live
(the real "save current state" action - not safe to fire with arbitrary live state in automated
testing), while PUT does a metadata-only rename that leaves the preset's saved routing/layout
untouched. The rename-and-revert action here uses PUT, mirroring the safe rename/revert pattern
in workflows/settings.py, so it never risks clobbering a real preset's configuration."""

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

    # Actions: rename the same preset to a temp name, verify it reflects (routing/layout
    # untouched), then rename it back to its original name. Uses PUT (metadata-only rename),
    # never POST, so the preset's saved routing/layout state is never at risk.
    target_preset = next((p for p in presets if str(p.get("index")) == preset_index), presets[0])
    original_name = target_preset.get("name", "")
    temp_name = f"{original_name} (test)" if original_name else "Test Preset"

    for action_label, target_name in [("Rename", temp_name), ("Restore name for", original_name)]:
        action = action_collector.start_action(
            name=f"{action_label} preset {preset_index} to '{target_name}'",
            action_type="room_preset_rename",
            before_state={"preset_index": preset_index},
            details={"preset_index": preset_index, "target_name": target_name},
        )
        api_start = time.perf_counter()
        try:
            response = client.rename_room_preset(preset_index, target_name)
            api_end = time.perf_counter()
            api_duration_ms = (api_end - api_start) * 1000
            response_code = response.get("code") if isinstance(response, dict) else None

            ui_start = time.perf_counter()
            updated_presets = []
            renamed = False
            for _ in range(50):
                updated_presets = client.get("api/room/presets") or []
                renamed = any(str(p.get("index")) == preset_index and p.get("name") == target_name for p in updated_presets)
                if renamed:
                    break
                await page.wait_for_timeout(100)
            ui_duration_ms = (time.perf_counter() - ui_start) * 1000

            action_collector.end_action(
                success=response_code == "rpm_200_r1",
                after_state={"preset_index": preset_index, "name": target_name, "renamed": renamed},
                api_calls=["PUT /api/room/presets", "GET /api/room/presets"],
                api_duration_ms=api_duration_ms,
                ui_duration_ms=ui_duration_ms,
                error=None if response_code == "rpm_200_r1" else f"Unexpected response code: {response_code}",
            )
        except Exception as exc:
            action_collector.end_action(
                success=False,
                error=str(exc),
                api_calls=["PUT /api/room/presets"],
                api_duration_ms=(time.perf_counter() - api_start) * 1000,
            )
        actions.append(action.to_dict())

    client.close()

    return {"workflow": "presets", "actions": actions, "presets_found": len(presets)}
