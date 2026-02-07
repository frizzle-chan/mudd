"""Room model with database access methods."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self

import asyncpg

from mudd.events import RoomSyncedEvent
from mudd.models.entity import EntityInstance, ResolvedEntity
from mudd.utils.text import Rarity

if TYPE_CHECKING:
    from mudd.events import Observer
    from mudd.loaders.zone_loader import RoomData
    from mudd.models.interfaces import IReadableEntity, IUser
    from mudd.models.zone import SyncStats

logger = logging.getLogger(__name__)


class _DefaultVisibleEntities:
    """Mixin: get_visible_entities defaults to get_entities."""

    async def get_visible_entities(self) -> list[EntityInstance]:
        return await self.get_entities()  # type: ignore[attr-defined]


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

    def make_entity(self) -> ResolvedEntity:
        on_look = (
            """{{ effects.clear_focus() }}"""
            """{{ e.description_long or "You see nothing special." }}"""
            """{% if e.contents %}\n\nYou see:\n{{ e.contents }}{% endif %}"""
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
            on_fish=on_look,
            contents_visible=True,
            rarity="none",
        )

    async def get_entities(self) -> list[EntityInstance]:
        """Get all entity instances in this room.

        Returns:
            List of EntityInstance objects in the room
        """
        return await EntityInstance.get_by_room(self._pool, self)

    async def get_visible_entities(self) -> list[EntityInstance]:
        """Get visible entities (top-level + visible container contents).

        Returns top-level entities plus contents of containers with
        contents_visible=True.

        Returns:
            List of EntityInstance objects visible in the room
        """
        top_level = await EntityInstance.get_top_level_by_room(self._pool, self)

        result: list[EntityInstance] = []
        for instance in top_level:
            result.append(instance)

            # Add contents of visible containers
            if instance.entity.contents_visible:
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

    def allows_pickup(self, entity: IReadableEntity) -> bool:
        """Check if picking up the given entity is allowed."""
        return True

    @classmethod
    async def get_all_zone_mappings(cls, pool: asyncpg.Pool) -> dict[str, str]:
        """Get a mapping of room IDs to their zone IDs.

        Args:
            pool: Database connection pool

        Returns:
            Dict mapping room ID to zone ID for all rooms
        """
        rows = await pool.fetch("SELECT id, zone_id FROM rooms")
        return {row["id"]: row["zone_id"] for row in rows}

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

    async def get_room_entity(self, user: IUser) -> RoomEntityInstance:
        """Return this room as a virtual entity for autocomplete."""
        focus = await user.get_focus()
        focus_name = focus.current_container.name if focus else None
        return self.as_entity(focus_name=focus_name)

    def as_entity(self, focus_name: str | None = None) -> RoomEntityInstance:
        """Create a virtual entity instance representing this room.

        Args:
            focus_name: If set, prepends "[Close {focus_name}]" to the display name
                       to indicate this will close the current focus.

        Returns:
            RoomEntityInstance that implements IEntityInstance protocol
        """
        room_name = f"📍 {self.name}"
        display_name = f"[Close {focus_name}] {room_name}" if focus_name else room_name
        return RoomEntityInstance(_room=self, _display_name=display_name)


@dataclass(frozen=True)
class RoomEntityInstance:
    """Virtual entity instance representing a room.

    Implements IEntityInstance protocol so rooms can appear in entity
    autocomplete and be targeted by commands like /look.
    """

    _room: Room
    _display_name: str

    @property
    def instance_id(self) -> str:
        """Entity reference in scheme format (room://{room_id})."""
        return f"room://{self._room.id}"

    @property
    def entity(self) -> ResolvedEntity:
        """Resolved entity definition for this room."""
        return self._room.make_entity()

    @property
    def room_id(self) -> str | None:
        """Room ID - returns the room's own ID."""
        return self._room.id

    @property
    def owner_id(self) -> int | None:
        """Owner's Discord ID - rooms are not owned."""
        return None

    # Proxy properties delegating to self.entity for template access
    @property
    def id(self) -> str:
        """Entity definition ID."""
        return self.entity.id

    @property
    def name(self) -> str:
        """Entity name (with optional [Close X] prefix)."""
        return self._display_name

    @property
    def description_short(self) -> str | None:
        """Short description template."""
        return self.entity.description_short

    @property
    def description_long(self) -> str | None:
        """Long description template."""
        return self.entity.description_long

    @property
    def contents_visible(self) -> bool:
        """Whether container contents are visible."""
        return self.entity.contents_visible

    @property
    def rarity(self) -> Rarity:
        """Item rarity tier - rooms have no rarity."""
        return "none"

    # Capability properties - virtual room entities don't support mutations
    @property
    def is_focusable(self) -> bool:
        return False

    @property
    def can_pickup(self) -> bool:
        return False

    @property
    def can_drop(self) -> bool:
        return False

    @property
    def can_destroy(self) -> bool:
        return False

    async def get_contents(self) -> list[EntityInstance]:
        """Get visible entities in the room."""
        return await self._room.get_visible_entities()

    def with_observers(self, *observers: Observer) -> Self:
        """No-op: rooms don't emit events, so observers are ignored."""
        return self


@dataclass(frozen=True)
class EntityModal(_DefaultVisibleEntities):
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

    async def get_drop_target(self) -> EntityModal:
        """Return the room where dropped items should land."""
        return self

    async def get_room_entity(self, user: IUser) -> RoomEntityInstance | None:
        """Return the underlying room as a virtual entity for autocomplete."""
        room = await Room.get(self._pool, user.current_room)
        if not room:
            return None
        focus = await user.get_focus()
        focus_name = focus.current_container.name if focus else None
        return room.as_entity(focus_name=focus_name)

    def allows_pickup(self, entity: IReadableEntity) -> bool:
        """Check if picking up the given entity is allowed."""
        return True


@dataclass(frozen=True)
class InventoryThread(_DefaultVisibleEntities):
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

    async def get_drop_target(self) -> Room | None:
        """Return the user's actual room for drops from inventory."""
        return await Room.get(self._pool, self.owner.current_room)

    async def get_room_entity(self, user: IUser) -> RoomEntityInstance | None:
        """Inventory threads have no room entity for autocomplete."""
        return None

    def allows_pickup(self, entity: IReadableEntity) -> bool:
        """Disallow picking up the thread's own entity."""
        return entity.instance_id != self.entity_instance.instance_id
