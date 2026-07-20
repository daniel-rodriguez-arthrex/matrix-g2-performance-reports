import json
import os
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class RoomConfig:
    id: str
    base_url: str
    username: str
    password: str
    passcode: Optional[str] = None
    is_default: bool = False

    def login_url(self) -> str:
        return f"{self.base_url}/app"


def _load_rooms_from_env() -> Dict[str, RoomConfig]:
    """Build the room registry from environment variables only.

    Credentials and internal IPs are NEVER hardcoded in source. Provide them via a
    gitignored .env file (see .env.example). Two formats are supported:

    1. MATRIX_ROOMS_JSON - a JSON object of {room_id: {base_url, username, password, passcode}}
       for multi-room setups.
    2. MATRIX_BASE_URL / MATRIX_USERNAME / MATRIX_PASSWORD / MATRIX_PASSCODE / ROOM_ID
       for a single room.
    """
    rooms: Dict[str, RoomConfig] = {}

    raw = os.getenv("MATRIX_ROOMS_JSON")
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"MATRIX_ROOMS_JSON is not valid JSON: {exc}") from exc
        for rid, cfg in parsed.items():
            rooms[rid] = RoomConfig(
                id=rid,
                base_url=cfg["base_url"],
                username=cfg.get("username", "admin"),
                password=cfg["password"],
                passcode=cfg.get("passcode"),
            )

    # Single-room fallback / override from discrete env vars.
    single_base = os.getenv("MATRIX_BASE_URL")
    if single_base:
        rid = os.getenv("ROOM_ID", "OR1")
        rooms.setdefault(
            rid,
            RoomConfig(
                id=rid,
                base_url=single_base,
                username=os.getenv("MATRIX_USERNAME", "admin"),
                password=os.getenv("MATRIX_PASSWORD", "password"),
                passcode=os.getenv("MATRIX_PASSCODE"),
            ),
        )
    return rooms


ROOMS = _load_rooms_from_env()


def get_room_config(room_id: Optional[str] = None) -> RoomConfig:
    room_id = room_id or os.getenv("ROOM_ID", "OR1")
    rooms = ROOMS or _load_rooms_from_env()
    if room_id in rooms:
        return rooms[room_id]
    if not rooms:
        raise ValueError(
            "No room configuration found. Copy .env.example to .env and set "
            "MATRIX_ROOMS_JSON (or MATRIX_BASE_URL/USERNAME/PASSWORD) before running."
        )
    raise ValueError(f"Unknown room '{room_id}'. Available: {list(rooms.keys())}")


def get_environment() -> dict:
    return {
        "base_url": os.getenv("MATRIX_BASE_URL", ""),
        "username": os.getenv("MATRIX_USERNAME", "admin"),
        "password": os.getenv("MATRIX_PASSWORD", ""),
        "room_id": os.getenv("ROOM_ID", "OR1"),
        "headless": os.getenv("HEADLESS", "true").lower() == "true",
        "output_dir": os.getenv("OUTPUT_DIR", "results"),
    }
