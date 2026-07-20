"""Shared helpers for workflow modules."""

from typing import Optional


def label(name: Optional[str], device_id: str) -> str:
    """Format a human-readable label combining a device's display name and its stable id.

    Names are shown for readability but the id is always kept for exact correlation/debugging,
    since names can be changed at runtime (e.g. via the settings/rename workflow).
    """
    if name:
        return f"{name} ({device_id})"
    return device_id
