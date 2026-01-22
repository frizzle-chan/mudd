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
from mudd.database import close_pool, get_pool, init_database
from mudd.services.entity import EntityService
from mudd.services.focus_context import FocusContextService
from mudd.services.inventory import InventoryService
from mudd.services.player_context import PlayerContextService
from mudd.services.rendering import RenderingService
from mudd.services.visibility import VisibilityService

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

    # Get database pool
    pool = await get_pool()

    # Create services with explicit dependencies
    entity_service = EntityService(pool)
    focus_service = FocusContextService(pool)
    player_context = PlayerContextService(entity_service, focus_service)
    visibility_service = VisibilityService(pool)
    rendering_service = RenderingService()
    inventory_service = InventoryService(pool, entity_service)

    # Create cogs with explicit dependencies
    await bot.add_cog(
        Interact(
            bot,
            entity_service,
            player_context,
            visibility_service,
            inventory_service,
            pool,
            rendering_service,
        )
    )
    await bot.add_cog(
        Look(bot, entity_service, player_context, visibility_service, rendering_service)
    )
    await bot.add_cog(Ping(bot))
    await bot.add_cog(
        Movement(bot, visibility_service, player_context, inventory_service)
    )
    await bot.add_cog(
        Sync(
            bot,
            entity_service,
            player_context,
            visibility_service,
            pool,
            rendering_service,
            inventory_service,
        )
    )


@bot.event
async def on_ready():
    # Sync cog handles zone/room sync and visibility service initialization
    # on first periodic_sync iteration. This just syncs slash commands.
    await bot.tree.sync()
    logger.info(f"Logged in as {bot.user} (world: {bot.world_file})")


bot.run(os.environ["DISCORD_TOKEN"])
