from discord import Interaction, app_commands
from discord.ext import commands


class Look(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="look", description="View surroundings")
    async def look(self, interaction: Interaction):
        topic = getattr(interaction.channel, "topic", None)
        if topic:
            await interaction.response.send_message(topic)
        else:
            await interaction.response.send_message("No topic set")
