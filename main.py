import argparse
import logging
import os
from pathlib import Path

import discord
from dotenv import load_dotenv

from mudd.bot import MuddBot
from mudd.caches.entity_autocomplete import EntityAutocompleteCache
from mudd.caches.user import UserCache
from mudd.cogs.economy import Economy
from mudd.cogs.interact import Interact
from mudd.cogs.look import Look
from mudd.cogs.movement import Movement
from mudd.cogs.ping import Ping
from mudd.cogs.speech import Speech
from mudd.cogs.sync import Sync
from mudd.database import get_pool, init_database
from mudd.observers import RoomChannelCache

# Suppress PyNaCl warning since we don't use voice features
discord.VoiceClient.warn_nacl = False

load_dotenv()

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)

# Default world file for backwards compatibility
DEFAULT_WORLD = Path(__file__).parent / "data" / "worlds" / "mansion.rec"


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="MUDD Discord Bot")
    parser.add_argument(
        "--world",
        type=Path,
        default=DEFAULT_WORLD,
        help="Path to world .rec file (default: data/worlds/mansion.rec)",
    )
    return parser.parse_args()


intents = discord.Intents.default()
intents.members = True
# Enable message_content to suppress discord.py warning about prefix commands.
# This bot uses slash commands only, but discord.py requires this intent when
# a command_prefix is specified (even if not used).
intents.message_content = True

args = parse_args()
bot = MuddBot(world_file=args.world, command_prefix="!", intents=intents)


@bot.event
async def setup_hook():
    # Initialize database and run migrations
    await init_database()

    # Get database pool
    pool = await get_pool()

    # Create shared caches (rebuilt by Sync cog on startup)
    room_cache = RoomChannelCache(pool)
    autocomplete_cache = EntityAutocompleteCache()
    user_cache = UserCache()

    # Create cogs with explicit dependencies
    await bot.add_cog(Look(bot, pool, autocomplete_cache, user_cache))
    await bot.add_cog(Interact(bot, pool, autocomplete_cache, user_cache))
    await bot.add_cog(Ping(bot))
    await bot.add_cog(Movement(bot, pool, room_cache, user_cache))
    await bot.add_cog(Sync(bot, pool, room_cache, autocomplete_cache, user_cache))
    await bot.add_cog(Economy(bot, pool))
    await bot.add_cog(Speech(bot, pool, room_cache))


@bot.event
async def on_ready():
    # Sync cog handles zone/room sync and room cache initialization
    # on first periodic_sync iteration. This just syncs slash commands.
    await bot.tree.sync()
    logger.info(f"Logged in as {bot.user} (world: {bot.world_file})")


PID_FILE = Path("mudd.pid")
PID_FILE.write_text(str(os.getpid()))
bot.run(os.environ["DISCORD_TOKEN"])
