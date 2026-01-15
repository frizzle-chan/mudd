from discord import Interaction, app_commands
from discord.ext import commands

from mudd.formatting.entities import format_room_entities, render_entity_on_look
from mudd.services.entity import get_entity_service
from mudd.services.entity_matcher import (
    get_autocomplete_entities,
    match_entity_by_prefix,
)
from mudd.services.visibility import get_visibility_service


class Look(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def at_autocomplete(
        self, interaction: Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete callback for at parameter.

        Suggests entity names from the current room, excluding entities
        inside containers with contents_visible=False.
        """
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

        # Add "Room" option at top if it matches current input
        if not current or "room".startswith(current.lower()):
            room_choice = app_commands.Choice(name="Room", value="Room")
            return [room_choice] + choices[:24]

        return choices[:25]

    @app_commands.command(name="look", description="View surroundings or examine item")
    @app_commands.describe(at="Thing to examine (optional)")
    @app_commands.autocomplete(at=at_autocomplete)
    async def look(self, interaction: Interaction, at: str | None = None):
        """Look at room or specific entity."""
        visibility_service = get_visibility_service()
        await visibility_service.wait_for_startup()

        room = getattr(interaction.channel, "name", None)

        if at is None or at == "Room":
            # Original behavior: show room description + top-level entities
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
            # New behavior: look at specific entity
            if not room:
                await interaction.response.send_message(
                    "You can't look at anything here.", ephemeral=True
                )
                return

            entity_service = get_entity_service()
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
                # Unique match: render on_look template
                matched_instance = match_result.matches[0].instance
                detail_text = await render_entity_on_look(
                    matched_instance, entity_service, room
                )
                await interaction.response.send_message(detail_text, ephemeral=True)
