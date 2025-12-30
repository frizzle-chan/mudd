from discord import Interaction, app_commands
from discord.ext import commands


class Ping(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Check bot latency")
    async def ping(self, interaction: Interaction):
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"Pong! {latency}ms")
