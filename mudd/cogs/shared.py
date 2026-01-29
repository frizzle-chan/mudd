"""Shared utilities for cogs."""

import logging
from typing import TYPE_CHECKING

import discord
from discord import Interaction

from mudd.services.entity_resolution import ViewMode
from mudd.services.rendering import RenderingService

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
    """Handle escape action in inventory thread (close focus, show thread item).

    This is only used for inventory thread containers. Room escape is now
    handled by the room entity's on_look template (ADR 0006).

    Args:
        interaction: Discord interaction
        ctx: Interaction context from entity resolution
        entity_resolution: Service for focus management
        entity_service: Service for entity lookups
        visibility_service: Service for room name lookups (unused, kept for API compat)
        inventory: Service for inventory thread lookups
        rendering: Service for template rendering
    """
    user_id = interaction.user.id

    if ctx.view_mode != ViewMode.INVENTORY_THREAD or not ctx.thread_instance_id:
        # This shouldn't happen - room escape should go through room entity
        logger.warning(
            "handle_escape called outside inventory thread context for user %s",
            user_id,
        )
        await interaction.response.send_message(
            "You see nothing special.", ephemeral=True
        )
        return

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

    await interaction.response.send_message("You see nothing special.", ephemeral=True)
