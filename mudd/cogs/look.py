"""Look command for viewing surroundings and examining entities."""

import logging
from typing import TYPE_CHECKING

import asyncpg
import discord
from discord import Interaction, app_commands
from discord.ext import commands

from mudd.services.entity_resolution import ResolutionError, ViewMode
from mudd.services.rendering import RenderingService, TemplateRenderError

if TYPE_CHECKING:
    from mudd.services.currency import CurrencyService
    from mudd.services.entity import EntityService
    from mudd.services.entity_resolution import (
        EntityResolutionService,
        InteractionContext,
    )
    from mudd.services.inventory import InventoryService
    from mudd.services.visibility import VisibilityServiceProtocol

logger = logging.getLogger(__name__)


class Look(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot | None,
        entity_service: "EntityService",
        entity_resolution: "EntityResolutionService",
        visibility_service: "VisibilityServiceProtocol",
        rendering_service: RenderingService,
        inventory_service: "InventoryService",
        currency_service: "CurrencyService",
    ) -> None:
        self.bot = bot
        self.entity_service = entity_service
        self.entity_resolution = entity_resolution
        self.visibility_service = visibility_service
        self._rendering = rendering_service
        self._inventory = inventory_service
        self._currency = currency_service

    async def at_autocomplete(
        self, interaction: Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete callback for at parameter.

        Suggests entity names from the current room, excluding entities
        inside containers with contents_visible=False. When a user has an
        active focus (open container), shows only the focused contents with
        a "[Close {container}] Room" escape option at the top.

        In inventory threads, only shows the thread's item (no Room option).
        """
        try:
            await self.visibility_service.wait_for_startup()

            # Build context and get choices using unified API
            ctx = await self.entity_resolution.build_context(interaction, current)
            return await self.entity_resolution.get_autocomplete_choices(ctx, current)
        except asyncpg.PostgresError:
            logger.exception(
                "Database error in at autocomplete for room '%s'",
                getattr(interaction.channel, "name", "unknown"),
            )
            return []
        except Exception:
            logger.exception(
                "Unexpected error in at autocomplete for room '%s'",
                getattr(interaction.channel, "name", "unknown"),
            )
            return []

    @app_commands.command(name="look", description="View surroundings or examine item")
    @app_commands.describe(at="Thing to examine")
    @app_commands.autocomplete(at=at_autocomplete)
    async def look(self, interaction: Interaction, at: str):
        """Look at room or specific entity."""
        await self.visibility_service.wait_for_startup()

        # Build context for resolution
        ctx = await self.entity_resolution.build_context(interaction, at)
        user_id = interaction.user.id
        room = ctx.room

        # Handle "Room" and empty input as escape (show room description)
        # This supports both legacy calls with at="Room" and new escape:room values
        if not at or at == "Room":
            await self._handle_escape(interaction, ctx)
            return

        # Resolve target using unified API
        result = await self.entity_resolution.resolve_target(ctx, at)

        if isinstance(result, ResolutionError):
            if result.error_type == "escape":
                # Handle escape - clear focus and show room/item
                await self._handle_escape(interaction, ctx)
                return
            elif result.error_type == "ambiguous":
                # Disambiguation prompt
                await interaction.response.send_message(result.message, ephemeral=True)
                return
            else:
                # Not found
                if ctx.view_mode == ViewMode.INVENTORY_THREAD:
                    await interaction.response.send_message(
                        result.message, ephemeral=True
                    )
                else:
                    # Show room description on not found
                    topic = getattr(interaction.channel, "topic", None)
                    room_description = topic or "You see nothing special."
                    await interaction.response.send_message(
                        f"{result.message}\n\n{room_description}",
                        ephemeral=True,
                    )
                return

        # Successfully resolved entity
        matched_instance = result.instance
        entity = matched_instance.entity

        # Handle focus for room entities only
        if ctx.view_mode == ViewMode.ROOM:
            # Check if looking at entity that is NOT in current focus
            is_in_focus = await self.entity_resolution.is_entity_in_focus(
                user_id, room, entity.id
            )

            # Clear focus if looking at unrelated entity
            # (per ADR 0003: "focus follows attention")
            if not is_in_focus:
                await self.entity_resolution.clear_focus(user_id, reason="interaction")
            else:
                # Update timestamp to prevent timeout
                await self.entity_resolution.update_focus_timestamp(user_id)

        # Render on_look template
        # Use room=None for inventory items
        render_room = room if result.source == "room" else None

        # Fetch balance for wallet entities
        balance_str = ""
        if entity.id == "wallet":
            balance = await self._currency.get_balance(user_id)
            if balance is not None:
                balance_str = f"¥{balance:,}"

        detail_text = await self._rendering.render_entity_on_look(
            matched_instance, self.entity_service, render_room, balance_str
        )
        await interaction.response.send_message(detail_text, ephemeral=True)

    async def _handle_escape(
        self, interaction: Interaction, ctx: "InteractionContext"
    ) -> None:
        """Handle escape action (close focus, show room or thread item)."""
        user_id = interaction.user.id
        room = ctx.room

        if ctx.view_mode == ViewMode.INVENTORY_THREAD and ctx.thread_instance_id:
            # In inventory thread container - close focus and show the container
            await self.entity_resolution.clear_focus(user_id, reason="close")

            # Get thread item and show it
            channel = interaction.channel
            if isinstance(channel, (discord.abc.GuildChannel, discord.Thread)):
                thread_item = await self._inventory.get_thread_item(channel)
                if thread_item:
                    detail_text = await self._rendering.render_entity_on_look(
                        thread_item, self.entity_service, None
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
        focus = await self.entity_resolution.get_focus(user_id, room)
        focused_entity = None
        if focus:
            focused_entity = await self.entity_service.get_entity(focus.entity_id)

        # Clear focus with "close" reason to get on_close template
        close_template = await self.entity_resolution.clear_focus(
            user_id, reason="close"
        )

        # Render close message if we have template and entity
        if close_template and focused_entity:
            try:
                close_msg = self._rendering.render(close_template, focused_entity, "")
            except TemplateRenderError:
                logger.warning(
                    "Template error rendering on_close for entity '%s'",
                    focused_entity.id,
                    exc_info=True,
                )
                entity_name = focused_entity.name
                close_msg = f"You step away from the *{entity_name}*."

        # Show room description + top-level entities
        room_name = await self.visibility_service.get_room_name(room) if room else None
        topic = getattr(interaction.channel, "topic", None)
        room_description = topic or "You see nothing special."

        entity_text = ""
        if room:
            entities = await self.entity_service.get_top_level_room_entities(room)
            entity_text = await self._rendering.format_room_entities(
                entities, self.entity_service, room
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
