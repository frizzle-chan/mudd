"""Shared utilities for cogs."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

import asyncpg
from discord import app_commands
from rapidfuzz import fuzz

from mudd.caches.entity_autocomplete import entities_to_choices
from mudd.models import EntityInstance, Room
from mudd.models.room import RoomEntityInstance
from mudd.models.user import User
from mudd.scene import Scene
from mudd.views import ViewEntity

if TYPE_CHECKING:
    from mudd.caches.entity_autocomplete import EntityAutocompleteCache
    from mudd.caches.user import UserCache

logger = logging.getLogger(__name__)


async def autocomplete_entities(
    scene: Scene, current: str
) -> list[EntityInstance | RoomEntityInstance]:
    """Autocomplete entities the user can see.

    Returns entity instances plus a virtual room entity (unless in inventory context).
    The room entity appears first and shows "[Close X] Room" when user has focus.
    """
    is_inventory_lookup = current.startswith("i.")
    candidates: list[EntityInstance | RoomEntityInstance]

    if is_inventory_lookup:
        # Inventory item lookup - no room entity
        candidates = list(await scene.user.get_inventory())
        current = current[2:]
    else:
        # Room entity lookup
        candidates = list(await scene.room.get_visible_entities())

        room_entity = await scene.room.get_room_entity(scene.user)
        if room_entity:
            candidates.insert(0, room_entity)

    if current == "":
        return candidates

    current = current.lower()

    # Return exact matches
    for e in candidates:
        if e.name.lower() == current:
            return [e]

    return [e for e in candidates if fuzz.partial_ratio(current, e.name.lower()) >= 75]


async def resolve_entity(
    pool: asyncpg.Pool,
    scene: Scene,
    entity_instance_query: str,
    ambiguous_handler: Callable[[str], Awaitable[Any]] = lambda _: asyncio.sleep(0),
) -> EntityInstance | RoomEntityInstance | None:
    """Resolve an entity from a query string.

    Supports scheme-based resolution:
    - room://{room_id} - Virtual room entity
    - entity://{uuid} - Database entity instance
    - {text} - Fuzzy text matching against visible entities
    """
    # Parse room:// scheme
    if entity_instance_query.startswith("room://"):
        room_id = entity_instance_query[7:]  # Strip "room://"
        room = await Room.get(pool, room_id)
        if not room:
            return None
        focus = await scene.user.get_focus()
        focus_name = focus.current_container.name if focus else None
        return room.as_entity(focus_name=focus_name)

    # Parse entity:// scheme
    if entity_instance_query.startswith("entity://"):
        uuid_str = entity_instance_query[9:]  # Strip "entity://"
        try:
            entity_instance_id = UUID(uuid_str)
            return await EntityInstance.get(pool, entity_instance_id)
        except ValueError:
            return None

    # Fall back to fuzzy text matching
    options = await autocomplete_entities(scene, entity_instance_query)

    if len(options) > 1:
        candidates = ", ".join(ViewEntity(e).name for e in options[:3])
        await ambiguous_handler(
            f"Multiple things match that description: {candidates}. "
            "Please be more specific."
        )

    return options[0] if len(options) == 1 else None


def _lookup_entity_choices(
    cache: EntityAutocompleteCache,
    room_id: str,
    focus_id: UUID | None,
) -> list[app_commands.Choice[str]] | None:
    """Try the entity cache for a room+focus pair."""
    if focus_id is not None:
        return cache.get_focus_choices(room_id, focus_id)
    return cache.get_room_choices(room_id)


async def entity_instance_id_autocomplete(
    pool: asyncpg.Pool,
    user_id: int,
    current: str,
    *,
    thread_id: int | None = None,
    entity_cache: EntityAutocompleteCache | None = None,
    user_cache: UserCache | None = None,
) -> list[app_commands.Choice[str]]:
    """Autocomplete callback for entity instance selection.

    Suggests entity names from the current room, excluding entities
    inside containers with contents_visible=False. When a user has an
    active focus (open container), shows only the focused contents with
    a "[Close {container}] Room" escape option at the top.

    In inventory threads, only shows the thread's item (no Room option).

    Values use scheme-based format:
    - entity://{uuid} for database entities
    - room://{room_id} for virtual room entities

    When both caches are provided and the user has typed nothing yet,
    returns precomputed choices with zero database queries.
    """
    # Fast path: no input, not in a thread, caches available
    if current == "" and entity_cache is not None and thread_id is None:
        room_id: str | None = None
        focus_id: UUID | None = None

        # Try fully cached path (zero queries) via user cache
        if user_cache is not None:
            state = user_cache.get(user_id)
            if state is not None:
                room_id = state.current_room
                focus_id = state.focus_id

        # Fallback: resolve from DB
        if room_id is None:
            logger.debug("Autocomplete user cache miss user=%s", user_id)
            room_id = await User.get_current_room(pool, user_id)
            if room_id is not None:
                focus_id = await User.get_active_focus_id(pool, user_id, room_id)

        if room_id is not None:
            choices = _lookup_entity_choices(entity_cache, room_id, focus_id)
            if choices is not None:
                logger.debug("Autocomplete cache hit user=%s room=%s", user_id, room_id)
                return choices

    # Slow path: build scene and query entities
    logger.debug("Autocomplete cache miss (slow path) user=%s", user_id)
    entities = await autocomplete_entities(
        await Scene.from_user(pool, user_id, thread_id=thread_id), current
    )
    return entities_to_choices(entities)
