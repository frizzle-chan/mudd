"""Room model with database access methods."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import asyncpg

from mudd.events import RoomSyncedEvent
from mudd.models.entity import ResolvedEntity

if TYPE_CHECKING:
    from mudd.events import Observer
    from mudd.loaders.zone_loader import Room as RoomData
    from mudd.models.entity import EntityInstance
    from mudd.models.interfaces import IEntityInstance, IUser
    from mudd.models.zone import SyncStats

logger = logging.getLogger(__name__)


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
    # Fields below have defaults
    has_voice: bool = field(default=False)
    is_default: bool = field(default=False)
    _observers: tuple[Observer, ...] = field(default=(), repr=False, compare=False)

    def with_observers(self, *observers: Observer) -> Room:
        """Return a new Room with additional observers attached."""
        return Room(
            id=self.id,
            name=self.name,
            description=self.description,
            zone_id=self.zone_id,
            has_voice=self.has_voice,
            is_default=self.is_default,
            _pool=self._pool,
            _observers=self._observers + observers,
        )

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
            rarity="none",
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

    @property
    def current_container(self) -> EntityInstance | None:
        """The container entity if this is a container context, else None.

        Regular rooms are not containers, so this always returns None.
        """
        return None

    async def get_drop_target(self) -> Room:
        """Return the room where dropped items should land."""
        return self

    def allows_pickup(self, entity: IEntityInstance) -> bool:
        """Check if picking up the given entity is allowed."""
        return True

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

    @classmethod
    async def sync_all(
        cls,
        pool: asyncpg.Pool,
        room_data: list[RoomData],
        default_room: str,
        observers: tuple[Observer, ...] = (),
    ) -> SyncStats:
        """Bulk sync rooms to database. Emits RoomSyncedEvent for each room.

        Args:
            pool: Database connection pool
            room_data: List of room data from rec files
            default_room: Default room to relocate users to when their room is deleted
            observers: Observers to notify of sync events

        Returns:
            SyncStats with counts of synced/deleted rooms and relocated users
        """
        from mudd.models.zone import SyncStats

        room_ids = {r.id for r in room_data}
        deleted = 0
        users_relocated = 0

        # Validate default_room exists in provided rooms
        if default_room not in room_ids:
            raise ValueError(
                f"Default room '{default_room}' not found in rooms. "
                f"Available rooms: {sorted(room_ids)}"
            )

        async with pool.acquire() as conn, conn.transaction():
            # Move users from deleted rooms to default room
            deleted_rooms_result = await conn.fetch(
                "SELECT id FROM rooms WHERE id != ALL($1::text[])",
                list(room_ids),
            )
            deleted_room_ids = [r["id"] for r in deleted_rooms_result]

            if deleted_room_ids:
                update_sql = (
                    "UPDATE users SET current_room = $1 "
                    "WHERE current_room = ANY($2::text[])"
                )
                result = await conn.execute(update_sql, default_room, deleted_room_ids)
                # Parse "UPDATE N" to get count
                if result.startswith("UPDATE "):
                    users_relocated = int(result.split()[1])
                    if users_relocated > 0:
                        logger.info(
                            f"Relocated {users_relocated} users from deleted rooms"
                        )

            # Delete rooms not in data (after user relocation)
            result = await conn.execute(
                "DELETE FROM rooms WHERE id != ALL($1::text[])",
                list(room_ids),
            )
            if result.startswith("DELETE "):
                deleted = int(result.split()[1])

            # Upsert rooms
            for room in room_data:
                await conn.execute(
                    """INSERT INTO rooms
                           (id, name, description, zone_id, has_voice, is_default)
                       VALUES ($1, $2, $3, $4, $5, $6)
                       ON CONFLICT (id) DO UPDATE SET
                           name = $2, description = $3, zone_id = $4, has_voice = $5,
                           is_default = $6""",
                    room.id,
                    room.name,
                    room.description,
                    room.zone_id,
                    room.has_voice,
                    room.is_default,
                )

        # Emit events after transaction commits
        for room in room_data:
            event = RoomSyncedEvent(
                room_id=room.id,
                name=room.name,
                description=room.description,
                zone_id=room.zone_id,
                has_voice=room.has_voice,
            )
            for observer in observers:
                observer.notify(event)

        logger.info(
            f"Synced {len(room_data)} rooms, deleted {deleted}, "
            f"relocated {users_relocated} users"
        )
        return SyncStats(
            synced=len(room_data), deleted=deleted, users_relocated=users_relocated
        )


@dataclass(frozen=True)
class EntityModal:
    """Context for interacting with a focused container."""

    id: str
    zone_id: str
    entity_instance: EntityInstance
    _pool: asyncpg.Pool = field(repr=False, compare=False)
    is_container: bool = False

    @property
    def current_container(self) -> EntityInstance | None:
        """The container entity if this is a container context, else None."""
        return self.entity_instance if self.is_container else None

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

    async def get_drop_target(self) -> EntityModal:
        """Return the room where dropped items should land."""
        return self

    def allows_pickup(self, entity: IEntityInstance) -> bool:
        """Check if picking up the given entity is allowed."""
        return True


@dataclass(frozen=True)
class InventoryThread:
    """Context for interacting within an inventory thread.

    Unlike EntityModal (for focus/container context), InventoryThread
    represents a Discord thread view of a single inventory item.
    """

    id: str  # Discord thread ID (not a room ID)
    entity_instance: EntityInstance
    owner: IUser  # User who owns this inventory
    _pool: asyncpg.Pool = field(repr=False, compare=False)

    @property
    def zone_id(self) -> str:
        return "Inventory"

    @property
    def current_container(self) -> EntityInstance | None:
        return None  # Inventory items are not containers

    async def get_entities(self) -> list[EntityInstance]:
        return [self.entity_instance]

    async def get_visible_entities(self) -> list[EntityInstance]:
        return [self.entity_instance]

    async def get_drop_target(self) -> Room | None:
        """Return the user's actual room for drops from inventory."""
        return await Room.get(self._pool, self.owner.current_room)

    def allows_pickup(self, entity: IEntityInstance) -> bool:
        """Disallow picking up the thread's own entity."""
        return entity.instance_id != self.entity_instance.instance_id
