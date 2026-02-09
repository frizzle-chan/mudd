"""Periodic synchronization task for MUDD.

This cog owns ALL sync operations: zones, rooms, and user permissions.
The first sync iteration handles startup initialization, subsequent iterations
perform full syncs every 15 minutes.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import asyncpg
import discord
from discord.ext import commands, tasks

if TYPE_CHECKING:
    from mudd.bot import MuddBot
    from mudd.caches.entity_autocomplete import EntityAutocompleteCache
    from mudd.caches.user import UserCache

from mudd.events import (
    InventorySyncEvent,
    OrphanChannelDetectedEvent,
    UserSyncEvent,
)
from mudd.loaders.entity_loader import sync_entities
from mudd.loaders.verb_loader import sync_verbs
from mudd.loaders.zone_loader import (
    ZoneData,
    get_default_room,
    load_rooms_from_rec,
    load_zones_from_rec,
)
from mudd.models import Room, Zone
from mudd.observers import DiscordReconciler, RoomChannelCache
from mudd.observers.skills_reconciler import ensure_category, ensure_roles

logger = logging.getLogger(__name__)


class Sync(commands.Cog):
    """Background task for periodic Discord synchronization.

    Responsibilities:
    - Zone/room sync: Create missing channels, fix topics, detect orphans
    - Visibility sync: Sync user permissions to match database state
    - Orphan tracking: Only report NEW orphans to console (not previously seen)
    """

    bot: MuddBot
    room_cache: RoomChannelCache

    def __init__(
        self,
        bot: MuddBot,
        pool: asyncpg.Pool,
        room_cache: RoomChannelCache,
        autocomplete_cache: EntityAutocompleteCache | None = None,
        user_cache: UserCache | None = None,
    ) -> None:
        self.bot = bot
        self._pool = pool
        self.room_cache = room_cache
        self._autocomplete_cache = autocomplete_cache
        self._user_cache = user_cache
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

    async def _sync(self, pool: asyncpg.Pool, *, fail_fast: bool) -> None:
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

        # Create reconciler for Discord operations (without room_cache initially
        # since it needs to be rebuilt after channels are created)
        reconciler = DiscordReconciler(
            self.bot,
            pool,
            room_cache=None,
            console_channel=self._console_channel,
            seen_orphans=self._seen_orphans,
        )

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

        # Rebuild caches after entities are synced
        if self._autocomplete_cache is not None:
            try:
                await self._autocomplete_cache.rebuild(pool)
            except Exception:
                logger.exception("Failed to rebuild autocomplete cache")
                if fail_fast:
                    raise

        if self._user_cache is not None:
            try:
                await self._user_cache.rebuild(pool)
            except Exception:
                logger.exception("Failed to rebuild user cache")
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

        for guild in self.bot.guilds:
            logger.info(f"Starting remaining sync for {guild.name}")

            # Rebuild room cache after channels are created
            try:
                await self.room_cache.rebuild(guild)
            except Exception:
                logger.exception(f"Failed to rebuild room cache for {guild.name}")
                if fail_fast:
                    raise

            # Create reconciler with room_cache for permission sync
            perm_reconciler = DiscordReconciler(
                self.bot,
                pool,
                room_cache=self.room_cache,
                console_channel=self._console_channel,
            )

            # Visibility sync via UserLocationSyncEvent
            try:
                vis_stats = await self._sync_user_visibility(guild, perm_reconciler)
                logger.info(f"Visibility sync for {guild.name}: {vis_stats}")
            except Exception:
                logger.exception(f"Failed visibility sync for {guild.name}")
                if fail_fast:
                    raise

            # Inventory sync via unified event (forums, wallets, threads, descriptions)
            # Reset stats before sync
            perm_reconciler.reset_inventory_forum_stats()
            member_count = 0
            for member in guild.members:
                if not member.bot:
                    member_count += 1
                    perm_reconciler.notify(
                        InventorySyncEvent(guild_id=guild.id, user_id=member.id)
                    )

            try:
                await perm_reconciler.flush()
                inv_stats = perm_reconciler.get_inventory_forum_stats()
                logger.info(
                    f"Inventory sync for {guild.name}: "
                    f"{member_count} users, {inv_stats}"
                )
            except Exception:
                logger.exception(f"Failed inventory sync for {guild.name}")

            # Skills sync: channels, nicknames, milestone roles
            try:
                await self._sync_skills(guild, pool)
            except Exception:
                logger.exception(f"Failed skills sync for {guild.name}")

        if fail_fast:
            logger.info("Initial sync complete")

    async def _sync_skills(self, guild: discord.Guild, pool: asyncpg.Pool) -> None:
        """Sync skills channels, nicknames, and milestone roles.

        Args:
            guild: Discord guild
            pool: Database connection pool
        """
        reconciler = DiscordReconciler(self.bot, pool)

        # Ensure milestone roles and skills category exist
        await ensure_roles(guild)
        await ensure_category(guild)

        # Sync each non-bot member
        synced = 0
        for member in guild.members:
            if member.bot:
                continue
            try:
                await reconciler.skills.sync_user(guild, member)
                synced += 1
            except Exception:
                logger.exception("Failed to sync skills for user %d", member.id)

        logger.info(f"Skills sync for {guild.name}: {synced} users")

    async def _sync_user_visibility(
        self, guild, reconciler: DiscordReconciler
    ) -> dict[str, int]:
        """Sync all users' data and Discord permissions.

        Uses UserSyncEvent to:
        1. Upsert user with display_name (keeping display names in sync)
        2. Grant permissions to current room (or default for new users)

        Args:
            guild: Discord guild
            reconciler: DiscordReconciler with room_cache attached

        Returns:
            Stats dict with counts of users synced
        """
        default_channel_id = await self.room_cache.get_default_channel_id()
        if default_channel_id is None:
            default_room = await self.room_cache.get_default_room()
            raise RuntimeError(
                f"Default room '{default_room}' not found in any zone category. "
                f"Ensure the room exists in Discord."
            )

        default_room = await self.room_cache.get_default_room()
        stats = {"synced": 0, "errors": 0}

        for member in guild.members:
            if member.bot:
                continue

            try:
                # Emit UserSyncEvent - handles user upsert with display_name
                # and grants permissions to current room (or default for new users)
                reconciler.notify(
                    UserSyncEvent(
                        user_id=member.id,
                        display_name=member.display_name,
                        default_room=default_room,
                        guild_id=guild.id,
                    )
                )
                stats["synced"] += 1

            except Exception:
                logger.exception(f"Failed to sync user {member.id}")
                stats["errors"] += 1

        # Flush all user sync events
        await reconciler.flush()

        return stats

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
        affected_rooms: set[str] = set()
        for sp in pools:
            instance = await sp.try_spawn(now)

            if instance is not None:
                spawned += 1
                affected_rooms.add(sp.room)
                logger.debug(
                    "Spawned '%s' in room '%s' from pool '%s'",
                    instance.entity.name,
                    sp.room,
                    sp.id,
                )

        if spawned > 0:
            logger.info(f"Spawned {spawned} items from spawning pools")

        # Invalidate + rebuild autocomplete cache for rooms where items spawned
        if affected_rooms and self._autocomplete_cache is not None:
            for room_id in affected_rooms:
                self._autocomplete_cache.invalidate_room(room_id)
            for room_id in affected_rooms:
                await self._autocomplete_cache.rebuild_room(self._pool, room_id)

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
