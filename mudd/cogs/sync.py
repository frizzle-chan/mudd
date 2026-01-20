"""Periodic synchronization task for MUDD.

This cog owns ALL sync operations: zones, rooms, and user permissions.
The first sync iteration handles startup initialization, subsequent iterations
perform full syncs every 15 minutes.
"""

import logging
import os
from typing import TYPE_CHECKING

import asyncpg
from discord.ext import commands, tasks

if TYPE_CHECKING:
    from main import MuddBot

from mudd.loaders.entity_loader import sync_entities
from mudd.loaders.verb_loader import sync_verbs
from mudd.loaders.zone_loader import sync_zones_and_rooms
from mudd.services.entity import EntityService
from mudd.services.player_context import PlayerContextService
from mudd.services.rendering import RenderingService
from mudd.services.visibility import VisibilityService

logger = logging.getLogger(__name__)


class Sync(commands.Cog):
    """Background task for periodic Discord synchronization.

    Responsibilities:
    - Zone/room sync: Create missing channels, fix topics, detect orphans
    - Visibility sync: Sync user permissions to match database state
    - Startup initialization: Mark VisibilityService ready on first sync
    - Orphan tracking: Only report NEW orphans to console (not previously seen)
    """

    bot: "MuddBot"

    def __init__(
        self,
        bot: "MuddBot",
        entity_service: EntityService,
        player_context: PlayerContextService,
        visibility_service: VisibilityService,
        pool: asyncpg.Pool,
        rendering_service: RenderingService,
    ) -> None:
        self.bot = bot
        self.entity_service = entity_service
        self.player_context = player_context
        self.visibility_service = visibility_service
        self._pool = pool
        self._rendering = rendering_service
        self._seen_orphans: set[tuple[int, str, str]] = set()
        self._console_channel = os.environ.get("MUDD_CONSOLE_CHANNEL", "console")
        self.periodic_sync.start()

    def cog_unload(self):
        self.periodic_sync.cancel()

    @tasks.loop(minutes=15)
    async def periodic_sync(self):
        """Full sync: zones, rooms, and permissions for all guilds.

        On first iteration:
        - Sync zones/rooms from rec files to database and Discord
        - Sync user permissions
        - Mark startup complete (unblocks commands)

        On subsequent iterations:
        - Full zone/room sync (recreates deleted channels, fixes topics)
        - Report only NEW orphan channels
        - Sync user permissions
        """
        pool = self._pool
        is_first_sync = not self.visibility_service.startup_complete

        if is_first_sync:
            await self._initial_sync(pool)
        else:
            await self._periodic_sync(pool)

    async def _initial_sync(self, pool) -> None:
        """First sync: sync all data and mark visibility service ready."""
        logger.info("Starting initial sync (first run)")

        # Sync verb word lists (no dependencies, can run first)
        try:
            await sync_verbs(pool)
        except Exception:
            logger.exception("Failed to sync verbs")
            raise

        # Access world_file from bot (set in main.py)
        world_file = self.bot.world_file

        for guild in self.bot.guilds:
            try:
                stats, _, orphans = await sync_zones_and_rooms(
                    pool, guild, world_file, self._console_channel, self._seen_orphans
                )
                logger.info(f"Initial zone sync for {guild.name}: {stats}")

                # Track all orphans from first sync
                self._seen_orphans.update(orphans)

            except Exception:
                logger.exception(f"Failed initial zone sync for {guild.name}")
                raise

        # Sync entity definitions and instances to database
        try:
            await sync_entities(pool, world_file)
            # Invalidate entity cache after sync
            self.entity_service.invalidate_cache()
            # Invalidate player context cache after entity sync
            self.player_context.invalidate_cache()
            # Clear template cache to ensure fresh templates
            self._rendering.clear_cache()
        except Exception:
            logger.exception("Failed to sync entities")
            raise

        # Prepopulate autocomplete cache for all rooms with entities
        try:
            await self._prepopulate_autocomplete_cache(pool)
        except Exception:
            logger.exception("Failed to prepopulate autocomplete cache")
            # Non-fatal: continue operation

        # Sync user permissions
        for guild in self.bot.guilds:
            try:
                stats = await self.visibility_service.sync_guild(guild)
                logger.info(f"Initial visibility sync for {guild.name}: {stats}")
            except Exception:
                logger.exception(f"Failed initial visibility sync for {guild.name}")
                raise

        # Mark startup complete - unblocks commands
        self.visibility_service.mark_startup_complete()
        logger.info("Initial sync complete - bot ready for commands")

    async def _periodic_sync(self, pool) -> None:
        """Subsequent syncs: full zone/room/permission sync."""
        # Wait for startup to complete (in case we're racing with initial sync)
        await self.visibility_service.wait_for_startup()

        # Sync verb word lists
        try:
            await sync_verbs(pool)
        except Exception:
            logger.exception("Failed to sync verbs")
            # Don't raise - allow continued operation

        # Access world_file from bot (set in main.py)
        world_file = self.bot.world_file

        for guild in self.bot.guilds:
            logger.info(f"Starting periodic sync for {guild.name}")
            try:
                # Zone/room sync (recreates deleted channels, fixes topics)
                stats, _, orphans = await sync_zones_and_rooms(
                    pool, guild, world_file, self._console_channel, self._seen_orphans
                )
                logger.info(f"Zone sync for {guild.name}: {stats}")

                # Track new orphans (reporting handled by zone_loader)
                self._seen_orphans.update(orphans)

                # Sync entity definitions and instances
                try:
                    await sync_entities(pool, world_file)
                    # Invalidate entity cache after sync
                    self.entity_service.invalidate_cache()
                    # Invalidate player context cache after entity sync
                    self.player_context.invalidate_cache()
                    # Clear template cache to ensure fresh templates
                    self._rendering.clear_cache()
                except Exception:
                    logger.exception("Failed to sync entities")
                    # Don't raise - allow continued operation

                # Prepopulate autocomplete cache for all rooms with entities
                try:
                    await self._prepopulate_autocomplete_cache(pool)
                except Exception:
                    logger.exception("Failed to prepopulate autocomplete cache")
                    # Non-fatal: continue operation

                # Permission sync
                perm_stats = await self.visibility_service.sync_guild(guild)
                logger.info(f"Permission sync for {guild.name}: {perm_stats}")

            except Exception:
                logger.exception(f"Periodic sync failed for {guild.name}")

    @periodic_sync.before_loop
    async def before_periodic_sync(self):
        """Wait for bot to be ready before starting sync."""
        await self.bot.wait_until_ready()
        logger.info("Sync task ready - starting first sync")

    async def _prepopulate_autocomplete_cache(self, pool) -> None:
        """Prepopulate autocomplete cache for all rooms with entities."""
        rows = await pool.fetch(
            "SELECT DISTINCT room FROM entity_instances WHERE room IS NOT NULL"
        )
        rooms = [row["room"] for row in rows]
        if rooms:
            count = await self.player_context.prepopulate_cache(rooms)
            logger.info(f"Prepopulated autocomplete cache for {count} rooms")
