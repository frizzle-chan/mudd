from discord import Interaction, app_commands
from discord.ext import commands

from mudd.services.visibility import get_visibility_service


class Look(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="look", description="View surroundings")
    async def look(self, interaction: Interaction):
        service = get_visibility_service()
        await service.wait_for_startup()

        topic = getattr(interaction.channel, "topic", None)
        if topic:
            await interaction.response.send_message(topic, ephemeral=True)
        else:
            await interaction.response.send_message("No topic set", ephemeral=True)
