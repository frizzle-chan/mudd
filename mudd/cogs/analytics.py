"""Analytics tracking for user progression."""

import logging

import discord
from discord import Interaction, app_commands
from discord.ext import commands

from mudd.services.analytics import get_message_count, increment_message_count

logger = logging.getLogger(__name__)


class Analytics(commands.Cog):
    """Track user analytics for progression."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Track message count for users."""
        # Ignore bot messages
        if message.author.bot:
            return

        # Ignore DMs
        if not message.guild:
            return

        try:
            new_count = await increment_message_count(message.author.id)
            logger.debug(f"User {message.author.id} message count: {new_count}")
        except Exception as e:
            logger.error(
                f"Failed to increment message count for {message.author.id}: {e}"
            )

    @app_commands.command(name="stats", description="View your statistics")
    async def stats(self, interaction: Interaction):
        """Display user statistics."""
        try:
            message_count = await get_message_count(interaction.user.id)
            await interaction.response.send_message(
                f"📊 **Your Stats**\nMessages sent: {message_count}", ephemeral=True
            )
        except Exception as e:
            logger.error(f"Failed to get stats for {interaction.user.id}: {e}")
            await interaction.response.send_message(
                "Failed to retrieve statistics. Please try again.", ephemeral=True
            )
