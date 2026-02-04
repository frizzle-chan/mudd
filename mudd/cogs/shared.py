"""Shared utilities for cogs."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import asyncpg
from discord import Interaction, app_commands
from rapidfuzz import fuzz

from mudd.commands2 import ViewEntity
from mudd.models import EntityInstance
from mudd.scene import Scene

logger = logging.getLogger(__name__)


async def autocomplete_entities(scene: Scene, current: str) -> list[EntityInstance]:
    """Autocomplete entities the user can see."""
    if current.startswith("i."):
        # Inventory item lookup
        candidates = await scene.user.get_inventory()
        current = current[2:]
    else:
        # Room entity lookup
        candidates = await scene.room.get_visible_entities()

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
    ambiguous_handler: Callable[[str], Awaitable[Any]] = lambda msg: asyncio.sleep(0),
) -> EntityInstance | None:
    try:
        entity_instance_id = UUID(entity_instance_query)
        return await EntityInstance.get(pool, entity_instance_id)
    except ValueError:
        options = await autocomplete_entities(scene, entity_instance_query)

        if len(options) > 1:
            candidates = ", ".join(ViewEntity(e).name for e in options[:3])
            await ambiguous_handler(
                f"Multiple things match that description: {candidates}. "
                "Please be more specific."
            )

        return options[0] if len(options) == 1 else None


async def entity_instance_id_autocomplete(
    pool, interaction: Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete callback for at parameter.

    Suggests entity names from the current room, excluding entities
    inside containers with contents_visible=False. When a user has an
    active focus (open container), shows only the focused contents with
    a "[Close {container}] Room" escape option at the top.

    In inventory threads, only shows the thread's item (no Room option).
    """
    return [
        app_commands.Choice(name=ViewEntity(e).display_name, value=str(e.instance_id))
        for e in await autocomplete_entities(
            await Scene.from_interaction(pool, interaction), current
        )
    ][:25]  # Discord limits to 25 options
