"""In-memory cache for autocomplete choices.

Precomputes default (no-input) autocomplete choices per room and per focus
context. Rebuilt during periodic sync to avoid repeated DB queries on every
autocomplete interaction.

Invalidated instantly on entity mutations (pickup, drop, destroy) via an
EntityMutationObserver created by ``create_invalidator()``, then rebuilt
in the background during flush().
"""

from __future__ import annotations

import logging
from functools import partial
from uuid import UUID

import asyncpg
from discord import app_commands

from mudd.models.entity import EntityInstance
from mudd.models.room import Room, RoomEntityInstance
from mudd.observers.entity_mutation import EntityMutationObserver
from mudd.views import ViewEntity

logger = logging.getLogger(__name__)


def _make_choice(e: EntityInstance | RoomEntityInstance) -> app_commands.Choice[str]:
    """Format an entity as a Discord autocomplete choice."""
    return app_commands.Choice(
        name=ViewEntity(e).display_name,
        value=(
            e.instance_id
            if isinstance(e, RoomEntityInstance)
            else f"entity://{e.instance_id}"
        ),
    )


class AutocompleteCache:
    """In-memory cache for default autocomplete choices.

    Stores precomputed autocomplete choice lists indexed by room (no focus)
    and by (room, focused-entity-instance) pairs.

    Rebuilt atomically during periodic sync so lookups never see partial state.
    Invalidated instantly per-room on entity mutations, then rebuilt during
    observer flush.
    """

    def __init__(self) -> None:
        self._room_choices: dict[str, list[app_commands.Choice[str]]] = {}
        self._focus_choices: dict[tuple[str, str], list[app_commands.Choice[str]]] = {}

    def get_room_choices(self, room_id: str) -> list[app_commands.Choice[str]] | None:
        """Get cached default choices for a room (no focus)."""
        return self._room_choices.get(room_id)

    def get_focus_choices(
        self, room_id: str, entity_instance_id: UUID
    ) -> list[app_commands.Choice[str]] | None:
        """Get cached default choices for a focus context."""
        return self._focus_choices.get((room_id, str(entity_instance_id)))

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
        """
        room_choices: dict[str, list[app_commands.Choice[str]]] = {}
        focus_choices: dict[tuple[str, str], list[app_commands.Choice[str]]] = {}

        rooms = await Room.get_all(pool)

        for room in rooms:
            rc, fc = await _compute_room_entries(pool, room)
            room_choices[room.id] = rc
            focus_choices.update(fc)

        # Atomic swap
        self._room_choices = room_choices
        self._focus_choices = focus_choices

        logger.info(
            "Rebuilt autocomplete cache: %d rooms, %d focus contexts",
            len(room_choices),
            len(focus_choices),
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

    def create_invalidator(
        self, pool: asyncpg.Pool, room_id: str
    ) -> EntityMutationObserver:
        """Create an observer that invalidates this cache on entity mutations.

        The returned observer immediately removes affected room entries on
        notify() and rebuilds them during flush().
        """
        return EntityMutationObserver(
            room_id=room_id,
            on_room_changed=self.invalidate_room,
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
    # No-focus choices: room entity + visible entities
    visible = await room.get_visible_entities()
    room_entity = room.as_entity(focus_name=None)

    room_choices: list[app_commands.Choice[str]] = [_make_choice(room_entity)]
    for e in visible:
        room_choices.append(_make_choice(e))

    # Focus choices for each top-level entity
    focus_choices: dict[tuple[str, str], list[app_commands.Choice[str]]] = {}
    top_level = await EntityInstance.get_top_level_by_room(pool, room)
    for entity in top_level:
        focus_room_entity = room.as_entity(focus_name=entity.name)
        contents = await entity.get_contents()

        fc: list[app_commands.Choice[str]] = [
            _make_choice(focus_room_entity),
            _make_choice(entity),
        ]
        for c in contents:
            fc.append(_make_choice(c))
        focus_choices[(room.id, str(entity.instance_id))] = fc[:25]

    return room_choices[:25], focus_choices
