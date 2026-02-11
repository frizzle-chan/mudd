"""Discord utility functions."""

from __future__ import annotations

import re


def normalize_channel_name(username: str, suffix: str) -> str:
    """Build a Discord channel name that matches Discord's normalization.

    Discord channel names only allow [a-z0-9-_], stripping all other characters.
    """
    normalized = username.lower().replace(" ", "-")
    normalized = re.sub(r"[^a-z0-9\-_]", "", normalized)
    return f"{normalized}-{suffix}"
