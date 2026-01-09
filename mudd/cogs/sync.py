"""Periodic synchronization task for MUDD."""

import logging

from discord.ext import commands, tasks

from mudd.services.visibility import get_visibility_service

logger = logging.getLogger(__name__)


class Sync(commands.Cog):
    """Background task for periodic Discord permission synchronization."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.periodic_sync.start()

    def cog_unload(self):
        self.periodic_sync.cancel()

    @tasks.loop(minutes=15)
    async def periodic_sync(self):
        """Sync database state to Discord for all guilds every 15 minutes."""
        service = get_visibility_service()

        for guild in self.bot.guilds:
            logger.info(f"Starting periodic sync for guild: {guild.name}")
            try:
                stats = await service.sync_guild(guild)
                logger.info(f"Periodic sync complete for {guild.name}: {stats}")
            except Exception as e:
                logger.error(f"Periodic sync failed for guild {guild.name}: {e}")

    @periodic_sync.before_loop
    async def before_periodic_sync(self):
        """Wait for bot to be ready before starting sync."""
        await self.bot.wait_until_ready()
        logger.info("Periodic sync task starting")
