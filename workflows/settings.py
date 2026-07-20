"""Settings workflow: rename displays, speakers, and sources via the admin room-settings
endpoint, then revert each rename.

Uses POST /api/room/settings, the endpoint confirmed (via passive capture of the Settings
panel's "Admin Password" unlock -> rename flow) to power renames for displays, speakers,
audio sources, and video sources, as well as per-display layout capability toggles
(pip_pap/quadSupport/wallSupport). Note: the room's own name is NOT renameable via this
endpoint - confirmed against the live device, which rejects it as an "Unsupported setting".
"""

import time
from typing import Any, Callable, Dict, Optional

from core.matrix_client import MatrixClient
from workflows._util import label


def _get_display_name(displays, display_id: str) -> str:
    for display in displays:
        if display.get("id") == display_id:
            return display.get("attributes", {}).get("name", "") or ""
    return ""


def _entity_name(settings: Dict[str, Any], key: str, entity_id: str) -> str:
    for item in settings.get(key, []) or []:
        if item.get("id") == entity_id:
            return item.get("name", "") or ""
    return ""


async def _rename_and_revert(
    page,
    client: MatrixClient,
    action_collector,
    actions: list,
    *,
    entity_label: str,
    action_type: str,
    payload_key: str,
    entity_id: Optional[str],
    get_name: Callable[[Dict[str, Any]], str],
) -> None:
    """Rename an entity (room/speaker/audio source/video source) via POST /api/room/settings,
    verify it reflects on GET /api/room/settings, then rename it back to the original name.

    Note: GET /api/room/settings can include sensitive camera credentials, so only the
    extracted name (never the raw settings blob) is stored in action before/after state.
    """
    original_name = get_name(client.get_room_settings())
    temp_name = f"{original_name} (test)" if original_name else "Test Name"

    for action_label, target_name in [("Rename", temp_name), ("Restore name for", original_name)]:
        details: Dict[str, Any] = {"target_name": target_name}
        if entity_id:
            details["entity_id"] = entity_id
        action = action_collector.start_action(
            name=f"{action_label} {entity_label} to '{target_name}'",
            action_type=action_type,
            before_state={"name": get_name(client.get_room_settings())},
            details=details,
        )
        api_start = time.perf_counter()
        try:
            if payload_key == "room":
                payload = {"room": {"name": target_name}}
            else:
                payload = {payload_key: [{"id": entity_id, "name": target_name}]}
            client.update_room_settings(payload)
            api_end = time.perf_counter()
            api_duration_ms = (api_end - api_start) * 1000

            ui_start = time.perf_counter()
            updated_name = ""
            for _ in range(50):
                updated_name = get_name(client.get_room_settings())
                if updated_name == target_name:
                    break
                await page.wait_for_timeout(100)
            ui_end = time.perf_counter()
            ui_duration_ms = (ui_end - ui_start) * 1000
            reflected = updated_name == target_name

            action_collector.end_action(
                success=True,
                after_state={"name": updated_name},
                api_calls=["POST /api/room/settings"],
                api_duration_ms=api_duration_ms,
                ui_duration_ms=ui_duration_ms,
                error=None if reflected else f"Note: {entity_label} name did not reflect within 5s (API call succeeded)",
            )
        except Exception as exc:
            api_end = time.perf_counter()
            action_collector.end_action(
                success=False,
                error=str(exc),
                api_calls=["POST /api/room/settings"],
                api_duration_ms=(api_end - api_start) * 1000,
            )
        actions.append(action.to_dict())


def _get_supported_layouts(displays, display_id: str):
    for display in displays:
        if display.get("id") == display_id:
            return display.get("attributes", {}).get("supportedLayouts", []) or []
    return []


# Maps each layout-capability flag (sent via POST /api/room/settings) to the layout
# code(s) it controls in the display's supportedLayouts (per docs/discovered_api_endpoints.md).
CAPABILITY_LAYOUTS = {
    "pip_pap": ["pip", "pap"],
    "quadSupport": ["quad"],
    "wallSupport": ["wall"],
}


async def run(session, interceptor, ui_monitor=None, **kwargs: Any) -> Dict[str, Any]:
    """Rename the first display, verify it reflects, then rename it back."""
    page = session.page
    room = session.room
    action_collector = kwargs.get("action_collector")
    actions = []

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
        print("[settings] No displays found")
        client.close()
        return {"workflow": "settings", "actions": [], "displays_found": 0}

    display_id = displays[0].get("id")
    original_name = _get_display_name(displays, display_id)
    display_label = label(original_name, display_id)
    temp_name = f"{original_name} (test)" if original_name else "Test Display"

    for action_label, target_name in [("Rename", temp_name), ("Restore name for", original_name)]:
        action = action_collector.start_action(
            name=f"{action_label} display {display_label} to '{target_name}'",
            action_type="room_settings_rename",
            before_state={"display_id": display_id, "name": _get_display_name(client.get_displays(), display_id)},
            details={"display_id": display_id, "target_name": target_name},
        )
        api_start = time.perf_counter()
        try:
            client.update_room_settings({"displays": [{"id": display_id, "name": target_name}]})
            api_end = time.perf_counter()
            api_duration_ms = (api_end - api_start) * 1000

            ui_start = time.perf_counter()
            updated_name = ""
            for _ in range(50):
                updated_name = _get_display_name(client.get_displays(), display_id)
                if updated_name == target_name:
                    break
                await page.wait_for_timeout(100)
            ui_end = time.perf_counter()
            ui_duration_ms = (ui_end - ui_start) * 1000
            reflected = updated_name == target_name

            action_collector.end_action(
                success=True,
                after_state={"display_id": display_id, "name": updated_name},
                api_calls=["POST /api/room/settings"],
                api_duration_ms=api_duration_ms,
                ui_duration_ms=ui_duration_ms,
                error=None if reflected else "Note: display name did not reflect within 5s (API call succeeded)",
            )
        except Exception as exc:
            api_end = time.perf_counter()
            action_collector.end_action(
                success=False,
                error=str(exc),
                api_calls=["POST /api/room/settings"],
                api_duration_ms=(api_end - api_start) * 1000,
            )
        actions.append(action.to_dict())

    # Note: the room's own name (settings.room.name) is not renameable via POST
    # /api/room/settings - confirmed against the live device, which rejects any payload
    # shape ({"room": {...}}, {"name": ...}, {"roomName": ...}) with
    # {"code": "rom_400_rs", "cause": "Unsupported setting."}. Only devices/sources
    # (displays, speakers, audio/video sources) are renameable this way.

    # Actions: rename the first speaker/audio source/video source, then restore each
    room_settings = client.get_room_settings()
    for kind, payload_key, action_type in [
        ("speaker", "speakers", "room_settings_rename_speaker"),
        ("audio source", "audioSources", "room_settings_rename_audio_source"),
        ("video source", "videoSources", "room_settings_rename_video_source"),
    ]:
        entities = room_settings.get(payload_key, []) or []
        if not entities:
            print(f"[settings] No {kind}s found, skipping rename")
            continue
        entity_id = entities[0].get("id")
        entity_label_text = label(entities[0].get("name", ""), entity_id)
        await _rename_and_revert(
            page, client, action_collector, actions,
            entity_label=f"{kind} {entity_label_text}",
            action_type=action_type,
            payload_key=payload_key,
            entity_id=entity_id,
            get_name=lambda s, key=payload_key, eid=entity_id: _entity_name(s, key, eid),
        )

    # Actions: toggle each layout capability flag, then restore its original state
    for field, related_layouts in CAPABILITY_LAYOUTS.items():
        current_supported = _get_supported_layouts(client.get_displays(), display_id)
        original_enabled = any(layout in current_supported for layout in related_layouts)

        for step_label, target_enabled in [("Toggle", not original_enabled), ("Restore", original_enabled)]:
            action = action_collector.start_action(
                name=f"{step_label} {field} for display {display_label} to {target_enabled}",
                action_type="room_settings_layout_capability",
                before_state={"display_id": display_id, "capability": field},
                details={"display_id": display_id, "capability": field, "target_enabled": target_enabled},
            )
            api_start = time.perf_counter()
            try:
                client.update_room_settings({"displays": [{"id": display_id, field: target_enabled}]})
                api_end = time.perf_counter()
                api_duration_ms = (api_end - api_start) * 1000

                ui_start = time.perf_counter()
                supported = current_supported
                for _ in range(50):
                    supported = _get_supported_layouts(client.get_displays(), display_id)
                    reflected_now = any(layout in supported for layout in related_layouts) == target_enabled
                    if reflected_now:
                        break
                    await page.wait_for_timeout(100)
                ui_end = time.perf_counter()
                ui_duration_ms = (ui_end - ui_start) * 1000
                reflected = any(layout in supported for layout in related_layouts) == target_enabled

                action_collector.end_action(
                    success=True,
                    after_state={"display_id": display_id, "supportedLayouts": supported},
                    api_calls=["POST /api/room/settings"],
                    api_duration_ms=api_duration_ms,
                    ui_duration_ms=ui_duration_ms,
                    error=None if reflected else f"Note: {field} change did not reflect in supportedLayouts within 5s (API call succeeded)",
                )
            except Exception as exc:
                api_end = time.perf_counter()
                action_collector.end_action(
                    success=False,
                    error=str(exc),
                    api_calls=["POST /api/room/settings"],
                    api_duration_ms=(api_end - api_start) * 1000,
                )
            actions.append(action.to_dict())

    client.close()

    return {"workflow": "settings", "actions": actions, "display_id": display_id}
