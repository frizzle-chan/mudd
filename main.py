import argparse
import logging
import os
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

from mudd.cogs.interact import Interact
from mudd.cogs.look import Look
from mudd.cogs.movement import Movement
from mudd.cogs.ping import Ping
from mudd.cogs.sync import Sync
from mudd.services.database import close_pool, init_database
from mudd.services.entity import init_entity_service
from mudd.services.focus_context import init_focus_context_service

load_dotenv()

logging.basicConfig(level=logging.INFO)
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


class MuddBot(commands.Bot):
    """MUDD Discord bot with world file configuration."""

    def __init__(self, world_file: Path, **kwargs):
        super().__init__(**kwargs)
        self.world_file = world_file

    async def close(self):
        await close_pool()
        await super().close()


args = parse_args()
bot = MuddBot(world_file=args.world, command_prefix="!", intents=intents)


@bot.event
async def setup_hook():
    # Initialize database and run migrations
    await init_database()

    # Initialize entity service for runtime lookups
    init_entity_service()

    # Initialize focus context service for modal interactions
    init_focus_context_service()

    # Zone/room sync and visibility service initialization handled by Sync cog
    # on first periodic_sync iteration (after bot is ready)

    await bot.add_cog(Interact(bot))
    await bot.add_cog(Look(bot))
    await bot.add_cog(Ping(bot))
    await bot.add_cog(Movement(bot))
    await bot.add_cog(Sync(bot))


@bot.event
async def on_ready():
    # Sync cog handles zone/room sync and visibility service initialization
    # on first periodic_sync iteration. This just syncs slash commands.
    await bot.tree.sync()
    logger.info(f"Logged in as {bot.user} (world: {bot.world_file})")


bot.run(os.environ["DISCORD_TOKEN"])
