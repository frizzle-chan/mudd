"""Observer implementations for the MVC models.

This package provides observer classes that react to model events
and reconcile external state (e.g., Discord threads, game effects).
"""

from __future__ import annotations

import asyncpg
import discord

from mudd.events.observer import Observer
from mudd.observers.cache import CacheInvalidationObserver
from mudd.observers.discord import DiscordReconciler, RoomChannelCache
from mudd.observers.effects import EffectsObserver
from mudd.observers.skills import SkillsObserver
from mudd.observers.skills_reconciler import SkillsReconciler

__all__ = [
    "CacheInvalidationObserver",
    "DiscordReconciler",
    "EffectsObserver",
    "RoomChannelCache",
    "SkillsObserver",
    "SkillsReconciler",
    "build_observers",
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

    if bot is not None:
        observers.append(DiscordReconciler(bot, pool, room_cache=room_cache))
        skills_reconciler: SkillsReconciler | None = SkillsReconciler(bot, pool)
    else:
        skills_reconciler = None

    observers.append(
        SkillsObserver(
            _pool=pool,
            _user_id=user_id,
            _room_id=room_id,
            _reconciler=skills_reconciler,
        )
    )

    return observers
