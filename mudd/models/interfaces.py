"""Protocol definitions for model interfaces."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from mudd.utils.text import Rarity

if TYPE_CHECKING:
    from mudd.events import Observer
    from mudd.models.entity import EntityInstance, ResolvedEntity
    from mudd.models.room import Room, RoomEntityInstance
    from mudd.models.user import FocusContext


class IUser(Protocol):
    """Protocol for User model."""

    @property
    def id(self) -> int:
        """Discord user snowflake ID."""
        ...

    @property
    def current_room(self) -> str:
        """Current room ID."""
        ...

    @property
    def mention(self) -> str:
        """Discord mention string for this user."""
        ...

    async def get_room(self) -> Room:
        """Get the user's current room."""
        ...

    async def get_inventory(self) -> list[EntityInstance]:
        """Get all entities in the user's inventory."""
        ...

    async def get_focus(self) -> FocusContext | None:
        """Get the user's current focus context, if any."""
        ...

    async def get_balance(self) -> int:
        """Get the user's currency balance."""
        ...


class IRoom(Protocol):
    """Protocol for Room model."""

    @property
    def id(self) -> str:
        """Room identifier."""
        ...

    async def get_drop_target(self) -> IRoom | None:
        """Return the room where dropped items should land.

        Most rooms return self. InventoryThread returns the user's actual room
        since items dropped from inventory should appear in the physical room.
        """
        ...

    def allows_pickup(self, entity: IEntityInstance) -> bool:
        """Check if picking up the given entity is allowed in this room context.

        Most rooms allow all pickups. InventoryThread disallows picking up
        the thread's own entity (you can't take an item from its own thread).
        """
        ...

    @property
    def current_container(self) -> EntityInstance | None:
        """The container entity if this is a container context, else None."""
        ...

    @property
    def zone_id(self) -> str:
        """Parent zone ID."""
        ...

    async def get_entities(self) -> list[EntityInstance]:
        """Get all entity instances in this room."""
        ...

    async def get_visible_entities(self) -> list[EntityInstance]:
        """Get visible entities (top-level + visible container contents)."""
        ...

    async def get_room_entity(self, user: IUser) -> RoomEntityInstance | None:
        """Return a virtual room entity for autocomplete, or None.

        Physical rooms return themselves as an entity. Container/focus contexts
        delegate to the underlying room. Inventory threads return None.
        """
        ...


class IEntityInstance(Protocol):
    """Protocol for EntityInstance model."""

    @property
    def instance_id(self) -> UUID | str:
        """Unique instance identifier.

        Returns UUID for database-backed entities, or scheme-based string
        (e.g., 'room://main_hall') for virtual entities.
        """
        ...

    @property
    def entity(self) -> ResolvedEntity:
        """Resolved entity definition."""
        ...

    @property
    def room_id(self) -> str | None:
        """Room ID if in a room, None if in inventory."""
        ...

    @property
    def owner_id(self) -> int | None:
        """Owner's Discord ID if in inventory, None if in room."""
        ...

    # Proxy properties delegating to self.entity for template access
    @property
    def id(self) -> str:
        """Entity definition ID."""
        ...

    @property
    def name(self) -> str:
        """Entity name."""
        ...

    @property
    def description_short(self) -> str | None:
        """Short description template."""
        ...

    @property
    def description_long(self) -> str | None:
        """Long description template."""
        ...

    @property
    def contents_visible(self) -> bool:
        """Whether container contents are visible."""
        ...

    @property
    def rarity(self) -> Rarity:
        """Item rarity tier."""
        ...

    async def move_to_inventory(self, user: IUser) -> EntityInstance:
        """Move this instance to a user's inventory."""
        ...

    async def drop_to_room(
        self, room: IRoom, container: EntityInstance | None = None
    ) -> EntityInstance:
        """Drop this instance to a room, optionally into a container."""
        ...

    async def destroy(self) -> None:
        """Delete this instance from the database."""
        ...

    async def get_contents(self) -> list[EntityInstance]:
        """Get direct children of this container entity."""
        ...

    def with_observers(self, *observers: Observer) -> IEntityInstance:
        """Return a new instance with additional observers attached."""
        ...

    # Capability properties - determine what operations are valid
    @property
    def is_focusable(self) -> bool:
        """Whether this entity can be focused on."""
        ...

    @property
    def can_pickup(self) -> bool:
        """Whether this entity can be picked up."""
        ...

    @property
    def can_drop(self) -> bool:
        """Whether this entity can be dropped."""
        ...

    @property
    def can_destroy(self) -> bool:
        """Whether this entity can be destroyed."""
        ...
