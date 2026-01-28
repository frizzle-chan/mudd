"""Look command for viewing surroundings and examining entities."""

import logging
from typing import TYPE_CHECKING

import asyncpg
from discord import Interaction, app_commands
from discord.ext import commands

from mudd.cogs.shared import handle_escape
from mudd.services.entity_resolution import ResolutionError, ViewMode
from mudd.services.rendering import RenderingService

if TYPE_CHECKING:
    from mudd.services.currency import CurrencyService
    from mudd.services.entity import EntityService
    from mudd.services.entity_resolution import EntityResolutionService
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
        # Build context for resolution
        ctx = await self.entity_resolution.build_context(interaction, at)
        user_id = interaction.user.id
        room = ctx.room

        # Handle "Room" and empty input as escape (show room description)
        # This supports both legacy calls with at="Room" and new escape:room values
        if not at or at == "Room":
            await handle_escape(
                interaction,
                ctx,
                entity_resolution=self.entity_resolution,
                entity_service=self.entity_service,
                visibility_service=self.visibility_service,
                inventory=self._inventory,
                rendering=self._rendering,
            )
            return

        # Resolve target using unified API
        result = await self.entity_resolution.resolve_target(ctx, at)

        if isinstance(result, ResolutionError):
            if result.error_type == "escape":
                # Handle escape - clear focus and show room/item
                await handle_escape(
                    interaction,
                    ctx,
                    entity_resolution=self.entity_resolution,
                    entity_service=self.entity_service,
                    visibility_service=self.visibility_service,
                    inventory=self._inventory,
                    rendering=self._rendering,
                )
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
