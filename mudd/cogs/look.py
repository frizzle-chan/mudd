"""Look command for viewing surroundings and examining entities."""

import logging
from typing import TYPE_CHECKING

import asyncpg
from discord import Interaction, app_commands
from discord.ext import commands

from mudd.formatting.entities import format_room_entities, render_entity_on_look
from mudd.services.entity_matcher import (
    get_focus_aware_autocomplete_entities,
    match_entity_by_prefix,
)
from mudd.templating import TemplateRenderError, render

if TYPE_CHECKING:
    from mudd.services.entity import EntityService
    from mudd.services.focus_context import FocusContextService
    from mudd.services.visibility_protocol import VisibilityServiceProtocol

logger = logging.getLogger(__name__)


class Look(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot | None,
        entity_service: "EntityService",
        focus_service: "FocusContextService",
        visibility_service: "VisibilityServiceProtocol",
    ) -> None:
        self.bot = bot
        self.entity_service = entity_service
        self.focus_service = focus_service
        self.visibility_service = visibility_service

    async def at_autocomplete(
        self, interaction: Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete callback for at parameter.

        Suggests entity names from the current room, excluding entities
        inside containers with contents_visible=False. When a user has an
        active focus (open container), shows only the focused contents with
        a "[Close {container}] Room" escape option at the top.
        """
        try:
            await self.visibility_service.wait_for_startup()

            room = getattr(interaction.channel, "name", None)
            if not room:
                return []

            # Get focus-aware autocomplete choices
            choices = await get_focus_aware_autocomplete_entities(
                self.entity_service, self.focus_service, interaction.user.id, room
            )

            # Filter by current input using word prefix matching
            if current:
                # Get matching instances
                instances = [c.instance for c in choices]
                match_result = match_entity_by_prefix(current, instances)
                matched_ids = {m.instance.entity.id for m in match_result.matches}
                # Filter choices to matched entities only
                choices = [c for c in choices if c.instance.entity.id in matched_ids]

            # When focused, only show container contents (not room entities)
            focused_items = [c for c in choices if c.is_focused]
            if focused_items:
                choices = focused_items

            # Return as choices (limit 25 per Discord)
            result = [
                app_commands.Choice(
                    name=c.display_name,
                    value=c.instance.entity.name,  # Use actual name for matching
                )
                for c in choices
            ]

            # Get focus to determine Room option display
            focus = await self.focus_service.get_focus(interaction.user.id, room)
            room_display = f"[Close {focus.entity_name}] Room" if focus else "Room"

            # Add "Room" option at top if it matches current input
            if not current or "room".startswith(current.lower()):
                room_choice = app_commands.Choice(name=room_display, value="Room")
                return [room_choice] + result[:24]

            return result[:25]
        except asyncpg.PostgresError:
            logger.exception(
                "Database error in at autocomplete for room '%s'",
                getattr(interaction.channel, "name", "unknown"),
            )
            return []

    @app_commands.command(name="look", description="View surroundings or examine item")
    @app_commands.describe(at="Thing to examine")
    @app_commands.autocomplete(at=at_autocomplete)
    async def look(self, interaction: Interaction, at: str):
        """Look at room or specific entity."""
        await self.visibility_service.wait_for_startup()

        room = getattr(interaction.channel, "name", None)

        if not at or at == "Room":
            # Clear focus when explicitly selecting "Room" from autocomplete
            # This is the escape mechanism per user request
            close_msg = None
            if at == "Room":
                # Get focus to capture entity before clearing (for template rendering)
                if room:
                    focus = await self.focus_service.get_focus(
                        interaction.user.id, room
                    )
                    focused_entity = None
                    if focus:
                        focused_entity = await self.entity_service.get_entity(
                            focus.entity_id
                        )

                    # Clear focus with "close" reason to get on_close template
                    close_template = await self.focus_service.clear_focus(
                        interaction.user.id, reason="close"
                    )

                    # Render close message if we have template and entity
                    if close_template and focused_entity:
                        try:
                            close_msg = render(close_template, focused_entity, "")
                        except TemplateRenderError:
                            logger.warning(
                                "Template error rendering on_close for entity '%s'",
                                focused_entity.id,
                                exc_info=True,
                            )
                            entity_name = focused_entity.name
                            close_msg = f"You step away from the *{entity_name}*."
                else:
                    await self.focus_service.clear_focus(
                        interaction.user.id, reason="close"
                    )

            # Show room description + top-level entities
            room_name = (
                await self.visibility_service.get_room_name(room) if room else None
            )
            topic = getattr(interaction.channel, "topic", None)
            room_description = topic or "You see nothing special."

            entity_text = ""
            if room:
                entities = await self.entity_service.get_top_level_room_entities(room)
                entity_text = await format_room_entities(
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
        else:
            # Look at specific entity
            if not room:
                await interaction.response.send_message(
                    "You can't look at anything here.", ephemeral=True
                )
                return

            user_id = interaction.user.id

            all_entities = await self.entity_service.get_room_entities(room)

            match_result = match_entity_by_prefix(at, all_entities)

            if match_result.is_empty():
                # No match - show room description
                topic = getattr(interaction.channel, "topic", None)
                room_description = topic or "You see nothing special."
                await interaction.response.send_message(
                    f"You don't see '{at}' here.\n\n{room_description}",
                    ephemeral=True,
                )
            elif match_result.is_ambiguous():
                # Disambiguation prompt
                names = [m.instance.entity.name for m in match_result.matches]
                names_list = ", ".join(f"*{name}*" for name in names)
                await interaction.response.send_message(
                    f"Which one? {names_list}", ephemeral=True
                )
            else:
                # Unique match: check if should clear focus
                matched_instance = match_result.matches[0].instance
                entity = matched_instance.entity

                # Check if looking at entity that is NOT in current focus
                is_in_focus = await self.focus_service.is_entity_in_focus(
                    user_id, room, entity.id
                )

                # Clear focus if looking at unrelated entity
                # (per ADR 0003: "focus follows attention")
                if not is_in_focus:
                    await self.focus_service.clear_focus(user_id, reason="interaction")
                else:
                    # Update timestamp to prevent timeout
                    await self.focus_service.update_focus_timestamp(user_id)

                # Render on_look template
                detail_text = await render_entity_on_look(
                    matched_instance, self.entity_service, room
                )
                await interaction.response.send_message(detail_text, ephemeral=True)
