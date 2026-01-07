import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from mudd.cogs.look import Look
from mudd.cogs.movement import Movement
from mudd.cogs.ping import Ping
from mudd.cogs.sync import Sync
from mudd.services.database import close_pool, get_pool, init_database
from mudd.services.verb_loader import sync_verbs
from mudd.services.visibility import init_visibility_service

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.members = True


class MuddBot(commands.Bot):
    async def close(self):
        await close_pool()
        await super().close()


bot = MuddBot(command_prefix="!", intents=intents)


@bot.event
async def setup_hook():
    # Initialize database and run migrations
    await init_database()

    # Sync verb word lists to database
    pool = await get_pool()
    try:
        await sync_verbs(pool)
    except Exception:
        logger.exception("Failed to sync verbs - bot may not recognize verb commands")
        raise

    init_visibility_service(
        world_category_id=int(os.environ["MUDD_WORLD_CATEGORY_ID"]),
        default_channel_id=int(os.environ["MUDD_DEFAULT_CHANNEL_ID"]),
    )

    await bot.add_cog(Look(bot))
    await bot.add_cog(Ping(bot))
    await bot.add_cog(Movement(bot))
    await bot.add_cog(Sync(bot))


@bot.event
async def on_ready():
    await bot.tree.sync()
    logger.info(f"Logged in as {bot.user}")


bot.run(os.environ["DISCORD_TOKEN"])
