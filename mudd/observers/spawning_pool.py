"""SpawningPool observer for resetting respawn timers."""

from __future__ import annotations

import asyncpg

from mudd.events.types import EntityDestroyedEvent, EntityPickedUpEvent, GameEvent
from mudd.models.spawning_pool import SpawningPool


class SpawningPoolObserver:
    """Resets spawning pool timers when spawned entities are removed.

    When a spawned entity is picked up or destroyed, the pool's
    last_spawn_at is reset so the full respawn interval elapses
    before a replacement spawns.
    """

    flush_priority: int = 15

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._pool_ids: set[str] = set()

    def notify(self, event: GameEvent) -> None:
        match event:
            case EntityPickedUpEvent(spawning_pool_id=pool_id) if pool_id:
                self._pool_ids.add(pool_id)
            case EntityDestroyedEvent(spawning_pool_id=pool_id) if pool_id:
                self._pool_ids.add(pool_id)

    async def flush(self) -> list[GameEvent]:
        pool_ids = self._pool_ids
        self._pool_ids = set()
        for pool_id in pool_ids:
            await SpawningPool.reset_timer(self._pool, pool_id)
        return []

    async def post_flush(self) -> None:
        pass
