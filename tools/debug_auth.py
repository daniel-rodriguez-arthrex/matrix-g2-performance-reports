"""Diagnose the getAccessToken exchange for each configured room.

Calls POST /api/app/getAccessToken directly (bypassing MatrixClient's silent
exception handling) and prints the raw HTTP status + response body, so we can
see exactly why a room's passcode is accepted or rejected.

Usage:
    python tools/debug_auth.py
    python tools/debug_auth.py --rooms OR1 OR2
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

from config import get_room_config
from config.environments import ROOMS


def debug_room(room_id: str) -> None:
    room = get_room_config(room_id)
    pair_key = room.passcode or room.id
    url = f"{room.base_url.rstrip('/')}/api/app/getAccessToken"
    payload = {"pairKey": pair_key, "pairHash": "", "roomUrl": room.base_url}

    print(f"\n=== {room_id} ({room.base_url}) ===")
    print(f"  pairKey sent: {pair_key!r}")
    try:
        resp = requests.post(
            url, json=payload, headers={"Content-Type": "application/json"},
            timeout=15, verify=False,
        )
        print(f"  HTTP {resp.status_code}")
        print(f"  Body: {resp.text[:500]}")
    except requests.exceptions.RequestException as exc:
        print(f"  REQUEST FAILED: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rooms", nargs="+", default=None)
    args = parser.parse_args()

    room_ids = args.rooms or sorted(ROOMS.keys(), key=lambda r: (len(r), r))
    if not room_ids:
        print("No rooms configured. Set MATRIX_ROOMS_JSON in .env.")
        sys.exit(1)

    for rid in room_ids:
        debug_room(rid)


if __name__ == "__main__":
    main()
