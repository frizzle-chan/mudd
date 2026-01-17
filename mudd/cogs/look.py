"""Look command for viewing surroundings and examining entities."""

import logging

from discord import Interaction, app_commands
from discord.ext import commands

from mudd.formatting.entities import format_room_entities, render_entity_on_look
from mudd.services.entity import get_entity_service
from mudd.services.entity_matcher import (
    get_focus_aware_autocomplete_entities,
    match_entity_by_prefix,
)
from mudd.services.focus_context import get_focus_context_service
from mudd.services.visibility import get_visibility_service

logger = logging.getLogger(__name__)


class Look(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def at_autocomplete(
        self, interaction: Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete callback for at parameter.

        Suggests entity names from the current room, excluding entities
        inside containers with contents_visible=False. When a user has an
        active focus (open container), prioritizes focused contents with
        "[Container Name]" prefix.
        """
        try:
            visibility_service = get_visibility_service()
            await visibility_service.wait_for_startup()

            room = getattr(interaction.channel, "name", None)
            if not room:
                return []

            entity_service = get_entity_service()
            focus_service = get_focus_context_service()

            # Get focus-aware autocomplete choices
            choices = await get_focus_aware_autocomplete_entities(
                entity_service, focus_service, interaction.user.id, room
            )

            # Filter by current input using word prefix matching
            if current:
                # Get matching instances
                instances = [c.instance for c in choices]
                match_result = match_entity_by_prefix(current, instances)
                matched_ids = {m.instance.entity.id for m in match_result.matches}
                # Filter choices to matched entities only
                choices = [c for c in choices if c.instance.entity.id in matched_ids]

            # Reserve slots for room entities when focused
            # This ensures room entities are visible as escape options
            focused_items = [c for c in choices if c.is_focused]
            room_items = [c for c in choices if not c.is_focused]

            if len(focused_items) > 20 and len(room_items) > 0:
                # Truncate focused items to show some room entities
                max_focused = 24 - min(len(room_items), 4)  # Leave up to 4 slots
                focused_items = focused_items[:max_focused]
                choices = focused_items + room_items

            # Return as choices (limit 25 per Discord)
            result = [
                app_commands.Choice(
                    name=c.display_name,
                    value=c.instance.entity.name,  # Use actual name for matching
                )
                for c in choices
            ]

            # Get focus to determine Room option display
            focus = await focus_service.get_focus(interaction.user.id, room)
            room_display = f"[Close {focus.entity_name}] Room" if focus else "Room"

            # Add "Room" option at top if it matches current input
            if not current or "room".startswith(current.lower()):
                room_choice = app_commands.Choice(name=room_display, value="Room")
                return [room_choice] + result[:24]

            return result[:25]
        except Exception:
            logger.exception(
                "Error in at autocomplete for room '%s'",
                getattr(interaction.channel, "name", "unknown"),
            )
            return []

    @app_commands.command(name="look", description="View surroundings or examine item")
    @app_commands.describe(at="Thing to examine")
    @app_commands.autocomplete(at=at_autocomplete)
    async def look(self, interaction: Interaction, at: str):
        """Look at room or specific entity."""
        visibility_service = get_visibility_service()
        await visibility_service.wait_for_startup()

        room = getattr(interaction.channel, "name", None)

        if not at or at == "Room":
            # Clear focus when explicitly selecting "Room" from autocomplete
            # This is the escape mechanism per user request
            if at == "Room":
                focus_service = get_focus_context_service()
                await focus_service.clear_focus(
                    interaction.user.id, reason="interaction"
                )

            # Show room description + top-level entities
            topic = getattr(interaction.channel, "topic", None)
            room_description = topic or "You see nothing special."

            entity_text = ""
            if room:
                entity_service = get_entity_service()
                entities = await entity_service.get_top_level_room_entities(room)
                entity_text = await format_room_entities(entities, entity_service, room)

            if entity_text:
                message = f"{room_description}\n\n{entity_text}"
            else:
                message = room_description

            await interaction.response.send_message(message, ephemeral=True)
        else:
            # Look at specific entity
            if not room:
                await interaction.response.send_message(
                    "You can't look at anything here.", ephemeral=True
                )
                return

            entity_service = get_entity_service()
            focus_service = get_focus_context_service()
            user_id = interaction.user.id

            all_entities = await entity_service.get_room_entities(room)

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
                is_in_focus = await focus_service.is_entity_in_focus(
                    user_id, room, entity.id
                )

                # Clear focus if looking at unrelated entity
                # (per ADR 0003: "focus follows attention")
                if not is_in_focus:
                    await focus_service.clear_focus(user_id, reason="interaction")
                else:
                    # Update timestamp to prevent timeout
                    await focus_service.update_focus_timestamp(user_id)

                # Render on_look template
                detail_text = await render_entity_on_look(
                    matched_instance, entity_service, room
                )
                await interaction.response.send_message(detail_text, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Look(bot))
