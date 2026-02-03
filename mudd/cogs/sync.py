"""Periodic synchronization task for MUDD.

This cog owns ALL sync operations: zones, rooms, and user permissions.
The first sync iteration handles startup initialization, subsequent iterations
perform full syncs every 15 minutes.
"""

import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import asyncpg
from discord.ext import commands, tasks

if TYPE_CHECKING:
    from main import MuddBot

from mudd.events import InventorySyncEvent, OrphanChannelDetectedEvent
from mudd.loaders.entity_loader import sync_entities
from mudd.loaders.verb_loader import sync_verbs
from mudd.loaders.zone_loader import (
    ZoneData,
    get_default_room,
    load_rooms_from_rec,
    load_zones_from_rec,
)
from mudd.models import Room, Zone
from mudd.observers.discord import DiscordReconciler
from mudd.services.visibility import VisibilityService

logger = logging.getLogger(__name__)


class Sync(commands.Cog):
    """Background task for periodic Discord synchronization.

    Responsibilities:
    - Zone/room sync: Create missing channels, fix topics, detect orphans
    - Visibility sync: Sync user permissions to match database state
    - Orphan tracking: Only report NEW orphans to console (not previously seen)
    """

    bot: "MuddBot"

    def __init__(
        self,
        bot: "MuddBot",
        visibility_service: VisibilityService,
        pool: asyncpg.Pool,
    ) -> None:
        self.bot = bot
        self.visibility_service = visibility_service
        self._pool = pool
        self._seen_orphans: set[tuple[int, str, str]] = set()
        self._console_channel = os.environ.get("MUDD_CONSOLE_CHANNEL", "console")
        self._first_sync_done = False
        self.periodic_sync.start()
        self.respawn_task.start()

    def cog_unload(self):
        self.periodic_sync.cancel()
        self.respawn_task.cancel()

    @tasks.loop(minutes=15)
    async def periodic_sync(self):
        """Full sync: zones, rooms, and permissions for all guilds.

        On first iteration:
        - Sync zones/rooms from rec files to database and Discord
        - Sync user permissions

        On subsequent iterations:
        - Full zone/room sync (recreates deleted channels, fixes topics)
        - Report only NEW orphan channels
        - Sync user permissions
        """
        pool = self._pool
        is_first = not self._first_sync_done
        await self._sync(pool, fail_fast=is_first)
        self._first_sync_done = True

    async def _sync(self, pool, *, fail_fast: bool) -> None:
        """Sync all data.

        Args:
            pool: Database connection pool
            fail_fast: If True, raise on critical errors. If False, log and continue.
        """
        if fail_fast:
            logger.info("Starting initial sync (first run)")

        # Sync verb word lists (global)
        try:
            await sync_verbs(pool)
        except Exception:
            logger.exception("Failed to sync verbs")
            if fail_fast:
                raise

        world_file = self.bot.world_file

        # Load zones/rooms from rec file
        zones = load_zones_from_rec(world_file)
        rooms = load_rooms_from_rec(world_file)

        if not zones or not rooms:
            logger.warning("No zones or rooms found - skipping sync")
            return

        default_room = get_default_room(rooms)

        # Create reconciler for Discord operations
        reconciler = DiscordReconciler(
            self.bot, pool, console_channel=self._console_channel
        )
        # Transfer seen orphans to reconciler
        reconciler._seen_orphans = self._seen_orphans

        # Sync zones to DB via model (emits ZoneSyncedEvent)
        try:
            zone_stats = await Zone.sync_all(pool, zones, observers=(reconciler,))
            logger.info(
                f"Zone sync: {zone_stats.synced} synced, {zone_stats.deleted} deleted"
            )
        except Exception:
            logger.exception("Failed to sync zones to database")
            if fail_fast:
                raise

        # Sync rooms to DB via model (emits RoomSyncedEvent)
        try:
            room_stats = await Room.sync_all(
                pool, rooms, default_room, observers=(reconciler,)
            )
            logger.info(
                f"Room sync: {room_stats.synced} synced, {room_stats.deleted} deleted, "
                f"{room_stats.users_relocated} users relocated"
            )
        except Exception:
            logger.exception("Failed to sync rooms to database")
            if fail_fast:
                raise

        # Sync entity definitions and instances (global, once per sync)
        try:
            await sync_entities(pool, world_file)
        except Exception:
            logger.exception("Failed to sync entities")
            if fail_fast:
                raise

        # Flush reconciler to sync Discord state (idempotent)
        try:
            await reconciler.flush()
        except Exception:
            logger.exception("Failed to flush Discord reconciler")
            if fail_fast:
                raise

        # Detect orphans and emit events
        room_ids = {r.id for r in rooms}
        self._detect_orphan_channels(zones, room_ids, reconciler)

        # Flush orphan notifications
        try:
            await reconciler.flush()
        except Exception:
            logger.exception("Failed to report orphans")

        # Update seen orphans from reconciler
        self._seen_orphans = reconciler._seen_orphans

        for guild in self.bot.guilds:
            logger.info(f"Starting remaining sync for {guild.name}")
            try:
                # Visibility sync
                vis_stats = await self.visibility_service.sync_guild(guild)
                logger.info(f"Visibility sync for {guild.name}: {vis_stats}")
            except Exception:
                logger.exception(f"Failed visibility sync for {guild.name}")
                if fail_fast:
                    raise

            # Inventory sync via unified event (forums, wallets, threads, descriptions)
            # Reset stats before sync
            reconciler.reset_inventory_forum_stats()
            member_count = 0
            for member in guild.members:
                if not member.bot:
                    member_count += 1
                    reconciler.notify(
                        InventorySyncEvent(guild_id=guild.id, user_id=member.id)
                    )

            try:
                await reconciler.flush()
                inv_stats = reconciler.get_inventory_forum_stats()
                logger.info(
                    f"Inventory sync for {guild.name}: "
                    f"{member_count} users, {inv_stats}"
                )
            except Exception:
                logger.exception(f"Failed inventory sync for {guild.name}")

        if fail_fast:
            logger.info("Initial sync complete")

    @periodic_sync.before_loop
    async def before_periodic_sync(self):
        """Wait for bot to be ready before starting sync."""
        await self.bot.wait_until_ready()
        logger.info("Sync task ready - starting first sync")

    @periodic_sync.error
    async def on_periodic_sync_error(self, error: BaseException) -> None:
        """Handle periodic sync errors."""
        logger.exception("Periodic sync failed", exc_info=error)
        if not self._first_sync_done:
            logger.critical("Initial sync failed - shutting down")
            await self.bot.close()

    @tasks.loop(minutes=1)
    async def respawn_task(self):
        """Process spawning pools for item respawns.

        Runs every minute. For each pool:
        1. Check current instance count vs max_count
        2. Check if respawn_interval has elapsed
        3. If spawning needed, select weighted random entity by tag
        4. Create instance with spawning_pool_id
        """
        # Skip respawns until the initial sync has completed
        if not self._first_sync_done:
            return

        try:
            await self._process_spawning_pools()
        except Exception:
            logger.exception("Failed to process spawning pools")

    @respawn_task.before_loop
    async def before_respawn_task(self):
        """Wait for bot to be ready before starting respawn task."""
        await self.bot.wait_until_ready()

    async def _process_spawning_pools(self) -> None:
        """Process spawning pools using MVC pattern."""
        from mudd.models.spawning_pool import SpawningPool

        now = datetime.now(UTC)

        pools = await SpawningPool.get_all_with_counts(self._pool)

        spawned = 0
        for sp in pools:
            instance = await sp.try_spawn(now)

            if instance is not None:
                spawned += 1
                logger.debug(
                    "Spawned '%s' in room '%s' from pool '%s'",
                    instance.entity.name,
                    sp.room,
                    sp.id,
                )

        if spawned > 0:
            logger.info(f"Spawned {spawned} items from spawning pools")

    def _detect_orphan_channels(
        self,
        zones: list[ZoneData],
        room_ids: set[str],
        reconciler: DiscordReconciler,
    ) -> None:
        """Detect orphan channels and emit events.

        Scans all guilds for channels in zone categories that don't
        correspond to known room IDs.

        Args:
            zones: List of zones to check
            room_ids: Set of valid room IDs
            reconciler: DiscordReconciler to notify of orphans
        """
        for guild in self.bot.guilds:
            for zone in zones:
                # Find category for this zone
                normalized_name = zone.name.lower().replace(" ", "-")
                category = None
                for cat in guild.categories:
                    if cat.name.lower().replace(" ", "-") == normalized_name:
                        category = cat
                        break

                if category is None:
                    continue

                # Find orphan channels in this category
                for channel in category.channels:
                    if channel.name not in room_ids:
                        reconciler.notify(
                            OrphanChannelDetectedEvent(
                                guild_id=guild.id,
                                channel_name=channel.name,
                                category_name=category.name,
                            )
                        )
