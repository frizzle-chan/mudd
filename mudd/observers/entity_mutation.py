"""Generic observer for entity mutation events.

Extracts affected room IDs from entity pickup/drop/destroy events and
delegates to caller-provided callbacks. Created per-scene with room context
so pickup events (where entity.room_id has been cleared) still know which
room was affected.

Multiple caches can reuse this observer by providing their own callbacks
via factory methods (e.g., AutocompleteCache.create_invalidator).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from mudd.events import (
    EntityDestroyedEvent,
    EntityDroppedEvent,
    EntityPickedUpEvent,
    GameEvent,
)


class EntityMutationObserver:
    """Observer that reacts to entity mutations by room.

    On notify(): extracts the affected room_id and calls on_room_changed
    synchronously (for instant invalidation).

    On flush(): calls on_rebuild for each affected room asynchronously
    (for background cache warming).
    """

    def __init__(
        self,
        room_id: str,
        on_room_changed: Callable[[str], None],
        on_rebuild: Callable[[str], Awaitable[None]],
    ) -> None:
        self._room_id = room_id
        self._on_room_changed = on_room_changed
        self._on_rebuild = on_rebuild
        self._affected_rooms: set[str] = set()

    def _handle(self, room_id: str) -> None:
        """Invalidate a room and queue it for rebuild."""
        self._on_room_changed(room_id)
        self._affected_rooms.add(room_id)

    def notify(self, event: GameEvent) -> None:
        """Extract affected room from entity mutation events."""
        match event:
            case EntityPickedUpEvent():
                # Entity left the scene's room (instance.room_id is already None)
                self._handle(self._room_id)
            case EntityDroppedEvent(instance=inst) if inst.room_id:
                # Entity entered a room
                self._handle(inst.room_id)
            case EntityDestroyedEvent(instance=inst):
                # Entity removed — use its room or fall back to scene room
                self._handle(inst.room_id or self._room_id)

    async def flush(self) -> None:
        """Rebuild all affected rooms."""
        rooms = self._affected_rooms.copy()
        self._affected_rooms.clear()
        for room_id in rooms:
            await self._on_rebuild(room_id)
