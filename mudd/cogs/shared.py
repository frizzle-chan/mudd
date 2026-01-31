"""Shared utilities for cogs."""
from uuid import UUID
from ast import arg
import asyncpg
from mudd.models import EntityInstance

import logging
from typing import TYPE_CHECKING

import discord
from discord import Interaction
from discord.ext import commands

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
