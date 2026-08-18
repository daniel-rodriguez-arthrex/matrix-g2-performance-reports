"""List displays, speakers, and internal (non-external) video sources for each
configured operating room.

Usage:
    python tools/list_devices.py
    python tools/list_devices.py --rooms OR1 OR2 OR3
    python tools/list_devices.py --json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_room_config
from config.environments import ROOMS
from core.matrix_client import MatrixClient


def collect_room_devices(room_id: str) -> dict:
    room = get_room_config(room_id)
    client = MatrixClient(
        room.base_url, room.username, room.password, room.id, passcode=room.passcode
    )
    result = {"room_id": room_id, "base_url": room.base_url, "error": None,
               "displays": [], "speakers": [], "video_sources": []}
    try:
        client.authenticate()

        for d in client.get_displays() or []:
            attrs = d.get("attributes", {})
            result["displays"].append({"id": d.get("id"), "name": attrs.get("name", "")})

        for s in client.get_speakers() or []:
            attrs = s.get("attributes", {})
            result["speakers"].append({"id": s.get("id"), "name": attrs.get("name", "")})

        for v in client.get_video_sources() or []:
            attrs = v.get("attributes", {})
            if attrs.get("external"):
                continue
            result["video_sources"].append({"id": v.get("id"), "name": attrs.get("name", "")})
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        client.close()
    return result


def print_report(rooms_data: list) -> None:
    for data in rooms_data:
        print(f"\n=== {data['room_id']} ({data['base_url']}) ===")
        if data["error"]:
            print(f"  ERROR: {data['error']}")
            continue

        print("  Displays:")
        if data["displays"]:
            for d in data["displays"]:
                print(f"    - {d['name']}  [{d['id']}]")
        else:
            print("    (none)")

        print("  Speakers:")
        if data["speakers"]:
            for s in data["speakers"]:
                print(f"    - {s['name']}  [{s['id']}]")
        else:
            print("    (none)")

        print("  Video Sources (internal only):")
        if data["video_sources"]:
            for v in data["video_sources"]:
                print(f"    - {v['name']}  [{v['id']}]")
        else:
            print("    (none)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rooms", nargs="+", default=None,
        help="Room IDs to query (default: all rooms in MATRIX_ROOMS_JSON)",
    )
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of a formatted report")
    args = parser.parse_args()

    room_ids = args.rooms or sorted(ROOMS.keys(), key=lambda r: (len(r), r))
    if not room_ids:
        print("No rooms configured. Set MATRIX_ROOMS_JSON in .env.")
        sys.exit(1)

    rooms_data = [collect_room_devices(rid) for rid in room_ids]

    if args.json:
        print(json.dumps(rooms_data, indent=2))
    else:
        print_report(rooms_data)


if __name__ == "__main__":
    main()
