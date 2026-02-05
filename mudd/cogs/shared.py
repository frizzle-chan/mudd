"""Shared utilities for cogs."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import asyncpg
from discord import Interaction, app_commands
from rapidfuzz import fuzz

from mudd.commands import ViewEntity
from mudd.models import EntityInstance, Room
from mudd.models.room import RoomEntityInstance
from mudd.scene import Scene

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


async def entity_instance_id_autocomplete(
    pool: asyncpg.Pool, interaction: Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete callback for at parameter.

    Suggests entity names from the current room, excluding entities
    inside containers with contents_visible=False. When a user has an
    active focus (open container), shows only the focused contents with
    a "[Close {container}] Room" escape option at the top.

    In inventory threads, only shows the thread's item (no Room option).

    Values use scheme-based format:
    - entity://{uuid} for database entities
    - room://{room_id} for virtual room entities
    """
    entities = await autocomplete_entities(
        await Scene.from_interaction(pool, interaction), current
    )
    return [
        app_commands.Choice(
            name=ViewEntity(e).display_name,
            value=(
                e.instance_id
                if isinstance(e, RoomEntityInstance)
                else f"entity://{e.instance_id}"
            ),
        )
        for e in entities
    ][:25]  # Discord limits to 25 options
