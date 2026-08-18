"""Sharing workflow: grant then revoke a video source's share to another room.

Uses POST /api/room/share (network.Share command), confirmed via passive capture of
the live Matrix Routing UI's external-source sharing flow (grant with an "indefinite"
expiry, and revoke). Reflection is verified by reading the source's `sharedWith` list
back from GET /api/devices/videoSources.
"""

import time
from typing import Any, Dict, List, Optional

from core.matrix_client import MatrixClient
from workflows._util import label


def _find_own_source(video_sources: List[Dict[str, Any]], own_room_id: str) -> Optional[Dict[str, Any]]:
    """Return the first non-external (i.e. owned-by-this-room) video source."""
    for source in video_sources:
        attrs = source.get("attributes", {})
        if not attrs.get("external") and attrs.get("roomId") == own_room_id:
            return source
    return None


def _is_shared_with(video_sources: List[Dict[str, Any]], source_id: str, target_room_id: str) -> bool:
    for source in video_sources:
        if source.get("id") != source_id:
            continue
        shared_with = source.get("attributes", {}).get("sharedWith", []) or []
        return any(s.get("roomId") == target_room_id for s in shared_with)
    return False


async def _navigate_to_routing(page, room) -> None:
    """Navigate to the Control/Routing page."""
    await page.goto(
        f"{room.base_url}/control",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    await page.wait_for_timeout(1000)


async def run(session, interceptor, ui_monitor=None, **kwargs: Any) -> Dict[str, Any]:
    """Grant a share of a local video source to another room, verify it reflects, then revoke it."""
    page = session.page
    room = session.room
    action_collector = kwargs.get("action_collector")
    actions: List[Dict[str, Any]] = []

    await _navigate_to_routing(page, room)

    client = MatrixClient(
        room.base_url,
        room.username,
        room.password,
        room.id,
        passcode=room.passcode,
    )
    client.authenticate()

    own_room_id = client.get_room().get("roomId")
    other_rooms = [r for r in client.get_room_list() if r.get("roomId") != own_room_id]
    video_sources = client.get_video_sources()
    source = _find_own_source(video_sources, own_room_id) if own_room_id else None

    if not own_room_id or not other_rooms or not source:
        print(
            f"[sharing] Cannot share: own_room_id={own_room_id}, "
            f"other_rooms={len(other_rooms)}, own_source_found={bool(source)}"
        )
        client.close()
        return {"workflow": "sharing", "actions": [], "own_room_id": own_room_id}

    source_id = source.get("id")
    source_label = label(source.get("attributes", {}).get("name", ""), source_id)
    target_room = other_rooms[0]
    target_room_id = target_room.get("roomId")
    target_room_label = label(target_room.get("name", ""), target_room_id)

    for action_label, status, expect_shared in [
        ("Grant share of", "grant", True),
        ("Revoke share of", "revoke", False),
    ]:
        action = action_collector.start_action(
            name=f"{action_label} {source_label} with room {target_room_label}",
            action_type="source_share" if status == "grant" else "source_unshare",
            before_state={"source_id": source_id, "target_room_id": target_room_id},
            details={"source_id": source_id, "source_room": own_room_id, "requesting_room": target_room_id, "status": status},
        )
        api_start = time.perf_counter()
        try:
            client.share_source(source_id, own_room_id, target_room_id, status=status)
            api_end = time.perf_counter()
            api_duration_ms = (api_end - api_start) * 1000

            ui_start = time.perf_counter()
            shared = not expect_shared
            for _ in range(50):
                shared = _is_shared_with(client.get_video_sources(), source_id, target_room_id)
                if shared == expect_shared:
                    break
                await page.wait_for_timeout(100)
            ui_end = time.perf_counter()
            ui_duration_ms = (ui_end - ui_start) * 1000
            reflected = shared == expect_shared

            action_collector.end_action(
                success=True,
                after_state={"source_id": source_id, "target_room_id": target_room_id, "shared": shared},
                api_calls=["POST /api/room/share"],
                api_duration_ms=api_duration_ms,
                ui_duration_ms=ui_duration_ms,
                error=None if reflected else f"Note: share state did not reflect within 5s (API call succeeded)",
            )
        except Exception as exc:
            api_end = time.perf_counter()
            action_collector.end_action(
                success=False,
                error=str(exc),
                api_calls=["POST /api/room/share"],
                api_duration_ms=(api_end - api_start) * 1000,
            )
        actions.append(action.to_dict())

    client.close()

    return {
        "workflow": "sharing",
        "actions": actions,
        "source_id": source_id,
        "target_room_id": target_room_id,
    }
