"""Interact command for entity interactions."""

import logging
from typing import TYPE_CHECKING

import asyncpg
from discord import Interaction, app_commands
from discord.ext import commands

from mudd.matching.entity_matcher import match_entity_by_prefix
from mudd.matching.verb_matcher import match_verb
from mudd.services.entity import ResolvedEntity
from mudd.services.rendering import RenderingService, TemplateRenderError
from mudd.types import VerbAction

if TYPE_CHECKING:
    from mudd.services.entity import EntityService
    from mudd.services.player_context import PlayerContextService
    from mudd.services.visibility import VisibilityServiceProtocol

logger = logging.getLogger(__name__)


class Interact(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot | None,
        entity_service: "EntityService",
        player_context: "PlayerContextService",
        visibility_service: "VisibilityServiceProtocol",
        pool: asyncpg.Pool,
        rendering_service: RenderingService,
    ) -> None:
        self.bot = bot
        self.entity_service = entity_service
        self.player_context = player_context
        self.visibility_service = visibility_service
        self.pool = pool
        self._rendering = rendering_service

    async def with_autocomplete(
        self, interaction: Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete callback for with parameter.

        Suggests entity names from the current room, excluding entities
        inside containers with contents_visible=False. When a user has an
        active focus (open container), prioritizes focused contents with
        "[Container Name]" prefix.
        """
        try:
            await self.visibility_service.wait_for_startup()

            room = getattr(interaction.channel, "name", None)
            if not room:
                return []

            # Get autocomplete choices with text filtering
            choices = await self.player_context.get_visible_entities(
                room, interaction.user.id, query=current
            )

            # Return as Discord choices (limit 25 per Discord API)
            return [
                app_commands.Choice(
                    name=c.display_name,
                    value=c.instance.entity.name,  # Use actual name for matching
                )
                for c in choices
            ][:25]
        except asyncpg.PostgresError:
            logger.exception(
                "Database error in target autocomplete for room '%s'",
                getattr(interaction.channel, "name", "unknown"),
            )
            return []
        except Exception:
            logger.exception(
                "Unexpected error in target autocomplete for room '%s'",
                getattr(interaction.channel, "name", "unknown"),
            )
            return []

    @app_commands.command(name="interact", description="Interact with an entity")
    @app_commands.describe(
        with_entity="Thing to interact with",
        do="Action to perform (e.g., smash, touch, take)",
    )
    @app_commands.autocomplete(with_entity=with_autocomplete)
    async def interact(self, interaction: Interaction, with_entity: str, do: str):
        """Interact with an entity using a verb."""
        await self.visibility_service.wait_for_startup()

        room = getattr(interaction.channel, "name", None)
        if not room:
            await interaction.response.send_message(
                "You can't interact with anything here.", ephemeral=True
            )
            return

        user_id = interaction.user.id

        # Uses get_room_entities (not get_autocomplete_entities) intentionally:
        # players can interact with hidden container contents if they know the name
        all_entities = await self.entity_service.get_room_entities(room)

        # Resolve target to entity
        match_result = match_entity_by_prefix(with_entity, all_entities)

        if match_result.is_empty():
            await interaction.response.send_message(
                f"You don't see '{with_entity}' here.", ephemeral=True
            )
            return

        if match_result.is_ambiguous():
            names = [m.instance.entity.name for m in match_result.matches]
            names_list = ", ".join(f"*{name}*" for name in names)
            await interaction.response.send_message(
                f"Which one? {names_list}", ephemeral=True
            )
            return

        # Unique match - resolve verb to action
        matched_instance = match_result.matches[0].instance
        entity = matched_instance.entity

        action_type = await match_verb(self.pool, do)

        if action_type is None:
            await interaction.response.send_message(
                "You can't do that.", ephemeral=True
            )
            return

        # Check if target is in current focus (to decide whether to clear focus)
        is_in_focus = await self.player_context.is_entity_in_focus(
            user_id, room, entity.id
        )

        if is_in_focus:
            # Update timestamp to prevent timeout when interacting with focused content
            await self.player_context.update_focus_timestamp(user_id)
        else:
            # Clear focus when interacting with entity not in current focus
            await self.player_context.clear_focus(user_id, reason="interaction")

        # Get handler text based on action
        handler_text = _get_handler_text(entity, action_type)

        if handler_text is None:
            await interaction.response.send_message("Nothing happens.", ephemeral=True)
            return

        # Fetch container contents for template (regardless of contents_visible)
        container_contents = await self.entity_service.get_container_contents(
            entity.id, room
        )
        contents_str = self._rendering.build_contents_string(container_contents)

        # Render template with entity context
        try:
            output = self._rendering.render(handler_text, entity, contents_str)
        except TemplateRenderError:
            logger.warning(
                "Template error rendering '%s' handler for entity '%s'",
                action_type.value,
                entity.id,
                exc_info=True,
            )
            output = f"*{entity.name}* responds, but something went wrong."

        # Handle focus changes based on action type
        if action_type == VerbAction.ON_OPEN and entity.focus_mode != "none":
            # Establish focus when opening a focusable entity (e.g., container)
            await self.player_context.set_focus(user_id, room, entity)
        elif action_type == VerbAction.ON_CLOSE:
            # Clear focus when explicitly closing
            # Get close message (template) before clearing
            close_template = await self.player_context.clear_focus(
                user_id, reason="close"
            )
            if close_template:
                # Render the close template and append
                try:
                    close_output = self._rendering.render(close_template, entity, "")
                    output = f"{output}\n\n{close_output}"
                except TemplateRenderError:
                    logger.warning(
                        "Template error rendering on_close for entity '%s'",
                        entity.id,
                        exc_info=True,
                    )
                    output = f"{output}\n\nYou step away from the *{entity.name}*."

        await interaction.response.send_message(output, ephemeral=True)


def _get_handler_text(entity: ResolvedEntity, action: VerbAction) -> str | None:
    """Get handler text from entity based on action.

    Args:
        entity: The resolved entity
        action: The verb action (on_look, on_attack, etc.)

    Returns:
        Handler text or None if no handler defined
    """
    handler_map = {
        VerbAction.ON_LOOK: entity.on_look,
        VerbAction.ON_TOUCH: entity.on_touch,
        VerbAction.ON_ATTACK: entity.on_attack,
        VerbAction.ON_USE: entity.on_use,
        VerbAction.ON_TAKE: entity.on_take,
        VerbAction.ON_OPEN: entity.on_open,
        VerbAction.ON_CLOSE: entity.on_close,
    }
    return handler_map.get(action)
