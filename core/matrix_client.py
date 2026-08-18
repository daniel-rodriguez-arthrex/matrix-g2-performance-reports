import json
import os
import time
from typing import Any, Dict, List, Optional

import requests
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


class MatrixClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        room_id: str,
        passcode: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.room_id = room_id
        self.passcode = passcode
        self.token: Optional[str] = None  # deprecated
        self.access_token: Optional[str] = None  # room/pair token for read endpoints
        self.auth_token: Optional[str] = None    # admin token from getAuthToken
        self.session = requests.Session()
        self.session.verify = False

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def authenticate(self, pair_key: Optional[str] = None) -> str:
        """Authenticate and obtain both room access token and admin auth token.

        The app uses two JWT tokens: a room access token (from getAccessToken)
        for read endpoints and an admin token (from getAuthToken) for state-
        changing POST endpoints.
        """
        # 1) Room pair token (for GET /api/devices/displays, etc.)
        pair_key = pair_key or self.passcode or self.room_id
        if pair_key:
            try:
                response = self.session.post(
                    self._url("api/app/getAccessToken"),
                    json={"pairKey": pair_key, "pairHash": "", "roomUrl": self.base_url},
                    headers=self.headers(),
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()
                self.access_token = data.get("accessToken") or data.get("token")
            except Exception:
                pass

        # 2) Admin auth token for UI/admin state checks (optional; state-change POSTs
        #    work with the access token as well, but we keep the auth token when available)
        if self.username and self.password and self.access_token:
            try:
                response = self.session.post(
                    self._url("api/app/getAuthToken"),
                    json={"username": self.username, "password": self.password},
                    headers=self.headers(),
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()
                self.auth_token = data.get("token") or data.get("accessToken")
            except Exception:
                pass

        # Backwards compatibility: prefer admin token, then access token
        self.token = self.auth_token or self.access_token
        return self.token

    def headers(self) -> Dict[str, str]:
        """Return headers with the API's custom token headers.

        The API middleware reads `accesstoken` and `authtoken` headers, not
        standard `Authorization: Bearer`.
        """
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["accesstoken"] = self.access_token
        if self.auth_token:
            headers["authtoken"] = self.auth_token
        return headers

    def _send_with_retry(
        self,
        method: str,
        url: str,
        *,
        max_retries: int = 4,
        base_delay: float = 0.5,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Send a request, retrying on HTTP 429 (Too Many Requests) with exponential
        backoff. The device rate-limits when many requests arrive in quick succession
        (e.g. rapid state-reflection polling across a scenario); this lets transient
        limits self-heal instead of failing an action.

        Note: backoff waits only occur on an actual 429, so normal-path timing is
        unaffected. A Retry-After response header, if present, takes precedence.
        """
        delay = base_delay
        response = None
        for attempt in range(max_retries + 1):
            response = self.session.request(
                method, url, headers=self.headers(), timeout=30, **kwargs
            )
            if response.status_code == 429 and attempt < max_retries:
                retry_after = response.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else delay
                except (TypeError, ValueError):
                    wait = delay
                time.sleep(wait)
                delay *= 2
                continue
            break
        response.raise_for_status()
        return response.json()

    def get(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        return self._send_with_retry("GET", self._url(path), **kwargs)

    def post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_with_retry("POST", self._url(path), json=payload)

    def put(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_with_retry("PUT", self._url(path), json=payload)

    # ---- Action helpers: get current state ----

    def get_displays(self) -> List[Dict[str, Any]]:
        return self.get("api/devices/displays") or []

    def get_video_sources(self) -> List[Dict[str, Any]]:
        return self.get("api/devices/videoSources") or []

    def get_room_settings(self) -> Dict[str, Any]:
        return self.get("api/room/settings") or {}

    def update_room_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Partial update to room settings (rename displays/speakers/sources, toggle layout capabilities)."""
        return self.post("api/room/settings", payload)

    def get_room(self) -> Dict[str, Any]:
        """Full room config: roomId, externalApps, primaryCameraId, cameras[], visionConsoles[].
        Contains secrets (admin password hash) - do not log/export the raw response."""
        return self.get("api/room") or {}

    def get_room_list(self) -> List[Dict[str, Any]]:
        """List of all rooms on the site: roomId, name, port, externalApiURL. Used to pick a
        target room for source sharing."""
        return self.get("api/room/list") or []

    def get_audio_sources(self) -> List[Dict[str, Any]]:
        return self.get("api/devices/audioSources") or []

    def get_speakers(self) -> List[Dict[str, Any]]:
        return self.get("api/devices/speakers") or []

    def get_camera(self, camera_id: str = "1") -> Dict[str, Any]:
        return self.get(f"api/cameras/{camera_id}") or {}

    def get_camera_status(self, camera_id: str = "1") -> Dict[str, Any]:
        return self.get(f"api/cameras/{camera_id}/status") or {}

    # ---- Action helpers: perform state changes ----

    def route_source(self, source_id: str, destination_id: str, slot: str = "1") -> Dict[str, Any]:
        payload = {
            "command": "network.route",
            "params": {
                "sourceId": source_id,
                "destinationId": destination_id,
                "slotIndex": slot,
            },
        }
        return self.post("api/room/route", payload)

    def unroute_source(self, destination_id: str, slot: str = "1") -> Dict[str, Any]:
        payload = {
            "command": "network.unroute",
            "params": {
                "destinationId": destination_id,
                "slotIndex": slot,
            },
        }
        return self.post("api/room/unroute", payload)

    def change_layout(self, display_id: str, layout: str) -> Dict[str, Any]:
        payload = {
            "deviceId": display_id,
            "command": "devices.capability.ChangeLayout",
            "params": {"layout": layout},
        }
        return self.post(f"api/devices/displays/{display_id}/changeLayout", payload)

    def move_camera(self, camera_id: str, direction: str) -> Dict[str, Any]:
        payload = {"move": direction}
        return self.post(f"api/cameras/{camera_id}/move", payload)

    def call_camera_preset(self, camera_id: str, preset_id: int) -> Dict[str, Any]:
        payload = {"presetIndex": preset_id}
        return self.post(f"api/cameras/{camera_id}/presets/call", payload)

    def get_speaker(self, speaker_id: str) -> Dict[str, Any]:
        return self.get(f"api/devices/speakers/{speaker_id}") or {}

    def mute_speaker(self, speaker_id: str, mute: bool = True) -> Dict[str, Any]:
        payload = {
            "deviceId": speaker_id,
            "command": "devices.capability.Mute",
            "params": {"mute": mute},
        }
        return self.post(f"api/devices/speakers/{speaker_id}/mute", payload)

    def change_speaker_volume(self, speaker_id: str, volume: int) -> Dict[str, Any]:
        payload = {
            "deviceId": speaker_id,
            "command": "devices.capability.ChangeVolume",
            "params": {"volume": volume},
        }
        return self.post(f"api/devices/speakers/{speaker_id}/changeVolume", payload)

    def share_source(
        self,
        source_id: str,
        source_room: str,
        requesting_room: str,
        status: str = "grant",
        expires: str = "indefinite",
    ) -> Dict[str, Any]:
        """Grant or revoke sharing of a video/audio source with another room.

        Confirmed via passive capture (POST /api/room/share, network.Share command).
        `expires` is only sent for grants - the confirmed revoke payload omits it.
        """
        params: Dict[str, Any] = {
            "sourceId": source_id,
            "sourceRoom": source_room,
            "requestingRoom": requesting_room,
            "status": status,
        }
        if status == "grant":
            params["expires"] = expires
        payload = {"command": "network.Share", "params": params}
        return self.post("api/room/share", payload)

    def test_camera_connection(
        self, camera_id: str, endpoint: str, username: str, password: str
    ) -> Dict[str, Any]:
        """Test connectivity to the room camera at the given endpoint/credentials.
        Confirmed payload shape via passive capture (POST /api/cameras/{id}/testConnection)."""
        payload = {"endpoint": endpoint, "username": username, "password": password}
        return self.post(f"api/cameras/{camera_id}/testConnection", payload)

    def call_room_preset(self, preset_index: str) -> Dict[str, Any]:
        payload = {
            "command": "rooms.preset.call",
            "params": {"presetIndex": preset_index},
        }
        return self.post("api/room/presets/call", payload)

    def save_room_preset(self, preset_index: str, name: str) -> Dict[str, Any]:
        """Save the room's current live routing/layout state as a preset at `preset_index`.

        Confirmed via passive capture of the Presets page's "Save" flow
        (POST /api/room/presets, rooms.preset.add command). If a preset already exists
        at that index, this OVERWRITES its routing/layout with whatever is currently live,
        keyed by the given name. This is the real "update this preset to current state" action
        - not safe to fire with arbitrary/unknown live state for automated regression testing.
        """
        payload = {
            "command": "rooms.preset.add",
            "params": {"presetIndex": preset_index, "name": name},
        }
        return self.post("api/room/presets", payload)

    def rename_room_preset(self, preset_index: str, name: str) -> Dict[str, Any]:
        """Rename a preset without touching its saved routing/layout state.

        Confirmed via passive capture: same command/payload shape as `save_room_preset`
        (rooms.preset.add), but sent as PUT instead of POST - the device routes PUT to a
        metadata-only rename (response "Preset renamed to X") instead of overwriting the
        preset's routing with live state (response "New Preset added.").
        """
        payload = {
            "command": "rooms.preset.add",
            "params": {"presetIndex": preset_index, "name": name},
        }
        return self.put("api/room/presets", payload)

    def close(self) -> None:
        self.session.close()
