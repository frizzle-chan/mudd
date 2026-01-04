import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from mudd.cogs.look import Look
from mudd.cogs.movement import Movement
from mudd.cogs.ping import Ping
from mudd.services.valkey import close_valkey
from mudd.services.visibility import get_visibility_service, init_visibility_service

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.members = True


class MuddBot(commands.Bot):
    async def close(self):
        await close_valkey()
        await super().close()


bot = MuddBot(command_prefix="!", intents=intents)


@bot.event
async def setup_hook():
    init_visibility_service(
        world_category_id=int(os.environ["MUDD_WORLD_CATEGORY_ID"]),
        default_channel_id=int(os.environ["MUDD_DEFAULT_CHANNEL_ID"]),
    )

    await bot.add_cog(Look(bot))
    await bot.add_cog(Ping(bot))
    await bot.add_cog(Movement(bot))


@bot.event
async def on_ready():
    await bot.tree.sync()
    logger.info(f"Logged in as {bot.user}")

    service = get_visibility_service()
    for guild in bot.guilds:
        logger.info(f"Starting visibility sync for guild: {guild.name}")
        stats = await service.startup_sync(guild)
        logger.info(f"Sync complete for {guild.name}: {stats}")


bot.run(os.environ["DISCORD_TOKEN"])
