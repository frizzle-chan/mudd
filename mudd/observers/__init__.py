"""Observer implementations for the MVC models.

This package provides observer classes that react to model events
and reconcile external state (e.g., Discord threads, game effects).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

import asyncpg
import discord

from mudd.events.observer import Observer
from mudd.events.types import GameEvent
from mudd.observers.cache import CacheInvalidationObserver
from mudd.observers.discord import DiscordReconciler, RoomChannelCache
from mudd.observers.effects import EffectsObserver
from mudd.observers.skills import SkillsObserver

logger = logging.getLogger(__name__)

__all__ = [
    "CacheInvalidationObserver",
    "DiscordReconciler",
    "EffectsObserver",
    "RoomChannelCache",
    "SkillsObserver",
    "build_observers",
    "flush_all",
    "post_flush_all",
]


def build_observers(
    pool: asyncpg.Pool,
    user_id: int,
    room_id: str,
    *,
    bot: discord.Client | None = None,
    room_cache: RoomChannelCache | None = None,
) -> list[Observer]:
    """Build the standard observer set for interactive commands.

    Centralizes observer construction so new observers only need
    to be added here. Callers may append additional observers
    (EffectsObserver, cache invalidators) to the returned list.
    """
    observers: list[Observer] = []

    observers.append(
        SkillsObserver(
            _pool=pool,
            _user_id=user_id,
            _room_id=room_id,
        )
    )

    if bot is not None:
        observers.append(DiscordReconciler(bot, pool, room_cache=room_cache))

    return observers


async def flush_all(observers: Iterable[Observer]) -> None:
    """Sort observers by priority, flush each, and re-broadcast returned events.

    Higher flush_priority values flush first. Events returned by flush()
    are re-broadcast to all observers via notify() after all flushes complete.

    Args:
        observers: Observers to flush
    """
    sorted_obs = sorted(
        observers,
        key=lambda o: getattr(o, "flush_priority", 0),
        reverse=True,
    )
    new_events: list[GameEvent] = []
    for obs in sorted_obs:
        new_events.extend(await obs.flush())

    if new_events:
        logger.info("flush_all re-broadcasting %d events", len(new_events))
    for event in new_events:
        for obs in sorted_obs:
            obs.notify(event)


async def post_flush_all(observers: Iterable[Observer]) -> None:
    """Call post_flush() on all observers.

    Called after flush_all() and any caller-inserted messages (e.g.
    movement announcements) so that deferred work like level-up
    announcements appears last.

    Args:
        observers: Observers to post-flush
    """
    for obs in observers:
        await obs.post_flush()
