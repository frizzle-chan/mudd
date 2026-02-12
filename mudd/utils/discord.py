"""Discord utility functions."""

from __future__ import annotations

import logging
import re

import discord

logger = logging.getLogger(__name__)


async def fetch_thread(guild: discord.Guild, thread_id: int) -> discord.Thread | None:
    """Resolve a thread by ID, falling back to an API call if not cached."""
    thread = guild.get_thread(thread_id)
    if thread is not None:
        return thread
    try:
        channel = await guild.fetch_channel(thread_id)
    except discord.NotFound:
        return None
    if isinstance(channel, discord.Thread):
        return channel
    logger.warning(
        "Expected thread for ID %d but got %s", thread_id, type(channel).__name__
    )
    return None


def normalize_channel_name(username: str, suffix: str) -> str:
    """Build a Discord channel name that matches Discord's normalization.

    Discord channel names only allow [a-z0-9-_], stripping all other characters.
    """
    normalized = username.lower().replace(" ", "-")
    normalized = re.sub(r"[^a-z0-9\-_]", "", normalized)
    return f"{normalized}-{suffix}"
