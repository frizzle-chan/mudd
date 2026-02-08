"""Observer implementations for the MVC models.

This package provides observer classes that react to model events
and reconcile external state (e.g., Discord threads, game effects).
"""

from __future__ import annotations

from collections.abc import Iterable

import asyncpg
import discord

from mudd.events.observer import Observer
from mudd.observers.cache import CacheInvalidationObserver
from mudd.observers.discord import DiscordReconciler, RoomChannelCache
from mudd.observers.effects import EffectsObserver
from mudd.observers.skills import SkillsObserver

__all__ = [
    "CacheInvalidationObserver",
    "DiscordReconciler",
    "EffectsObserver",
    "RoomChannelCache",
    "SkillsObserver",
    "build_observers",
    "flush_all",
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
    """Flush observers with SkillsObserver -> DiscordReconciler event forwarding.

    Ensures flush ordering:
    1. SkillsObserver flushes first (writes XP to database)
    2. XP/level-up events are forwarded to DiscordReconciler
    3. All remaining observers flush (DiscordReconciler processes skills events)
    """
    skills: SkillsObserver | None = None
    reconciler: DiscordReconciler | None = None
    for obs in observers:
        if isinstance(obs, SkillsObserver):
            skills = obs
        elif isinstance(obs, DiscordReconciler):
            reconciler = obs

    # Phase 1: Flush SkillsObserver (writes XP to DB, stores results)
    if skills is not None:
        await skills.flush()
        if reconciler is not None:
            for event in skills.get_xp_events():
                reconciler.notify(event)
            for event in skills.get_level_up_events():
                reconciler.notify(event)

    # Phase 2: Flush all other observers
    for obs in observers:
        if obs is not skills:
            await obs.flush()
