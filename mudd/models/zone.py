"""Zone model with database access methods."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import asyncpg

if TYPE_CHECKING:
    from mudd.events import Observer
    from mudd.loaders.zone_loader import ZoneData

from mudd.events import ZoneSyncedEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SyncStats:
    """Statistics from a sync operation."""

    synced: int = 0
    deleted: int = 0
    users_relocated: int = 0


@dataclass(frozen=True)
class Zone:
    """Zone model with database access methods.

    Zones are immutable and represent a category of rooms in the game world.
    """

    id: str
    name: str
    description: str | None
    _pool: asyncpg.Pool = field(repr=False, compare=False)

    @classmethod
    async def sync_all(
        cls,
        pool: asyncpg.Pool,
        zone_data: list[ZoneData],
        observers: tuple[Observer, ...] = (),
    ) -> SyncStats:
        """Bulk sync zones to database. Emits ZoneSyncedEvent for each zone.

        Args:
            pool: Database connection pool
            zone_data: List of zone data from rec files
            observers: Observers to notify of sync events

        Returns:
            SyncStats with counts of synced and deleted zones
        """
        stats = SyncStats()
        zone_ids = {z.id for z in zone_data}

        async with pool.acquire() as conn, conn.transaction():
            # Delete zones not in data
            result = await conn.execute(
                "DELETE FROM zones WHERE id != ALL($1::text[])",
                list(zone_ids),
            )
            if result.startswith("DELETE "):
                stats = SyncStats(
                    synced=stats.synced,
                    deleted=int(result.split()[1]),
                    users_relocated=stats.users_relocated,
                )

            # Upsert zones
            for zone in zone_data:
                await conn.execute(
                    """INSERT INTO zones (id, name, description)
                       VALUES ($1, $2, $3)
                       ON CONFLICT (id) DO UPDATE SET name = $2, description = $3""",
                    zone.id,
                    zone.name,
                    zone.description,
                )

            stats = SyncStats(
                synced=len(zone_data),
                deleted=stats.deleted,
                users_relocated=stats.users_relocated,
            )

        # Emit events after transaction commits
        for zone in zone_data:
            event = ZoneSyncedEvent(zone_id=zone.id, name=zone.name)
            for observer in observers:
                observer.notify(event)

        logger.info(f"Synced {stats.synced} zones, deleted {stats.deleted}")
        return stats
