"""Room model with database access methods."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import asyncpg

from mudd.models import IRoom, ResolvedEntity

if TYPE_CHECKING:
    from mudd.models.entity import EntityInstance


@dataclass(frozen=True)
class Room:
    """Room model with database access methods.

    Rooms are immutable and represent a location in the game world.
    """

    id: str
    name: str
    description: str
    zone_id: str
    _pool: asyncpg.Pool = field(repr=False, compare=False)

    @classmethod
    async def get(cls, pool: asyncpg.Pool, room_id: str) -> Room | None:
        """Get room by ID.

        Args:
            pool: Database connection pool
            room_id: Room identifier

        Returns:
            Room model instance, or None if not found
        """
        row = await pool.fetchrow(
            "SELECT id, name, description, zone_id FROM rooms WHERE id = $1",
            room_id,
        )

        if row is None:
            return None

        return cls(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            zone_id=row["zone_id"],
            _pool=pool,
        )

    @classmethod
    async def get_default(cls, pool: asyncpg.Pool) -> Room | None:
        """Get the default spawn room.

        Args:
            pool: Database connection pool

        Returns:
            Room model instance, or None if no default is configured
        """
        row = await pool.fetchrow(
            "SELECT id, name, description, zone_id FROM rooms WHERE is_default = TRUE",
        )

        if row is None:
            return None

        return cls(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            zone_id=row["zone_id"],
            _pool=pool,
        )

    def make_entity(self, visible: list[EntityInstance]) -> ResolvedEntity:
        on_look = (
            """{{ e.description_long or "You see nothing special." }}"""
            """{{ contents }}"""
        )
        return ResolvedEntity(
            f"room::{self.id}",
            name=self.name,
            description_short=self.description,
            description_long=self.description,
            on_look=on_look,
            on_touch=on_look,
            on_attack=on_look,
            on_use=on_look,
            on_take=on_look,
            on_open=on_look,
            on_close=on_look,
            on_drop=on_look,
            contents_visible=True,
            focus_mode="none",
            rarity="none"
        )

    async def get_entities(self) -> list[EntityInstance]:
        """Get all entity instances in this room.

        Returns:
            List of EntityInstance objects in the room
        """
        from mudd.models.entity import EntityInstance

        return await EntityInstance.get_by_room(self._pool, self)

    async def get_visible_entities(self) -> list[EntityInstance]:
        """Get visible entities (top-level + visible container contents).

        Returns top-level entities plus contents of containers with
        contents_visible=True.

        Returns:
            List of EntityInstance objects visible in the room
        """
        from mudd.models.entity import EntityInstance, ResolvedEntity

        # Get top-level entities (no container)
        rows = await self._pool.fetch(
            """
            SELECT ei.id AS instance_id, ei.room, ei.owner_id,
                   ei.container_entity_id, r.*
            FROM entity_instances ei
            CROSS JOIN LATERAL resolve_entity(ei.entity_id) r
            WHERE ei.room = $1 AND ei.container_entity_id IS NULL
            """,
            self.id,
        )

        result: list[EntityInstance] = []
        for row in rows:
            entity = ResolvedEntity._from_row(row)
            instance = EntityInstance._from_row(row, entity, self._pool)
            result.append(instance)

            # Add contents of visible containers
            if entity.contents_visible:
                contents = await instance.get_contents()
                result.extend(contents)

        return result

    async def get_exits(self) -> list[dict[str, str]]:
        """Get available exits from this room.

        Note: This queries the room_exits table which may not exist
        in all deployments. Returns empty list if table doesn't exist.

        Returns:
            List of dicts with 'direction' and 'destination' keys
        """
        try:
            rows = await self._pool.fetch(
                """
                SELECT direction, destination_room_id AS destination
                FROM room_exits
                WHERE source_room_id = $1
                """,
                self.id,
            )
            return [
                {"direction": row["direction"], "destination": row["destination"]}
                for row in rows
            ]
        except asyncpg.UndefinedTableError:
            return []

@dataclass(frozen=True)
class EntityModal:
    """
    Rooms are immutable and represent a location in the game world.
    """

    id: str
    zone_id: str
    entity_instance: EntityInstance
    _pool: asyncpg.Pool = field(repr=False, compare=False)
    allow_close: bool = True

    async def get_entities(self) -> list[EntityInstance]:
        """Get all entity instances in this room.

        Returns:
            List of EntityInstance objects in the room
        """
        return [self.entity_instance, *await self.entity_instance.get_contents()]

    async def get_visible_entities(self) -> list[EntityInstance]:
        """Get visible entities (top-level + visible container contents).

        Returns top-level entities plus contents of containers with
        contents_visible=True.

        Returns:
            List of EntityInstance objects visible in the room
        """
        return await self.get_entities()
