"""Camera workflow: exercise all PTZ move directions and recall every camera preset."""

import time
from typing import Any, Dict

from core.matrix_client import MatrixClient
from workflows._util import label

# All supported PTZ move directions confirmed against the live device API:
# up/down/left/right = pan/tilt, tele = zoom in, wide = zoom out.
PTZ_DIRECTIONS = ["up", "down", "left", "right", "tele", "wide"]


async def _navigate_to_camera(page, room) -> None:
    """Navigate to the Camera page."""
    await page.goto(
        f"{room.base_url}/camera",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    await page.wait_for_timeout(1000)


async def run(session, interceptor, ui_monitor=None, **kwargs: Any) -> Dict[str, Any]:
    """Perform every PTZ move direction and recall every camera preset, recording action metrics."""
    page = session.page
    room = session.room
    action_collector = kwargs.get("action_collector")
    actions = []

    await _navigate_to_camera(page, room)

    client = MatrixClient(
        room.base_url,
        room.username,
        room.password,
        room.id,
        passcode=room.passcode,
    )
    client.authenticate()

    camera_id = "1"
    camera = client.get_camera(camera_id)
    if not camera or not camera.get("id"):
        print(f"[camera] Camera {camera_id} not found")
        client.close()
        return {"workflow": "camera", "actions": []}

    camera_id = camera.get("id", camera_id)
    presets = camera.get("presets") or []
    preset_indexes = [p.get("presetIndex") for p in presets if p.get("presetIndex") is not None]
    preset_names = {p.get("presetIndex"): p.get("name", "") for p in presets}
    if not preset_indexes:
        preset_indexes = [1]

    # Actions: move camera in every supported PTZ direction
    for direction in PTZ_DIRECTIONS:
        action = action_collector.start_action(
            name=f"Move camera {camera_id} {direction}",
            action_type="camera_move",
            details={"camera_id": camera_id, "direction": direction},
        )
        api_start = time.perf_counter()
        try:
            response = client.move_camera(camera_id, direction)
            api_end = time.perf_counter()
            api_duration_ms = (api_end - api_start) * 1000

            # Verify camera is still reachable after the move
            ui_start = time.perf_counter()
            status = client.get_camera_status(camera_id)
            ui_end = time.perf_counter()
            ui_duration_ms = (ui_end - ui_start) * 1000

            action_collector.end_action(
                success=True,
                error=None if status is not None else "Note: camera status check failed after move (API call succeeded)",
                api_calls=[f"POST /api/cameras/{camera_id}/move"],
                api_duration_ms=api_duration_ms,
                ui_duration_ms=ui_duration_ms,
            )
        except Exception as exc:
            api_end = time.perf_counter()
            action_collector.end_action(
                success=False,
                error=str(exc),
                api_calls=[f"POST /api/cameras/{camera_id}/move"],
                api_duration_ms=(api_end - api_start) * 1000,
            )
        actions.append(action.to_dict())

    # Actions: recall every camera preset
    for preset_index in preset_indexes:
        preset_label = label(preset_names.get(preset_index, ""), str(preset_index))
        action = action_collector.start_action(
            name=f"Recall camera {camera_id} preset {preset_label}",
            action_type="camera_preset_call",
            details={"camera_id": camera_id, "preset_id": preset_index},
        )
        api_start = time.perf_counter()
        try:
            response = client.call_camera_preset(camera_id, preset_index)
            api_end = time.perf_counter()
            api_duration_ms = (api_end - api_start) * 1000

            # Verify camera is still reachable after preset recall
            ui_start = time.perf_counter()
            status = client.get_camera_status(camera_id)
            ui_end = time.perf_counter()
            ui_duration_ms = (ui_end - ui_start) * 1000

            action_collector.end_action(
                success=True,
                error=None if status is not None else "Note: camera status check failed after preset recall (API call succeeded)",
                api_calls=[f"POST /api/cameras/{camera_id}/presets/call"],
                api_duration_ms=api_duration_ms,
                ui_duration_ms=ui_duration_ms,
            )
        except Exception as exc:
            api_end = time.perf_counter()
            action_collector.end_action(
                success=False,
                error=str(exc),
                api_calls=[f"POST /api/cameras/{camera_id}/presets/call"],
                api_duration_ms=(api_end - api_start) * 1000,
            )
        actions.append(action.to_dict())

    client.close()

    return {"workflow": "camera", "actions": actions, "directions_tested": PTZ_DIRECTIONS, "presets_tested": preset_indexes}
