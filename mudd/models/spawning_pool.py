"""SpawningPool model for entity respawns."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import asyncpg

from mudd.models.zone import SyncStats

if TYPE_CHECKING:
    from mudd.loaders.zone_loader import SpawningPoolData

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
