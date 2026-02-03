import argparse
import logging
import os
from pathlib import Path

import discord
from dotenv import load_dotenv

from mudd.bot import MuddBot
from mudd.cogs.economy import Economy
from mudd.cogs.interact import Interact
from mudd.cogs.look import Look
from mudd.cogs.movement import Movement
from mudd.cogs.ping import Ping
from mudd.cogs.sync import Sync
from mudd.database import get_pool, init_database
from mudd.services.currency import CurrencyService
from mudd.services.entity import EntityService
from mudd.services.entity_resolution import EntityResolutionService
from mudd.services.focus_context import FocusContextService
from mudd.services.inventory import InventoryService
from mudd.services.rendering import RenderingService
from mudd.services.visibility import VisibilityService

# Suppress PyNaCl warning since we don't use voice features
discord.VoiceClient.warn_nacl = False

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

    # Create services with explicit dependencies
    entity_service = EntityService(pool)
    focus_service = FocusContextService(pool)
    visibility_service = VisibilityService(pool)
    rendering_service = RenderingService()
    inventory_service = InventoryService(pool, entity_service, rendering_service)
    currency_service = CurrencyService(pool)
    entity_resolution = EntityResolutionService(
        entity_service, focus_service, inventory_service, pool
    )

    # Create cogs with explicit dependencies
    await bot.add_cog(Look(bot, pool))
    await bot.add_cog(Interact(bot, pool))
    await bot.add_cog(Ping(bot))
    await bot.add_cog(
        Movement(bot, visibility_service, entity_resolution, inventory_service)
    )
    await bot.add_cog(
        Sync(
            bot,
            visibility_service,
            pool,
        )
    )
    await bot.add_cog(
        Economy(
            bot,
            currency_service,
            visibility_service,
            inventory_service,
            entity_service,
            rendering_service,
            pool,
        )
    )


@bot.event
async def on_ready():
    # Sync cog handles zone/room sync and visibility service initialization
    # on first periodic_sync iteration. This just syncs slash commands.
    await bot.tree.sync()
    logger.info(f"Logged in as {bot.user} (world: {bot.world_file})")


bot.run(os.environ["DISCORD_TOKEN"])
