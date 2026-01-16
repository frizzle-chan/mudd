"""Interact command for entity interactions."""

import logging

from discord import Interaction, app_commands
from discord.ext import commands

from mudd.formatting.entities import build_contents_string
from mudd.services.database import get_pool
from mudd.services.entity import ResolvedEntity, get_entity_service
from mudd.services.entity_matcher import (
    get_autocomplete_entities,
    match_entity_by_prefix,
)
from mudd.services.verb_action import VerbAction
from mudd.services.verb_matcher import match_verb
from mudd.services.visibility import get_visibility_service
from mudd.templating import TemplateRenderError, render

logger = logging.getLogger(__name__)


class Interact(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def target_autocomplete(
        self, interaction: Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete callback for target parameter.

        Suggests entity names from the current room, excluding entities
        inside containers with contents_visible=False.
        """
        try:
            visibility_service = get_visibility_service()
            await visibility_service.wait_for_startup()

            room = getattr(interaction.channel, "name", None)
            if not room:
                return []

            entity_service = get_entity_service()
            visible_entities = await get_autocomplete_entities(entity_service, room)

            # Filter by current input using word prefix matching
            if current:
                match_result = match_entity_by_prefix(current, visible_entities)
                matching = [m.instance for m in match_result.matches]
            else:
                matching = visible_entities

            # Return as choices (limit 25 per Discord)
            choices = [
                app_commands.Choice(name=e.entity.name, value=e.entity.name)
                for e in matching
            ]

            return choices[:25]
        except Exception:
            logger.exception(
                "Error in target autocomplete for room '%s'",
                getattr(interaction.channel, "name", "unknown"),
            )
            return []

    @app_commands.command(name="interact", description="Interact with an entity")
    @app_commands.describe(
        action="Action to perform (e.g., smash, touch, take)",
        target="Thing to interact with",
    )
    @app_commands.autocomplete(target=target_autocomplete)
    async def interact(self, interaction: Interaction, action: str, target: str):
        """Interact with an entity using a verb."""
        visibility_service = get_visibility_service()
        await visibility_service.wait_for_startup()

        room = getattr(interaction.channel, "name", None)
        if not room:
            await interaction.response.send_message(
                "You can't interact with anything here.", ephemeral=True
            )
            return

        entity_service = get_entity_service()
        # Uses get_room_entities (not get_autocomplete_entities) intentionally:
        # players can interact with hidden container contents if they know the name
        all_entities = await entity_service.get_room_entities(room)

        # Resolve target to entity
        match_result = match_entity_by_prefix(target, all_entities)

        if match_result.is_empty():
            await interaction.response.send_message(
                f"You don't see '{target}' here.", ephemeral=True
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

        pool = await get_pool()
        action_type = await match_verb(pool, action)

        if action_type is None:
            await interaction.response.send_message(
                "You can't do that.", ephemeral=True
            )
            return

        # Get handler text based on action
        handler_text = _get_handler_text(entity, action_type)

        if handler_text is None:
            await interaction.response.send_message("Nothing happens.", ephemeral=True)
            return

        # Fetch container contents for template (regardless of contents_visible)
        container_contents = await entity_service.get_container_contents(
            entity.id, room
        )
        contents_str = build_contents_string(container_contents)

        # Render template with entity context
        try:
            output = render(handler_text, entity, contents_str)
        except TemplateRenderError:
            logger.warning(
                "Template error rendering '%s' handler for entity '%s'",
                action_type.value,
                entity.id,
            )
            output = f"*{entity.name}* responds, but something went wrong."

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
    }
    return handler_map.get(action)


async def setup(bot: commands.Bot):
    await bot.add_cog(Interact(bot))
