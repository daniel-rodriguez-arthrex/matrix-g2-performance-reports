"""Audio routing workflow: route and unroute an audio source to/from a speaker.

Uses the same generic POST /api/room/route and /api/room/unroute endpoints confirmed
working for video routing (see routing.py) - the API's "network.route"/"network.unroute"
commands take a sourceId/destinationId pair and are not video-specific."""

from typing import Any, Dict, List, Optional

import time

from core.matrix_client import MatrixClient
from workflows._util import label


def _get_speaker_slot_source(speaker: Dict[str, Any]) -> str:
    """Return the currently routed audio source id for the first speaker slot."""
    slots = speaker.get("attributes", {}).get("slots", [])
    if slots:
        return slots[0].get("routedSourceId", "") or ""
    return ""


def _find_first_source(sources: List[Dict[str, Any]]) -> Optional[str]:
    """Return the first available audio source id."""
    if sources:
        return sources[0].get("id")
    return None


def _get_name(items: List[Dict[str, Any]], item_id: str) -> str:
    """Return the speaker/source name for an id, or empty string if not found."""
    for item in items:
        if item.get("id") == item_id:
            return item.get("attributes", {}).get("name", "") or ""
    return ""


async def _navigate_to_speakers(page, room) -> None:
    """Navigate to the Speakers page."""
    await page.goto(
        f"{room.base_url}/speakers",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    await page.wait_for_timeout(1000)


async def run(session, interceptor, ui_monitor=None, **kwargs: Any) -> Dict[str, Any]:
    """Route and unroute an audio source to every speaker while recording action metrics."""
    page = session.page
    room = session.room
    action_collector = kwargs.get("action_collector")
    actions: List[Dict[str, Any]] = []

    await _navigate_to_speakers(page, room)

    client = MatrixClient(
        room.base_url,
        room.username,
        room.password,
        room.id,
        passcode=room.passcode,
    )
    client.authenticate()

    audio_sources = client.get_audio_sources()
    speakers = client.get_speakers()
    source_id = _find_first_source(audio_sources)
    speaker_ids = [s.get("id") for s in speakers if s.get("id")]

    if not source_id or not speaker_ids:
        print(f"[audio_routing] Cannot route: audio_sources={len(audio_sources)}, speakers={len(speakers)}")
        client.close()
        return {"workflow": "audio_routing", "actions": [], "audio_sources_found": len(audio_sources), "speakers_found": len(speakers)}

    source_label = label(_get_name(audio_sources, source_id), source_id)

    for speaker_id in speaker_ids:
        speaker_label = label(_get_name(speakers, speaker_id), speaker_id)

        # Action: Route audio source to this speaker
        action = action_collector.start_action(
            name=f"Route audio {source_label} to {speaker_label}",
            action_type="audio_route",
            before_state={"speaker_id": speaker_id},
            details={"source_id": source_id, "speaker_id": speaker_id, "slot": "1"},
        )
        api_start = time.perf_counter()
        try:
            client.route_source(source_id, speaker_id)
            api_end = time.perf_counter()
            api_duration_ms = (api_end - api_start) * 1000

            ui_start = time.perf_counter()
            updated_source = ""
            for _ in range(50):
                current_speakers = client.get_speakers()
                for speaker in current_speakers:
                    if speaker.get("id") == speaker_id:
                        updated_source = _get_speaker_slot_source(speaker)
                        break
                if updated_source == source_id:
                    break
                await page.wait_for_timeout(100)
            ui_end = time.perf_counter()
            ui_duration_ms = (ui_end - ui_start) * 1000

            action_collector.end_action(
                success=True,
                after_state={"speaker_id": speaker_id, "routed_source_id": updated_source},
                api_calls=["POST /api/room/route"],
                api_duration_ms=api_duration_ms,
                ui_duration_ms=ui_duration_ms,
                error=None if updated_source == source_id else "Note: speaker state did not reflect audio route within 5s (API call succeeded)",
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

        # Action: Unroute audio from this speaker
        action = action_collector.start_action(
            name=f"Unroute audio from {speaker_label}",
            action_type="audio_unroute",
            before_state={"speaker_id": speaker_id},
            details={"speaker_id": speaker_id, "slot": "1"},
        )
        api_start = time.perf_counter()
        try:
            client.unroute_source(speaker_id)
            api_end = time.perf_counter()
            api_duration_ms = (api_end - api_start) * 1000

            ui_start = time.perf_counter()
            updated_source = source_id
            for _ in range(50):
                current_speakers = client.get_speakers()
                for speaker in current_speakers:
                    if speaker.get("id") == speaker_id:
                        updated_source = _get_speaker_slot_source(speaker)
                        break
                if updated_source != source_id:
                    break
                await page.wait_for_timeout(100)
            ui_end = time.perf_counter()
            ui_duration_ms = (ui_end - ui_start) * 1000

            action_collector.end_action(
                success=True,
                after_state={"speaker_id": speaker_id, "routed_source_id": updated_source},
                api_calls=["POST /api/room/unroute"],
                api_duration_ms=api_duration_ms,
                ui_duration_ms=ui_duration_ms,
                error=None if updated_source != source_id else "Note: speaker state did not reflect audio unroute within 5s (API call succeeded)",
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
        "workflow": "audio_routing",
        "speaker_ids": speaker_ids,
        "source_id": source_id,
        "actions": actions,
    }
