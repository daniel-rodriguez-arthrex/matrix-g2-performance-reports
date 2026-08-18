"""Settings workflow: rename displays, speakers, and sources via the admin room-settings
endpoint, then revert each rename.

Uses POST /api/room/settings, the endpoint confirmed (via passive capture of the Settings
panel's "Admin Password" unlock -> rename flow) to power renames for displays, speakers,
audio sources, and video sources, as well as per-display layout toggles
(pip_pap/quad/wall - the fields the Settings "Layout Options" checkboxes write). Note: the
room's own name is NOT renameable via this endpoint - confirmed against the live device,
which rejects it as an "Unsupported setting".
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


def _get_display_settings_obj(settings: Dict[str, Any], display_id: str) -> Dict[str, Any]:
    for d in settings.get("displays", []) or []:
        if d.get("id") == display_id:
            return dict(d)
    return {"id": display_id}


def _get_settings_field(settings: Dict[str, Any], display_id: str, field: str) -> Any:
    for d in settings.get("displays", []) or []:
        if d.get("id") == display_id:
            return d.get(field)
    return None


# The user-facing layout toggles are the "PIP/PAP", "Quad View", "Wall" checkboxes in the
# Settings -> Layout Options panel, which write the pip_pap / quad / wall display fields
# (lowercase, no "Support" suffix - confirmed via live HAR capture, see
# docs/quadsupport_investigation.md). The exact check/uncheck sequence and the quad/wall ->
# pip_pap dependency are encoded in `checkbox_sequence` inside run().
#
# NOTE: quadSupport/wallSupport are intentionally NOT toggled - they are read-only
# hardware-capability flags (which physical output supports quad/wall), preset per display
# and not changeable by any UI action or API call. They are not what the checkboxes write.
LAYOUT_FLAGS = ("pip_pap", "quad", "wall")
LAYOUT_LABELS = {"pip_pap": "PIP/PAP", "quad": "Quad View", "wall": "Wall"}
LAYOUT_CODES = {"pip_pap": ["pip", "pap"], "quad": ["quad"], "wall": ["wall"]}


def _flags_state(settings: Dict[str, Any], display_id: str) -> Dict[str, bool]:
    obj = _get_display_settings_obj(settings, display_id)
    return {f: bool(obj.get(f, False)) for f in LAYOUT_FLAGS}


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
            # Use the FULL display object (not a partial {id, name}) - the device silently
            # drops partial writes for the name field too (returns success but does not
            # persist), same as the layout flags. See docs/quadsupport_investigation.md.
            rename_obj = dict(_get_display_settings_obj(client.get_room_settings(), display_id))
            rename_obj["name"] = target_name
            client.update_room_settings({"displays": [rename_obj]})
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

    # Actions: exercise the Settings "Layout Options" checkboxes (PIP/PAP, Quad View, Wall)
    # exactly as a user would, and verify each change reflects in the display's supportedLayouts.
    #
    # Dependency confirmed on the live device (see docs/quadsupport_investigation.md): quad and
    # wall each require pip_pap to be enabled - a write that sets quad/wall true while pip_pap is
    # false is silently dropped (returns "success" but never persists). Likewise, disabling
    # pip_pap while quad/wall are still on leaves an invalid/partial state. So we drive the
    # checkboxes in the same order the real UI does - check pip_pap -> quad -> wall on the way in,
    # then uncheck wall -> quad -> pip_pap on the way out - and always POST the full explicit
    # flag combination so the display is never left in an invalid state.
    # Pick the display to exercise layout toggles on. Display order from the API varies, and
    # only displays whose hardware supports quad/wall (read-only quadSupport/wallSupport flags)
    # can reflect them - so prefer such a display for the richest coverage, falling back to the
    # first display if none support quad/wall.
    settings_displays = client.get_room_settings().get("displays", []) or []
    cap_display_obj = next(
        (d for d in settings_displays if d.get("quadSupport") or d.get("wallSupport")),
        None,
    ) or _get_display_settings_obj(client.get_room_settings(), display_id)
    cap_display_id = cap_display_obj.get("id", display_id)
    cap_display_label = label(_get_display_name(client.get_displays(), cap_display_id), cap_display_id)
    original_flags = {f: bool(cap_display_obj.get(f, False)) for f in ("pip_pap", "quad", "wall")}

    # Only exercise the layouts THIS display's hardware can actually do. pip_pap has no
    # capability gate; quad/wall are gated by the read-only quadSupport/wallSupport flags -
    # on a display whose hardware doesn't support them (e.g. HDMI outputs), the toggle
    # persists but quad/wall can never appear in supportedLayouts, so testing reflection there
    # is meaningless (would always report a false "did not reflect"). See
    # docs/quadsupport_investigation.md.
    active_fields = ["pip_pap"]
    if bool(cap_display_obj.get("quadSupport", False)):
        active_fields.append("quad")
    if bool(cap_display_obj.get("wallSupport", False)):
        active_fields.append("wall")

    # Build the check/uncheck sequence: enable pip_pap -> quad -> wall (respecting the
    # quad/wall -> pip_pap dependency), then uncheck in reverse. Each step's target is the full
    # cumulative flag combination, and every step's changed layout code(s) are expected to be
    # PRESENT after a check / ABSENT after an uncheck.
    # (step label, target flag combination, changed field, its layout code(s), expect present)
    checkbox_sequence = []
    running = {f: False for f in LAYOUT_FLAGS}
    for field in active_fields:
        running[field] = True
        checkbox_sequence.append((f"Check {LAYOUT_LABELS[field]}", dict(running), field, LAYOUT_CODES[field], True))
    for field in reversed(active_fields):
        running[field] = False
        checkbox_sequence.append((f"Uncheck {LAYOUT_LABELS[field]}", dict(running), field, LAYOUT_CODES[field], False))

    for step_label, target_flags, changed_field, related_layouts, expect_present in checkbox_sequence:
        action = action_collector.start_action(
            name=f"{step_label} for display {cap_display_label}",
            action_type="room_settings_layout_capability",
            before_state={"display_id": cap_display_id, "flags": _flags_state(client.get_room_settings(), cap_display_id)},
            details={"display_id": cap_display_id, "field": changed_field, "target_flags": target_flags},
        )
        api_start = time.perf_counter()
        try:
            # Full display object, with the whole target flag combination applied at once.
            # Retry on rom_206_rs ("Partial update"): the device intermittently rejects a
            # settings write as partial when it arrives while the previous write's backend
            # processing (DeviceReloadEvent) is still in flight - a brief pause and retry
            # clears it. The real UI avoids this simply by human-paced (~1s) clicking.
            api_response = None
            response_code = None
            for attempt in range(4):
                payload_obj = dict(_get_display_settings_obj(client.get_room_settings(), cap_display_id))
                payload_obj.update(target_flags)
                api_response = client.update_room_settings({"displays": [payload_obj]})
                response_code = api_response.get("code") if isinstance(api_response, dict) else None
                if response_code != "rom_206_rs":
                    break
                await page.wait_for_timeout(500)
            api_duration_ms = (time.perf_counter() - api_start) * 1000
            if response_code and response_code != "rom_200_rs":
                action_collector.end_action(
                    success=False,
                    after_state={"display_id": cap_display_id, "api_response": api_response},
                    api_calls=["POST /api/room/settings"],
                    api_duration_ms=api_duration_ms,
                    error=f"{step_label} rejected by device: {response_code} ({api_response.get('msg')})",
                )
                actions.append(action.to_dict())
                continue

            # Verify the full flag combination persisted (readback), not just the response code.
            persist_start = time.perf_counter()
            persisted = False
            for _ in range(30):
                if _flags_state(client.get_room_settings(), cap_display_id) == target_flags:
                    persisted = True
                    break
                await page.wait_for_timeout(100)
            persist_duration_ms = (time.perf_counter() - persist_start) * 1000

            if not persisted:
                action_collector.end_action(
                    success=False,
                    after_state={"display_id": cap_display_id, "flags": _flags_state(client.get_room_settings(), cap_display_id)},
                    api_calls=["POST /api/room/settings", "GET /api/room/settings"],
                    api_duration_ms=api_duration_ms,
                    ui_duration_ms=persist_duration_ms,
                    error=f"{step_label} returned success ({response_code}) but flags did not reach "
                    f"{target_flags} - see docs/quadsupport_investigation.md",
                )
                actions.append(action.to_dict())
                continue

            # Verify the change reflects in supportedLayouts - the "seeing it in the display
            # settings" signal. Present after a check, absent after an uncheck.
            ui_start = time.perf_counter()
            supported = _get_supported_layouts(client.get_displays(), cap_display_id)
            for _ in range(50):
                supported = _get_supported_layouts(client.get_displays(), cap_display_id)
                if all(layout in supported for layout in related_layouts) == expect_present:
                    break
                await page.wait_for_timeout(100)
            ui_duration_ms = (time.perf_counter() - ui_start) * 1000
            reflected = all(layout in supported for layout in related_layouts) == expect_present

            action_collector.end_action(
                success=True,
                after_state={"display_id": cap_display_id, "flags": target_flags, "supportedLayouts": supported},
                api_calls=["POST /api/room/settings", "GET /api/room/settings", "GET /api/devices/displays"],
                api_duration_ms=api_duration_ms,
                ui_duration_ms=ui_duration_ms,
                error=None if reflected else f"Note: {changed_field} change did not reflect in supportedLayouts within 5s (setting itself persisted correctly)",
            )
        except Exception as exc:
            action_collector.end_action(
                success=False,
                error=str(exc),
                api_calls=["POST /api/room/settings"],
                api_duration_ms=(time.perf_counter() - api_start) * 1000,
            )
        actions.append(action.to_dict())

    # Restore the display's original layout flags (a valid combination as originally read).
    try:
        restore_obj = dict(_get_display_settings_obj(client.get_room_settings(), cap_display_id))
        restore_obj.update(original_flags)
        client.update_room_settings({"displays": [restore_obj]})
    except Exception as exc:
        print(f"[settings] Failed to restore original layout flags: {exc}")

    client.close()

    return {"workflow": "settings", "actions": actions, "display_id": display_id}
