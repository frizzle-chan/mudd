from discord import Interaction, app_commands
from discord.ext import commands

from mudd.formatting.entities import format_room_entities
from mudd.services.entity import get_entity_service
from mudd.services.visibility import get_visibility_service


class Look(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="look", description="View surroundings")
    async def look(self, interaction: Interaction):
        visibility_service = get_visibility_service()
        await visibility_service.wait_for_startup()

        # Get room description from channel topic
        topic = getattr(interaction.channel, "topic", None)
        room_description = topic or "You see nothing special."

        # Get room name (channel name = room ID)
        room = getattr(interaction.channel, "name", None)

        # Format entities if room is known
        entity_text = ""
        if room:
            entity_service = get_entity_service()
            entities = await entity_service.get_top_level_room_entities(room)
            entity_text = await format_room_entities(entities, entity_service, room)

        # Combine room description and entities
        if entity_text:
            message = f"{room_description}\n\n{entity_text}"
        else:
            message = room_description

        await interaction.response.send_message(message, ephemeral=True)
