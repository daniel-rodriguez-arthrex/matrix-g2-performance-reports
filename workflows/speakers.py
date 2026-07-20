"""Speakers workflow: mute/unmute and change speaker volume."""

import time
from typing import Any, Dict

from core.matrix_client import MatrixClient
from workflows._util import label


async def _navigate_to_speakers(page, room) -> None:
    """Navigate to the Speakers page."""
    await page.goto(
        f"{room.base_url}/speakers",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    await page.wait_for_timeout(1000)


def _get_speaker_muted(speaker: Dict[str, Any]) -> bool:
    return speaker.get("attributes", {}).get("muted", False)


def _get_speaker_volume(speaker: Dict[str, Any]) -> int:
    return speaker.get("attributes", {}).get("volume", 0)


async def run(session, interceptor, ui_monitor=None, **kwargs: Any) -> Dict[str, Any]:
    """Mute and change speaker volume via API and record action metrics."""
    page = session.page
    room = session.room
    action_collector = kwargs.get("action_collector")
    actions = []

    await _navigate_to_speakers(page, room)

    client = MatrixClient(
        room.base_url,
        room.username,
        room.password,
        room.id,
        passcode=room.passcode,
    )
    client.authenticate()

    speakers = client.get_speakers()
    if not speakers:
        print("[speakers] No speakers found")
        client.close()
        return {"workflow": "speakers", "actions": [], "speakers_found": 0}

    speaker_id = speakers[0].get("id")
    before_speaker = client.get_speaker(speaker_id)
    speaker_label = label(before_speaker.get("attributes", {}).get("name", ""), speaker_id)
    target_mute = not _get_speaker_muted(before_speaker)

    # Action 1: Toggle speaker mute
    action = action_collector.start_action(
        name=f"{'Mute' if target_mute else 'Unmute'} speaker {speaker_label}",
        action_type="speaker_mute",
        before_state={"speaker": before_speaker},
        details={"speaker_id": speaker_id, "target_mute": target_mute},
    )
    api_start = time.perf_counter()
    try:
        response = client.mute_speaker(speaker_id, target_mute)
        api_end = time.perf_counter()
        api_duration_ms = (api_end - api_start) * 1000

        ui_start = time.perf_counter()
        updated_mute = _get_speaker_muted(before_speaker)
        for _ in range(50):
            speaker = client.get_speaker(speaker_id)
            updated_mute = _get_speaker_muted(speaker)
            if updated_mute == target_mute:
                break
            await page.wait_for_timeout(100)
        ui_end = time.perf_counter()
        ui_duration_ms = (ui_end - ui_start) * 1000
        reflected = updated_mute == target_mute

        action_collector.end_action(
            success=True,
            after_state={"speaker": speaker},
            api_calls=[f"POST /api/devices/speakers/{speaker_id}/mute"],
            api_duration_ms=api_duration_ms,
            ui_duration_ms=ui_duration_ms,
            error=None if reflected else "Note: speaker mute state did not reflect within 5s (API call succeeded)",
        )
    except Exception as exc:
        api_end = time.perf_counter()
        action_collector.end_action(
            success=False,
            error=str(exc),
            api_calls=[f"POST /api/devices/speakers/{speaker_id}/mute"],
            api_duration_ms=(api_end - api_start) * 1000,
        )
    actions.append(action.to_dict())

    # Action 2: Change speaker volume to 50%
    before_speaker = client.get_speaker(speaker_id)
    target_volume = 50
    action = action_collector.start_action(
        name=f"Set speaker {speaker_label} volume to {target_volume}%",
        action_type="speaker_volume",
        before_state={"speaker": before_speaker},
        details={"speaker_id": speaker_id, "target_volume": target_volume},
    )
    api_start = time.perf_counter()
    try:
        response = client.change_speaker_volume(speaker_id, target_volume)
        api_end = time.perf_counter()
        api_duration_ms = (api_end - api_start) * 1000

        ui_start = time.perf_counter()
        updated_volume = _get_speaker_volume(before_speaker)
        for _ in range(50):
            speaker = client.get_speaker(speaker_id)
            updated_volume = _get_speaker_volume(speaker)
            if updated_volume == target_volume:
                break
            await page.wait_for_timeout(100)
        ui_end = time.perf_counter()
        ui_duration_ms = (ui_end - ui_start) * 1000
        reflected = updated_volume == target_volume

        action_collector.end_action(
            success=True,
            after_state={"speaker": speaker},
            api_calls=[f"POST /api/devices/speakers/{speaker_id}/changeVolume"],
            api_duration_ms=api_duration_ms,
            ui_duration_ms=ui_duration_ms,
            error=None if reflected else "Note: speaker volume did not reflect within 5s (API call succeeded)",
        )
    except Exception as exc:
        api_end = time.perf_counter()
        action_collector.end_action(
            success=False,
            error=str(exc),
            api_calls=[f"POST /api/devices/speakers/{speaker_id}/changeVolume"],
            api_duration_ms=(api_end - api_start) * 1000,
        )
    actions.append(action.to_dict())

    client.close()

    return {"workflow": "speakers", "actions": actions, "speakers_found": len(speakers)}
