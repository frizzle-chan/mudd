"""In-memory cache for autocomplete choices.

Precomputes default (no-input) autocomplete choices per room and per focus
context. Rebuilt during periodic sync to avoid repeated DB queries on every
autocomplete interaction.
"""

from __future__ import annotations

import logging
from uuid import UUID

import asyncpg
from discord import app_commands

from mudd.models.entity import EntityInstance
from mudd.models.room import Room, RoomEntityInstance
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

    async def rebuild(self, pool: asyncpg.Pool) -> None:
        """Rebuild cache from current database state.

        Precomputes:
        - Default choices for each room (room entity + visible entities)
        - Focus choices for each top-level entity in each room
          (room entity with close prefix + container + contents)
        """
        room_choices: dict[str, list[app_commands.Choice[str]]] = {}
        focus_choices: dict[tuple[str, str], list[app_commands.Choice[str]]] = {}

        rooms = await Room.get_all(pool)

        for room in rooms:
            # Precompute no-focus choices
            visible = await room.get_visible_entities()
            room_entity = room.as_entity(focus_name=None)

            choices: list[app_commands.Choice[str]] = [_make_choice(room_entity)]
            for e in visible:
                choices.append(_make_choice(e))
            room_choices[room.id] = choices[:25]

            # Precompute focus choices for each top-level entity
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

        # Atomic swap
        self._room_choices = room_choices
        self._focus_choices = focus_choices

        logger.info(
            "Rebuilt autocomplete cache: %d rooms, %d focus contexts",
            len(room_choices),
            len(focus_choices),
        )
