"""Periodic synchronization task for MUDD.

This cog owns ALL sync operations: zones, rooms, and user permissions.
The first sync iteration handles startup initialization, subsequent iterations
perform full syncs every 15 minutes.
"""

import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import asyncpg
import discord
from discord.ext import commands, tasks

if TYPE_CHECKING:
    from main import MuddBot

from mudd.loaders.entity_loader import sync_entities
from mudd.loaders.verb_loader import sync_verbs
from mudd.loaders.zone_loader import sync_zones_and_rooms
from mudd.services.currency import CurrencyService
from mudd.services.entity import EntityService
from mudd.services.entity_resolution import EntityResolutionService
from mudd.services.inventory import InventoryService
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
        entity_resolution: EntityResolutionService,
        visibility_service: VisibilityService,
        pool: asyncpg.Pool,
        rendering_service: RenderingService,
        inventory_service: InventoryService,
        currency_service: CurrencyService,
    ) -> None:
        self.bot = bot
        self.entity_service = entity_service
        self.entity_resolution = entity_resolution
        self.visibility_service = visibility_service
        self._pool = pool
        self._rendering = rendering_service
        self.inventory_service = inventory_service
        self.currency_service = currency_service
        self._seen_orphans: set[tuple[int, str, str]] = set()
        self._console_channel = os.environ.get("MUDD_CONSOLE_CHANNEL", "console")
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
            self.entity_resolution.invalidate_cache()
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

        # Sync user permissions and inventory forums
        for guild in self.bot.guilds:
            try:
                stats = await self.visibility_service.sync_guild(guild)
                logger.info(f"Initial visibility sync for {guild.name}: {stats}")
            except Exception:
                logger.exception(f"Failed initial visibility sync for {guild.name}")
                raise

            # Sync inventory forums for all members
            try:
                inv_stats = await self.inventory_service.sync_user_forums(guild)
                logger.info(f"Initial inventory sync for {guild.name}: {inv_stats}")
            except Exception:
                logger.exception(f"Failed initial inventory sync for {guild.name}")
                # Non-fatal: continue operation

            # Bootstrap wallets for all members
            try:
                wallet_stats = await self.sync_wallets(guild)
                logger.info(f"Initial wallet sync for {guild.name}: {wallet_stats}")
            except Exception:
                logger.exception(f"Failed initial wallet sync for {guild.name}")
                # Non-fatal: continue operation

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
                    self.entity_resolution.invalidate_cache()
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

                # Inventory forum sync
                try:
                    inv_stats = await self.inventory_service.sync_user_forums(guild)
                    logger.info(f"Inventory sync for {guild.name}: {inv_stats}")
                except Exception:
                    logger.exception(f"Failed inventory sync for {guild.name}")
                    # Non-fatal: continue operation

                # Bootstrap wallets for new members
                try:
                    wallet_stats = await self.sync_wallets(guild)
                    logger.info(f"Wallet sync for {guild.name}: {wallet_stats}")
                except Exception:
                    logger.exception(f"Failed wallet sync for {guild.name}")
                    # Non-fatal: continue operation

                # Sync inventory thread descriptions (update first post if changed)
                try:
                    desc_stats = (
                        await self.inventory_service.sync_inventory_descriptions(
                            guild, self._rendering, self.currency_service
                        )
                    )
                    logger.info(
                        f"Inventory description sync for {guild.name}: {desc_stats}"
                    )
                except Exception:
                    logger.exception(
                        f"Failed inventory description sync for {guild.name}"
                    )
                    # Non-fatal: continue operation

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
            count = await self.entity_resolution.prepopulate_cache(rooms)
            logger.info(f"Prepopulated autocomplete cache for {count} rooms")

    @tasks.loop(minutes=1)
    async def respawn_task(self):
        """Process spawning pools for item respawns.

        Runs every minute. For each pool:
        1. Check current instance count vs max_count
        2. Check if respawn_interval has elapsed
        3. If spawning needed, select weighted random entity by tag
        4. Create instance with spawning_pool_id
        """
        # Wait for startup to complete
        await self.visibility_service.wait_for_startup()

        try:
            await self._process_spawning_pools()
        except Exception:
            logger.exception("Failed to process spawning pools")

    @respawn_task.before_loop
    async def before_respawn_task(self):
        """Wait for bot to be ready before starting respawn task."""
        await self.bot.wait_until_ready()

    async def _process_spawning_pools(self) -> None:
        """Check and process all spawning pools."""
        pool = self._pool
        now = datetime.now(UTC)

        # Get all spawning pools with current instance counts and spawned entity IDs
        pools = await pool.fetch(
            """
            SELECT
                sp.id,
                sp.room,
                sp.container_id,
                sp.tag_query,
                sp.max_count,
                sp.respawn_interval_minutes,
                sp.last_spawn_at,
                sp.no_duplicates,
                COUNT(ei.id) AS current_count,
                ARRAY_REMOVE(ARRAY_AGG(ei.entity_id), NULL) AS spawned_entity_ids
            FROM spawning_pools sp
            LEFT JOIN entity_instances ei ON ei.spawning_pool_id = sp.id
            GROUP BY sp.id
            """
        )

        spawned = 0
        for sp in pools:
            # Check if at capacity
            if sp["current_count"] >= sp["max_count"]:
                continue

            # Check if interval has elapsed
            last_spawn = sp["last_spawn_at"]
            if last_spawn is not None:
                elapsed_minutes = (now - last_spawn).total_seconds() / 60
                if elapsed_minutes < sp["respawn_interval_minutes"]:
                    continue

            # Select random entity by tag with weighted rarity
            if sp["no_duplicates"]:
                # Exclude already-spawned entity types
                exclude_ids = set(sp["spawned_entity_ids"] or [])
                entity = await self.entity_service.get_random_entity_by_tag_excluding(
                    sp["tag_query"], exclude_ids
                )
                if entity is None:
                    # All entity types already spawned - skip silently
                    logger.debug(
                        "Pool '%s': all entity types already spawned (no_duplicates)",
                        sp["id"],
                    )
                    continue
            else:
                entity = await self.entity_service.get_random_entity_by_tag(
                    sp["tag_query"]
                )
                if entity is None:
                    logger.warning(
                        "No entities found for spawning pool '%s' with tag '%s'",
                        sp["id"],
                        sp["tag_query"],
                    )
                    continue

            # Create instance (with container if spawning pool has one)
            await pool.execute(
                """
                INSERT INTO entity_instances
                    (entity_id, room, spawning_pool_id, container_entity_id)
                VALUES ($1, $2, $3, $4)
                """,
                entity.id,
                sp["room"],
                sp["id"],
                sp["container_id"],
            )

            # Update last_spawn_at
            await pool.execute(
                "UPDATE spawning_pools SET last_spawn_at = $1 WHERE id = $2",
                now,
                sp["id"],
            )

            spawned += 1
            logger.debug(
                "Spawned '%s' in room '%s' from pool '%s'",
                entity.name,
                sp["room"],
                sp["id"],
            )

        if spawned > 0:
            # Invalidate caches since entities changed
            self.entity_service.invalidate_cache()
            self.entity_resolution.invalidate_cache()
            logger.info(f"Spawned {spawned} items from spawning pools")

    async def sync_wallets(self, guild: discord.Guild) -> dict[str, int]:
        """Bootstrap wallets for all guild members.

        For each member without a wallet:
        1. Create currency account with starting balance
        2. Create wallet entity instance in inventory
        3. Create inventory thread for wallet
        4. Link wallet instance to currency account

        Args:
            guild: Discord guild

        Returns:
            Stats dict with 'created', 'existing', 'errors' counts
        """
        stats = {"created": 0, "existing": 0, "errors": 0}

        # Get wallet entity (must exist after entity sync)
        wallet_entity = await self.entity_service.get_entity("wallet")
        if wallet_entity is None:
            logger.error("Wallet entity not found - cannot bootstrap wallets")
            return stats

        for member in guild.members:
            if member.bot:
                continue

            try:
                # Check if user already has a wallet instance
                wallet_instance_id = await self.currency_service.get_wallet_instance_id(
                    member.id
                )
                if wallet_instance_id is not None:
                    # Check if the wallet instance still exists
                    existing_instance = await self.entity_service.get_entity_instance(
                        UUID(wallet_instance_id)
                    )
                    if existing_instance is not None:
                        # Ensure existing wallet thread is pinned
                        row = await self._pool.fetchrow(
                            """SELECT discord_thread_id FROM entity_instances
                            WHERE id = $1""",
                            UUID(wallet_instance_id),
                        )
                        if row and row["discord_thread_id"]:
                            thread = guild.get_thread(row["discord_thread_id"])
                            if thread and not thread.flags.pinned:
                                await thread.edit(pinned=True)
                        stats["existing"] += 1
                        continue

                # Ensure user has an inventory forum first
                forum = await self.inventory_service.ensure_user_forum(guild, member.id)
                if forum is None:
                    stats["errors"] += 1
                    continue

                # Create currency account (idempotent)
                await self.currency_service.ensure_account(member.id)

                # Create wallet entity instance in inventory
                row = await self._pool.fetchrow(
                    """
                    INSERT INTO entity_instances (entity_id, owner_id)
                    VALUES ($1, $2)
                    RETURNING id
                    """,
                    "wallet",
                    member.id,
                )
                instance_id = row["id"]

                # Get the instance for rendering
                wallet_instance = await self.entity_service.get_entity_instance(
                    instance_id
                )
                if wallet_instance is None:
                    logger.error(f"Failed to fetch wallet instance {instance_id}")
                    stats["errors"] += 1
                    continue

                # Render wallet description with balance
                balance = await self.currency_service.get_balance(member.id)
                balance_str = f"\u00a5{balance:,}" if balance is not None else "\u00a50"
                description = await self._rendering.render_entity_on_look(
                    wallet_instance,
                    self.entity_service,
                    None,  # room is None for inventory items
                    extra_context={"balance": balance_str},
                )

                # Create inventory thread for wallet (pinned for easy access)
                thread = await self.inventory_service.create_item_thread(
                    guild,
                    member.id,
                    instance_id,
                    wallet_entity.display_name,
                    description,
                    pinned=True,
                )
                if thread is None:
                    logger.error(f"Failed to create wallet thread for user {member.id}")
                    stats["errors"] += 1
                    continue

                # Link wallet instance to currency account
                await self.currency_service.link_wallet(member.id, str(instance_id))

                stats["created"] += 1
                logger.info(f"Created wallet for user {member.id} ({member.name})")

            except discord.HTTPException as e:
                logger.error(f"Discord error creating wallet for {member.id}: {e}")
                stats["errors"] += 1
            except Exception:
                logger.exception(f"Failed to create wallet for {member.id}")
                stats["errors"] += 1

        return stats
