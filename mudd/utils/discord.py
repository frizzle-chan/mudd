"""Discord utility functions."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

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


async def fetch_forum(
    guild: discord.Guild, forum_id: int
) -> discord.ForumChannel | None:
    """Resolve a forum by ID, falling back to an API call if not cached.

    Returns ``None`` when Discord confirms the channel is gone (404), or when
    the ID resolves to something that is not a forum. Every other error
    propagates: callers read ``None`` as "confirmed deleted" and act
    destructively on it, so treating a transient failure or a ``Forbidden``
    as a deletion would clear a healthy DB row and drop the user into
    duplicate recovery.

    Note that ``guild.fetch_channel`` can also raise ``discord.InvalidData``
    (a ``ClientException``, not an ``HTTPException``). That escapes the
    caller's ``HTTPException`` handler into the widened outer
    ``except Exception`` in ``_ensure_user_inventory_locked``, which is the
    safe outcome — the user is skipped for the pass and the DB row is
    untouched.
    """
    channel = guild.get_channel(forum_id)
    if isinstance(channel, discord.ForumChannel):
        return channel
    try:
        fetched = await guild.fetch_channel(forum_id)
    except discord.NotFound:
        return None
    if isinstance(fetched, discord.ForumChannel):
        return fetched
    logger.warning(
        "Expected forum for ID %d but got %s", forum_id, type(fetched).__name__
    )
    return None


def is_older_than(snowflake_id: int, now: datetime, delta: timedelta) -> bool:
    """Whether a Discord snowflake was created more than ``delta`` before ``now``."""
    return discord.utils.snowflake_time(snowflake_id) < now - delta


def normalize_channel_name(username: str, suffix: str) -> str:
    """Build a Discord channel name that matches Discord's normalization.

    Discord channel names only allow [a-z0-9-_], stripping all other characters.
    """
    normalized = username.lower().replace(" ", "-")
    normalized = re.sub(r"[^a-z0-9\-_]", "", normalized)
    return f"{normalized}-{suffix}"
