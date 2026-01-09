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
from mudd.services.visibility import get_visibility_service, init_visibility_service
from mudd.services.zone_loader import sync_zones_and_rooms

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

    # Visibility service initialized in on_ready after zone sync discovers default room

    await bot.add_cog(Look(bot))
    await bot.add_cog(Ping(bot))
    await bot.add_cog(Movement(bot))
    await bot.add_cog(Sync(bot))


@bot.event
async def on_ready():
    # Sync zones and rooms from rec files to database and Discord
    # This must happen after bot is ready since we need guild access
    pool = await get_pool()
    console_channel = os.environ.get("MUDD_CONSOLE_CHANNEL", "console")

    # Sync zones/rooms and discover default room from rec files
    default_room: str | None = None
    for guild in bot.guilds:
        try:
            stats, discovered_room = await sync_zones_and_rooms(
                pool, guild, console_channel
            )
            logger.info(f"Zone sync for {guild.name}: {stats}")
            # Get default room from first successful sync
            if default_room is None and discovered_room:
                default_room = discovered_room
        except Exception:
            logger.exception(f"Failed to sync zones for guild {guild.name}")
            raise

    if not default_room:
        logger.error("No guilds found or no default room defined - cannot start")
        return

    # Initialize visibility service with discovered default room
    init_visibility_service(default_room=default_room)

    # Build room cache and sync user permissions after zone sync
    # This ensures the visibility service has up-to-date channel mappings
    service = get_visibility_service()
    for guild in bot.guilds:
        try:
            stats = await service.sync_guild(guild)
            logger.info(f"Visibility sync for {guild.name}: {stats}")
        except Exception:
            logger.exception(f"Failed to sync visibility for guild {guild.name}")
            raise

    service.mark_startup_complete()

    await bot.tree.sync()
    logger.info(f"Logged in as {bot.user}")


bot.run(os.environ["DISCORD_TOKEN"])
