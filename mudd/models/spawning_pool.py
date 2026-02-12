"""SpawningPool model for entity respawns."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

import asyncpg

from mudd.models.zone import SyncStats

if TYPE_CHECKING:
    from mudd.loaders.zone_loader import SpawningPoolData
    from mudd.models.entity import EntityInstance

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpawningPool:
    """Spawning pool for entity respawns.

    Spawning pools define locations where entities can respawn
    based on tag queries and configurable intervals.
    """

    id: str
    room: str
    container_id: str | None
    tag_query: str
    max_count: int
    respawn_interval_minutes: int
    no_duplicates: bool

    # Runtime state (from query, not rec file)
    last_spawn_at: datetime | None = None
    current_count: int = 0
    spawned_entity_ids: tuple[str, ...] = ()
    _pool: asyncpg.Pool | None = field(repr=False, compare=False, default=None)

    @classmethod
    async def get_all_with_counts(cls, pool: asyncpg.Pool) -> list[SpawningPool]:
        """Fetch all spawning pools with current instance counts."""
        rows = await pool.fetch(
            """
            SELECT
                sp.id, sp.room, sp.container_id, sp.tag_query,
                sp.max_count, sp.respawn_interval_minutes, sp.no_duplicates,
                sp.last_spawn_at,
                COUNT(ei.id) AS current_count,
                ARRAY_REMOVE(ARRAY_AGG(ei.entity_id), NULL) AS spawned_entity_ids
            FROM spawning_pools sp
            LEFT JOIN entity_instances ei ON ei.spawning_pool_id = sp.id
            GROUP BY sp.id
            """
        )
        return [
            cls(
                id=r["id"],
                room=r["room"],
                container_id=r["container_id"],
                tag_query=r["tag_query"],
                max_count=r["max_count"],
                respawn_interval_minutes=r["respawn_interval_minutes"],
                no_duplicates=r["no_duplicates"],
                last_spawn_at=r["last_spawn_at"],
                current_count=r["current_count"],
                spawned_entity_ids=tuple(r["spawned_entity_ids"] or []),
                _pool=pool,
            )
            for r in rows
        ]

    def can_spawn(self, now: datetime) -> bool:
        """Check if pool can spawn (capacity and interval)."""
        if self.current_count >= self.max_count:
            return False
        if self.last_spawn_at is not None:
            elapsed = (now - self.last_spawn_at).total_seconds() / 60
            if elapsed < self.respawn_interval_minutes:
                return False
        return True

    async def try_spawn(self, now: datetime) -> EntityInstance | None:
        """Attempt to spawn an entity. Returns instance or None."""
        from mudd.models.entity import EntityInstance, ResolvedEntity

        if self._pool is None:
            return None

        if not self.can_spawn(now):
            return None

        # Select entity using ResolvedEntity classmethod
        exclude_ids = set(self.spawned_entity_ids) if self.no_duplicates else None
        entity = await ResolvedEntity.get_weighted_random_by_tag(
            self._pool, self.tag_query, exclude_ids
        )
        if entity is None:
            return None

        # Create instance via EntityInstance.create()
        instance = await EntityInstance.create(
            self._pool,
            entity.id,
            room_id=self.room,
            container_entity_id=self.container_id,
            spawning_pool_id=self.id,
        )

        if instance is None:
            return None

        # Update last_spawn_at
        await self._pool.execute(
            "UPDATE spawning_pools SET last_spawn_at = $1 WHERE id = $2",
            now,
            self.id,
        )

        return instance

    @classmethod
    async def reset_timer(cls, pool: asyncpg.Pool, pool_id: str) -> None:
        """Reset the respawn timer so the full interval elapses before respawn.

        Called by SpawningPoolObserver when a spawned item is taken or destroyed.
        """
        await pool.execute(
            "UPDATE spawning_pools SET last_spawn_at = NOW() WHERE id = $1",
            pool_id,
        )

    @classmethod
    def _validate_pools(
        cls,
        pools: list[SpawningPoolData],
        room_ids: set[str],
        entity_ids: set[str],
    ) -> None:
        """Validate spawning pool references.

        Args:
            pools: List of SpawningPool data from rec files
            room_ids: Valid room IDs for validation
            entity_ids: Valid entity IDs for container validation

        Raises:
            ValueError: If validation fails
        """
        for pool in pools:
            if pool.room not in room_ids:
                raise ValueError(
                    f"SpawningPool '{pool.id}' references invalid room '{pool.room}'"
                )
            if pool.container_id and pool.container_id not in entity_ids:
                raise ValueError(
                    f"SpawningPool '{pool.id}' references invalid container "
                    f"'{pool.container_id}'"
                )

    @classmethod
    async def sync_all(
        cls,
        pool: asyncpg.Pool,
        pools: list[SpawningPoolData],
        room_ids: set[str],
        entity_ids: set[str],
    ) -> SyncStats:
        """Bulk sync spawning pools. Validates refs and upserts.

        Preserves last_spawn_at timestamps for existing pools.

        Args:
            pool: Database connection pool
            pools: List of SpawningPool data from rec files
            room_ids: Valid room IDs for validation
            entity_ids: Valid entity IDs for container validation

        Returns:
            SyncStats with synced and deleted counts

        Raises:
            ValueError: If validation fails
        """
        deleted = 0

        if not pools:
            async with pool.acquire() as conn:
                result = await conn.execute("DELETE FROM spawning_pools")
                if result.startswith("DELETE "):
                    deleted = int(result.split()[1])
            return SyncStats(synced=0, deleted=deleted)

        # Validate pool references
        cls._validate_pools(pools, room_ids, entity_ids)

        pool_ids = [p.id for p in pools]

        async with pool.acquire() as conn, conn.transaction():
            # Delete pools not in current files
            result = await conn.execute(
                "DELETE FROM spawning_pools WHERE id != ALL($1::text[])",
                pool_ids,
            )
            if result.startswith("DELETE "):
                deleted = int(result.split()[1])

            # Upsert pools (preserve last_spawn_at)
            for sp in pools:
                await conn.execute(
                    """INSERT INTO spawning_pools (
                        id, room, container_id, tag_query, max_count,
                        respawn_interval_minutes, no_duplicates
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (id) DO UPDATE SET
                        room = $2,
                        container_id = $3,
                        tag_query = $4,
                        max_count = $5,
                        respawn_interval_minutes = $6,
                        no_duplicates = $7
                    """,
                    sp.id,
                    sp.room,
                    sp.container_id,
                    sp.tag_query,
                    sp.max_count,
                    sp.respawn_interval_minutes,
                    sp.no_duplicates,
                )

        logger.info(f"Synced {len(pools)} spawning pools")
        return SyncStats(synced=len(pools), deleted=deleted)
