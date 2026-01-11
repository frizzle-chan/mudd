"""Periodic synchronization task for MUDD.

This cog owns ALL sync operations: zones, rooms, and user permissions.
The first sync iteration handles startup initialization, subsequent iterations
perform full syncs every 15 minutes.
"""

import logging
import os

from discord.ext import commands, tasks

from mudd.services.database import get_pool
from mudd.services.visibility import (
    get_visibility_service,
    init_visibility_service,
    is_visibility_service_initialized,
)
from mudd.services.zone_loader import sync_zones_and_rooms

logger = logging.getLogger(__name__)


class Sync(commands.Cog):
    """Background task for periodic Discord synchronization.

    Responsibilities:
    - Zone/room sync: Create missing channels, fix topics, detect orphans
    - Visibility sync: Sync user permissions to match database state
    - Startup initialization: Initialize VisibilityService on first sync
    - Orphan tracking: Only report NEW orphans to console (not previously seen)
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._seen_orphans: set[tuple[str, str]] = set()
        self._console_channel = os.environ.get("MUDD_CONSOLE_CHANNEL", "console")
        self.periodic_sync.start()

    def cog_unload(self):
        self.periodic_sync.cancel()

    @tasks.loop(minutes=15)
    async def periodic_sync(self):
        """Full sync: zones, rooms, and permissions for all guilds.

        On first iteration:
        - Sync zones/rooms from rec files to database and Discord
        - Discover default room and initialize VisibilityService
        - Sync user permissions
        - Mark startup complete (unblocks commands)

        On subsequent iterations:
        - Full zone/room sync (recreates deleted channels, fixes topics)
        - Report only NEW orphan channels
        - Sync user permissions
        """
        pool = await get_pool()
        is_first_sync = not is_visibility_service_initialized()

        if is_first_sync:
            await self._initial_sync(pool)
        else:
            await self._periodic_sync(pool)

    async def _initial_sync(self, pool) -> None:
        """First sync: initialize visibility service and sync all data."""
        logger.info("Starting initial sync (first run)")

        default_room: str | None = None

        for guild in self.bot.guilds:
            try:
                stats, discovered_room, orphans = await sync_zones_and_rooms(
                    pool, guild, self._console_channel, self._seen_orphans
                )
                logger.info(f"Initial zone sync for {guild.name}: {stats}")

                # Get default room from first successful sync
                if default_room is None and discovered_room:
                    default_room = discovered_room

                # Track all orphans from first sync
                self._seen_orphans.update(orphans)

            except Exception:
                logger.exception(f"Failed initial zone sync for {guild.name}")
                raise

        if not default_room:
            raise RuntimeError(
                "No guilds found or no default room defined - cannot start"
            )

        # Initialize visibility service with discovered default room
        init_visibility_service(default_room=default_room)
        service = get_visibility_service()

        # Sync user permissions
        for guild in self.bot.guilds:
            try:
                stats = await service.sync_guild(guild)
                logger.info(f"Initial visibility sync for {guild.name}: {stats}")
            except Exception:
                logger.exception(f"Failed initial visibility sync for {guild.name}")
                raise

        # Mark startup complete - unblocks commands
        service.mark_startup_complete()
        logger.info("Initial sync complete - bot ready for commands")

    async def _periodic_sync(self, pool) -> None:
        """Subsequent syncs: full zone/room/permission sync."""
        service = get_visibility_service()

        # Wait for startup to complete (in case we're racing with initial sync)
        await service.wait_for_startup()

        for guild in self.bot.guilds:
            logger.info(f"Starting periodic sync for {guild.name}")
            try:
                # Zone/room sync (recreates deleted channels, fixes topics)
                stats, _, orphans = await sync_zones_and_rooms(
                    pool, guild, self._console_channel, self._seen_orphans
                )
                logger.info(f"Zone sync for {guild.name}: {stats}")

                # Track new orphans (reporting handled by zone_loader)
                self._seen_orphans.update(orphans)

                # Permission sync
                perm_stats = await service.sync_guild(guild)
                logger.info(f"Permission sync for {guild.name}: {perm_stats}")

            except Exception as e:
                logger.error(f"Periodic sync failed for {guild.name}: {e}")

    @periodic_sync.before_loop
    async def before_periodic_sync(self):
        """Wait for bot to be ready before starting sync."""
        await self.bot.wait_until_ready()
        logger.info("Sync task ready - starting first sync")
