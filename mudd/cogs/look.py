"""Look command for viewing surroundings and examining entities."""

import logging
from typing import TYPE_CHECKING, cast

import asyncpg
from discord import Interaction, app_commands
from discord.ext import commands

from mudd.commands import ActionContext, create_command
from mudd.services.entity_resolution import ResolutionError, ViewMode, encode_choice
from mudd.services.rendering import (
    EntityContext,
    RenderingService,
    RoomContext,
    TemplateRenderError,
)
from mudd.types import UserContext, VerbAction

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
        pool: asyncpg.Pool,
    ) -> None:
        self.bot = bot
        self.entity_service = entity_service
        self.entity_resolution = entity_resolution
        self.visibility_service = visibility_service
        self._rendering = rendering_service
        self._inventory = inventory_service
        self._currency = currency_service
        self._pool = pool

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

        # If "Room" selected, resolve to room entity
        if at == "Room":
            room_entity_id = f"room:{room}"
            at = encode_choice("room", room_entity_id)

        # Resolve target using unified API
        result = await self.entity_resolution.resolve_target(ctx, at)

        # Check resolution result
        if isinstance(result, ResolutionError):
            if result.error_type == "ambiguous":
                # Disambiguation prompt
                await interaction.response.send_message(result.message, ephemeral=True)
                return

            # Not found or other error
            if ctx.view_mode == ViewMode.INVENTORY_THREAD:
                await interaction.response.send_message(result.message, ephemeral=True)
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
        source = cast(str, result.source)
        is_room_entity = entity.id.startswith("room:")
        is_inventory_source = source in ("inventory", "container")

        # Update focus timestamp if looking at entity in focus (prevents timeout)
        if ctx.view_mode == ViewMode.ROOM and not is_room_entity:
            is_in_focus = await self.entity_resolution.is_entity_in_focus(
                user_id, room, entity.id
            )
            if is_in_focus:
                await self.entity_resolution.update_focus_timestamp(user_id)

        # Create lazy room context (for all entities in room context)
        # Data is fetched on-demand when templates call room.description()/entities()
        room_ctx: RoomContext | None = None
        if not is_inventory_source:
            room_ctx = RoomContext(
                room, self._pool, self.entity_service, self._rendering
            )

        # Create EntityContext with lazy contents fetching
        entity_ctx = EntityContext(
            entity=entity,
            instance_id=matched_instance.instance_id,
            source=cast(str, source),  # type: ignore[arg-type]
            room=room,
            user_id=user_id,
            entity_service=self.entity_service,
            entity_resolution=self.entity_resolution,
            rendering_service=self._rendering,
        )

        # Create user context for template with lazy balance fetching
        user_context = UserContext(
            name=interaction.user.display_name,
            mention=interaction.user.mention,
            user_id=user_id,
            currency_service=self._currency,
        )

        # Build action context and execute LookCommand
        action_ctx = ActionContext(
            interaction=interaction,
            entity=entity_ctx,
            source=cast(str, source),  # type: ignore[arg-type]
            user=user_context,
            container=None,
            room=room_ctx,
        )

        command = create_command(VerbAction.ON_LOOK, self._rendering)
        try:
            cmd_result = await command.execute(action_ctx)
        except TemplateRenderError:
            logger.warning(
                "Template error rendering on_look for entity '%s'",
                entity.id,
                exc_info=True,
            )
            output = "You see nothing special."
            effects = cmd_result.effects if "cmd_result" in dir() else None
        else:
            output = cmd_result.output
            effects = cmd_result.effects

        # Add heading
        if is_room_entity:
            room_name = await self.visibility_service.get_room_name(room)
            heading = room_name or "Unknown Room"
        else:
            heading = entity.display_name

        detail_text = f"### {heading}\n\n{output}"

        # Process focus effects
        if effects:
            if effects.has_set_focus:
                await self.entity_resolution.set_focus(
                    user_id, matched_instance.instance_id
                )
            if effects.has_clear_focus:
                await self.entity_resolution.clear_focus(user_id, reason="close")

        await interaction.response.send_message(detail_text, ephemeral=True)
