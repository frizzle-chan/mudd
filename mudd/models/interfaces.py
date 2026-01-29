"""Protocol definitions for model interfaces."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from mudd.models.entity import EntityInstance, ResolvedEntity
    from mudd.models.room import Room
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

    async def get_focused_contents(self) -> list[str]:
        """Get entity IDs accessible through current focus."""
        ...


class IRoom(Protocol):
    """Protocol for Room model."""

    @property
    def id(self) -> str:
        """Room identifier."""
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


class IEntityInstance(Protocol):
    """Protocol for EntityInstance model."""

    @property
    def instance_id(self) -> UUID:
        """Unique instance identifier."""
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
