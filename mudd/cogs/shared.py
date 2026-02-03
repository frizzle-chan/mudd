"""Shared utilities for cogs."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

import asyncpg
import discord
from discord import Interaction, app_commands
from rapidfuzz import fuzz

from mudd.commands2 import ViewEntity
from mudd.models import EntityInstance
from mudd.scene import Scene
from mudd.services.entity_resolution import ViewMode
from mudd.services.rendering import RenderingService, TemplateRenderError

if TYPE_CHECKING:
    from mudd.services.entity import EntityService
    from mudd.services.entity_resolution import (
        EntityResolutionService,
        InteractionContext,
    )
    from mudd.services.inventory import InventoryService
    from mudd.services.visibility import VisibilityServiceProtocol

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


async def handle_escape(
    interaction: Interaction,
    ctx: "InteractionContext",
    *,
    entity_resolution: "EntityResolutionService",
    entity_service: "EntityService",
    visibility_service: "VisibilityServiceProtocol",
    inventory: "InventoryService",
    rendering: RenderingService,
) -> None:
    """Handle escape action (close focus, show room or thread item).

    This is shared between /look and /interact commands.

    Args:
        interaction: Discord interaction
        ctx: Interaction context from entity resolution
        entity_resolution: Service for focus management
        entity_service: Service for entity lookups
        visibility_service: Service for room name lookups
        inventory: Service for inventory thread lookups
        rendering: Service for template rendering
    """
    user_id = interaction.user.id
    room = ctx.room

    if ctx.view_mode == ViewMode.INVENTORY_THREAD and ctx.thread_instance_id:
        # In inventory thread container - close focus and show the container
        await entity_resolution.clear_focus(user_id, reason="close")

        # Get thread item and show it
        channel = interaction.channel
        if isinstance(channel, (discord.abc.GuildChannel, discord.Thread)):
            thread_item = await inventory.get_thread_item(channel)
            if thread_item:
                detail_text = await rendering.render_entity_on_look(
                    thread_item,
                    entity_service,
                    None,
                    include_heading=False,  # Thread title shows the item name
                )
                await interaction.response.send_message(detail_text, ephemeral=True)
                return

        await interaction.response.send_message(
            "You see nothing special.", ephemeral=True
        )
        return

    # Room escape - clear focus and show room
    close_msg = None

    # Get focus to capture entity before clearing (for template rendering)
    focus = await entity_resolution.get_focus(user_id, room)
    focused_entity = None
    if focus:
        focused_entity = await entity_service.get_entity(focus.entity_id)

    # Clear focus with "close" reason to get on_close template
    close_template = await entity_resolution.clear_focus(user_id, reason="close")

    # Render close message if we have template and entity
    if close_template and focused_entity:
        try:
            close_msg = rendering.render(close_template, focused_entity, "")
        except TemplateRenderError:
            logger.warning(
                "Template error rendering on_close for entity '%s'",
                focused_entity.id,
                exc_info=True,
            )
            entity_name = focused_entity.name
            close_msg = f"You step away from the *{entity_name}*."

    # Show room description + top-level entities
    room_name = await visibility_service.get_room_name(room) if room else None
    topic = getattr(interaction.channel, "topic", None)
    room_description = topic or "You see nothing special."

    entity_text = ""
    if room:
        entities = await entity_service.get_top_level_room_entities(room)
        entity_text = await rendering.format_room_entities(
            entities, entity_service, room
        )

    # Build message, prepending close message if present
    parts = []
    if close_msg:
        parts.append(close_msg)
    if room_name:
        parts.append(f"### {room_name}")
    parts.append(room_description)
    if entity_text:
        parts.append(entity_text)

    message = "\n\n".join(parts)
    await interaction.response.send_message(message, ephemeral=True)
