"""In-memory cache for entity autocomplete choices.

Precomputes default (no-input) autocomplete choices per room and per focus
context. Rebuilt during periodic sync to avoid repeated DB queries on every
autocomplete interaction.

Invalidated instantly on entity mutations (pickup, drop, destroy) via a
CacheInvalidationObserver created by ``create_invalidator()``, then rebuilt
in the background during flush().

The ``entities_to_choices()`` function is the single source of truth for
converting entities to Discord autocomplete choices — used by both the
cache rebuild and the live autocomplete slow path.
"""

from __future__ import annotations

import logging
from functools import partial
from uuid import UUID

import asyncpg
from discord import app_commands

from mudd.events import EntityDestroyedEvent, EntityDroppedEvent, EntityPickedUpEvent
from mudd.models.entity import EntityInstance
from mudd.models.room import Room, RoomEntityInstance
from mudd.observers.cache import CacheInvalidationObserver
from mudd.views import ViewEntity

logger = logging.getLogger(__name__)

# Discord limits autocomplete to 25 options
_MAX_CHOICES = 25


def _make_choice(e: EntityInstance | RoomEntityInstance) -> app_commands.Choice[str]:
    """Format a single entity as a Discord autocomplete choice."""
    return app_commands.Choice(
        name=ViewEntity(e).display_name,
        value=(
            e.instance_id
            if isinstance(e, RoomEntityInstance)
            else f"entity://{e.instance_id}"
        ),
    )


def entities_to_choices(
    entities: list[EntityInstance | RoomEntityInstance],
) -> list[app_commands.Choice[str]]:
    """Convert entities to Discord autocomplete choices.

    This is the single source of truth for entity → Choice formatting.
    Used by both the cache rebuild and the live autocomplete slow path.
    """
    return [_make_choice(e) for e in entities][:_MAX_CHOICES]


class EntityAutocompleteCache:
    """In-memory cache for default entity autocomplete choices.

    Stores precomputed autocomplete choice lists indexed by room (no focus)
    and by (room, focused-entity-instance) pairs.

    Rebuilt atomically during periodic sync so lookups never see partial state.
    Invalidated instantly per-room on entity mutations, then rebuilt during
    observer flush.
    """

    def __init__(self) -> None:
        self._room_choices: dict[str, list[app_commands.Choice[str]]] = {}
        self._focus_choices: dict[tuple[str, str], list[app_commands.Choice[str]]] = {}
        self._thread_choices: dict[int, list[app_commands.Choice[str]]] = {}

    def get_room_choices(self, room_id: str) -> list[app_commands.Choice[str]] | None:
        """Get cached default choices for a room (no focus)."""
        return self._room_choices.get(room_id)

    def get_focus_choices(
        self, room_id: str, entity_instance_id: UUID
    ) -> list[app_commands.Choice[str]] | None:
        """Get cached default choices for a focus context."""
        return self._focus_choices.get((room_id, str(entity_instance_id)))

    def get_thread_choices(
        self, thread_id: int
    ) -> list[app_commands.Choice[str]] | None:
        """Get cached default choices for an inventory thread."""
        return self._thread_choices.get(thread_id)

    def invalidate_thread(self, thread_id: int) -> None:
        """Remove cached choices for a thread.

        After invalidation, autocomplete requests for this thread fall through
        to the slow path until the cache is rebuilt.
        """
        self._thread_choices.pop(thread_id, None)

    def invalidate_room(self, room_id: str) -> None:
        """Immediately remove cached choices for a room.

        After invalidation, autocomplete requests for this room fall through
        to the slow path until the cache is rebuilt.
        """
        self._room_choices.pop(room_id, None)
        keys_to_remove = [k for k in self._focus_choices if k[0] == room_id]
        for k in keys_to_remove:
            del self._focus_choices[k]

    async def rebuild(self, pool: asyncpg.Pool) -> None:
        """Rebuild entire cache from current database state.

        Precomputes:
        - Default choices for each room (room entity + visible entities)
        - Focus choices for each top-level entity in each room
          (room entity with close prefix + container + contents)
        - Thread choices for each entity with a discord_thread_id
        """
        room_choices: dict[str, list[app_commands.Choice[str]]] = {}
        focus_choices: dict[tuple[str, str], list[app_commands.Choice[str]]] = {}
        thread_choices: dict[int, list[app_commands.Choice[str]]] = {}

        rooms = await Room.get_all(pool)

        for room in rooms:
            rc, fc = await _compute_room_entries(pool, room)
            room_choices[room.id] = rc
            focus_choices.update(fc)

        # Build thread choices for all entities with a discord thread
        thread_instances = await EntityInstance.get_all_with_threads(pool)
        for instance in thread_instances:
            thread_choices[instance.thread_id] = entities_to_choices([instance.entity])

        # Atomic swap
        self._room_choices = room_choices
        self._focus_choices = focus_choices
        self._thread_choices = thread_choices

        logger.info(
            "Rebuilt entity autocomplete cache:"
            " %d rooms, %d focus contexts, %d threads",
            len(room_choices),
            len(focus_choices),
            len(thread_choices),
        )

    async def rebuild_room(self, pool: asyncpg.Pool, room_id: str) -> None:
        """Rebuild cache entries for a single room.

        Called after invalidation to re-warm the cache without a full rebuild.
        """
        room = await Room.get(pool, room_id)
        if room is None:
            return

        rc, fc = await _compute_room_entries(pool, room)

        # Remove stale focus entries for this room before inserting new ones
        keys_to_remove = [k for k in self._focus_choices if k[0] == room_id]
        for k in keys_to_remove:
            del self._focus_choices[k]

        self._room_choices[room_id] = rc
        self._focus_choices.update(fc)

    async def rebuild_thread(self, pool: asyncpg.Pool, thread_id: int) -> None:
        """Rebuild cache entry for a single inventory thread.

        Called after invalidation to re-warm the cache without a full rebuild.
        """
        instance = await EntityInstance.get_by_inventory_thread_id(pool, thread_id)
        if instance is None:
            self._thread_choices.pop(thread_id, None)
            return

        self._thread_choices[thread_id] = entities_to_choices([instance])

    def create_invalidator(
        self, pool: asyncpg.Pool, room_id: str
    ) -> CacheInvalidationObserver[str]:
        """Create an observer that invalidates this cache on entity mutations.

        The returned observer immediately removes affected room entries on
        notify() and rebuilds them during flush().

        Args:
            pool: Database pool for rebuilding cache entries.
            room_id: Current scene room — used as fallback when the entity's
                room_id has already been cleared (e.g., after pickup).
        """
        return CacheInvalidationObserver(
            extractors={
                EntityPickedUpEvent: lambda _: room_id,
                EntityDroppedEvent: lambda e: e.instance.room_id,
                EntityDestroyedEvent: lambda e: e.instance.room_id or room_id,
            },
            on_invalidate=self.invalidate_room,
            on_rebuild=partial(self.rebuild_room, pool),
        )


async def _compute_room_entries(
    pool: asyncpg.Pool, room: Room
) -> tuple[
    list[app_commands.Choice[str]],
    dict[tuple[str, str], list[app_commands.Choice[str]]],
]:
    """Compute room and focus choices for a single room.

    Returns:
        Tuple of (room_choices, focus_choices_dict)
    """
    # Room choices: delegates contents_visible filtering to model
    visible = await room.get_visible_entities()
    room_entity = room.as_entity(focus_name=None)
    room_choices = entities_to_choices([room_entity, *visible])

    # Focus choices: all contents regardless of contents_visible
    top_level = [e for e in visible if e.container_entity_id is None]
    contents_by_container = await room.get_entities_by_container()

    focus_choices: dict[tuple[str, str], list[app_commands.Choice[str]]] = {}
    for entity in top_level:
        focus_room_entity = room.as_entity(focus_name=entity.name)
        contents = contents_by_container.get(entity.entity.id, [])
        focus_choices[(room.id, str(entity.instance_id))] = entities_to_choices(
            [focus_room_entity, entity, *contents]
        )

    return room_choices, focus_choices
