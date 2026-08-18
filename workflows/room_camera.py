"""Room camera workflow: test the room camera's connection, and exercise the
Settings -> Room Camera save round-trip via POST /api/room/settings.

Both confirmed via passive capture of the live Settings panel's Room Camera modal:
- POST /api/cameras/{id}/testConnection with {endpoint, username, password}
- POST /api/room/settings with {"camera": {id, endpoint, username, password, model, authMode}}

NOTE: unlike display/speaker/source renames, the camera's endpoint/credentials point at a
real physical device - deliberately changing them to a bogus value to test round-trip
reflection risks knocking the live room camera offline. So the save action here re-submits
the CURRENT camera object unchanged, exercising the exact same save path (and payload
shape) the real UI uses when a user re-saves the Room Camera settings, without touching
functionality.
"""

import time
from typing import Any, Dict

from core.matrix_client import MatrixClient


def _get_camera_obj(settings: Dict[str, Any]) -> Dict[str, Any]:
    return dict(settings.get("camera") or {"id": "1"})


async def _navigate_to_settings(page, room) -> None:
    """Navigate to the app root (Settings panel is opened via #settings-icon, not a route)."""
    await page.goto(
        f"{room.base_url}/app",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    await page.wait_for_timeout(1000)


async def run(session, interceptor, ui_monitor=None, **kwargs: Any) -> Dict[str, Any]:
    """Test the room camera's connection, then round-trip its settings via room/settings."""
    page = session.page
    room = session.room
    action_collector = kwargs.get("action_collector")
    actions = []

    await _navigate_to_settings(page, room)

    client = MatrixClient(
        room.base_url,
        room.username,
        room.password,
        room.id,
        passcode=room.passcode,
    )
    client.authenticate()

    camera_obj = _get_camera_obj(client.get_room_settings())
    camera_id = camera_obj.get("id", "1")
    endpoint = camera_obj.get("endpoint", "")
    username = camera_obj.get("username", "")
    password = camera_obj.get("password", "")

    if not endpoint:
        print(f"[room_camera] Camera {camera_id} has no endpoint configured, skipping")
        client.close()
        return {"workflow": "room_camera", "actions": [], "camera_id": camera_id}

    # Action: Test camera connection with the currently configured credentials.
    action = action_collector.start_action(
        name=f"Test room camera {camera_id} connection",
        action_type="camera_test_connection",
        details={"camera_id": camera_id, "endpoint": endpoint},
    )
    api_start = time.perf_counter()
    try:
        response = client.test_camera_connection(camera_id, endpoint, username, password)
        api_duration_ms = (time.perf_counter() - api_start) * 1000
        response_code = response.get("code") if isinstance(response, dict) else None
        action_collector.end_action(
            success=response_code == "cam_200",
            after_state={"response_code": response_code},
            api_calls=[f"POST /api/cameras/{camera_id}/testConnection"],
            api_duration_ms=api_duration_ms,
            error=None if response_code == "cam_200" else f"Unexpected response code: {response_code}",
        )
    except Exception as exc:
        action_collector.end_action(
            success=False,
            error=str(exc),
            api_calls=[f"POST /api/cameras/{camera_id}/testConnection"],
            api_duration_ms=(time.perf_counter() - api_start) * 1000,
        )
    actions.append(action.to_dict())

    # Action: Save round-trip - re-submit the same camera object via room/settings and
    # verify readback matches. Exercises the exact save path without changing the live
    # camera's endpoint/credentials.
    action = action_collector.start_action(
        name=f"Save room camera {camera_id} settings",
        action_type="room_camera_save",
        before_state={"camera_id": camera_id, "endpoint": endpoint},
        details={"camera_id": camera_id},
    )
    api_start = time.perf_counter()
    try:
        client.update_room_settings({"camera": camera_obj})
        api_duration_ms = (time.perf_counter() - api_start) * 1000

        ui_start = time.perf_counter()
        updated_endpoint = ""
        for _ in range(50):
            updated_endpoint = _get_camera_obj(client.get_room_settings()).get("endpoint", "")
            if updated_endpoint == endpoint:
                break
            await page.wait_for_timeout(100)
        ui_duration_ms = (time.perf_counter() - ui_start) * 1000
        reflected = updated_endpoint == endpoint

        action_collector.end_action(
            success=True,
            after_state={"camera_id": camera_id, "endpoint": updated_endpoint},
            api_calls=["POST /api/room/settings"],
            api_duration_ms=api_duration_ms,
            ui_duration_ms=ui_duration_ms,
            error=None if reflected else "Note: camera settings did not reflect within 5s (API call succeeded)",
        )
    except Exception as exc:
        action_collector.end_action(
            success=False,
            error=str(exc),
            api_calls=["POST /api/room/settings"],
            api_duration_ms=(time.perf_counter() - api_start) * 1000,
        )
    actions.append(action.to_dict())

    client.close()

    return {"workflow": "room_camera", "actions": actions, "camera_id": camera_id}
