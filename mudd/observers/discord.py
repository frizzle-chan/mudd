"""Discord reconciler that syncs Discord state with model changes."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import asyncpg
import discord

if TYPE_CHECKING:
    pass

from mudd.events import (
    BalanceChangedEvent,
    EntityDestroyedEvent,
    EntityDroppedEvent,
    EntityPickedUpEvent,
    GameEvent,
    InventorySyncEvent,
    OrphanChannelDetectedEvent,
    RoomSyncedEvent,
    ZoneSyncedEvent,
)
from mudd.models.entity import EntityInstance

# Type alias for pending events
type PendingEvent = (
    tuple[EntityInstance, str]
    | tuple[ZoneSyncedEvent, str]
    | tuple[RoomSyncedEvent, str]
    | tuple[OrphanChannelDetectedEvent, str]
    | tuple[InventorySyncEvent, str]
)

logger = logging.getLogger(__name__)

INVENTORY_CATEGORY_NAME = "Inventory"


def _get_inventory_forum_name(username: str) -> str:
    """Get the forum channel name for a user's inventory."""
    return f"{username}-inventory"


class DiscordReconciler:
    """Observes model changes and reconciles Discord state.

    Handles Discord operations when models change:
    - Entity events: Creates/deletes inventory threads
    - Zone events: Creates Discord categories idempotently
    - Room events: Creates Discord channels idempotently
    - Orphan events: Reports new orphan channels to console

    The reconciler implements the Observer protocol: notify() is sync
    and queues notifications for async processing. Call flush() after
    sending the response to execute queued Discord operations.

    Events are idempotent - fire an event a million times, it creates
    the resource once and noops thereafter.

    Usage:
        reconciler = DiscordReconciler(bot, pool)
        await Zone.sync_all(pool, zones, observers=(reconciler,))
        await Room.sync_all(pool, rooms, default_room, observers=(reconciler,))
        await reconciler.flush()  # Idempotently reconciles Discord state
    """

    def __init__(
        self,
        bot: discord.Client,
        pool: asyncpg.Pool,
        console_channel: str = "console",
    ) -> None:
        """Initialize the Discord reconciler.

        Args:
            bot: Discord bot client
            pool: Database connection pool
            console_channel: Channel name for orphan notifications
        """
        self.bot = bot
        self.pool = pool
        self._console_channel = console_channel
        self._pending: list[PendingEvent] = []
        # Cache category ID per guild to avoid repeated lookups
        self._category_cache: dict[int, int] = {}
        # Track zone categories per guild: guild_id -> {zone_id -> category}
        self._zone_categories: dict[int, dict[str, discord.CategoryChannel]] = {}
        # Track seen orphans: (guild_id, channel_name, category_name)
        self._seen_orphans: set[tuple[int, str, str]] = set()
        # Stats for inventory forum sync
        self._inventory_forum_stats: dict[str, int] = {
            "created": 0,
            "recovered": 0,
            "existing": 0,
            "renamed": 0,
            "fixed": 0,
            "threads_pruned": 0,
            "errors": 0,
        }

    def notify(self, event: GameEvent) -> None:
        """Receive notification (sync). Queue for async processing.

        This method is called synchronously by models when state changes.
        It queues the event for later async processing via flush().

        Args:
            event: The game event to process
        """
        match event:
            case EntityPickedUpEvent(instance=instance):
                # Route pickup to inventory sync (creates thread for new item)
                if instance.owner_id:
                    self._pending.append(
                        (
                            InventorySyncEvent(guild_id=0, user_id=instance.owner_id),
                            "inventory_sync",
                        )
                    )
            case EntityDroppedEvent(instance=instance):
                self._pending.append((instance, "dropped"))
            case EntityDestroyedEvent(instance=instance):
                self._pending.append((instance, "destroyed"))
            case ZoneSyncedEvent() as evt:
                self._pending.append((evt, "zone_synced"))
            case RoomSyncedEvent() as evt:
                self._pending.append((evt, "room_synced"))
            case OrphanChannelDetectedEvent() as evt:
                self._pending.append((evt, "orphan_detected"))
            case InventorySyncEvent() as evt:
                self._pending.append((evt, "inventory_sync"))
            case BalanceChangedEvent() as evt:
                # Route balance changes to inventory sync (updates wallet description)
                self._pending.append(
                    (
                        InventorySyncEvent(guild_id=0, user_id=evt.user_id),
                        "inventory_sync",
                    )
                )
            # Ignore template signals - they're handled by EffectsObserver

    async def flush(self) -> None:
        """Process queued notifications. Call after response sent.

        Processes all pending events and clears the queue. Safe to call
        multiple times; subsequent calls are no-ops if queue is empty.

        Events are processed in order:
        1. Zone events (create categories)
        2. Room events (create channels in categories)
        3. Orphan events (report to console)
        4. Entity events (create/delete threads)
        """
        pending = self._pending
        self._pending = []

        if not self.bot.guilds:
            logger.warning("No guilds available, skipping Discord reconciliation")
            return

        # Sort events by type for proper ordering
        zone_events: list[ZoneSyncedEvent] = []
        room_events: list[RoomSyncedEvent] = []
        orphan_events: list[OrphanChannelDetectedEvent] = []
        inventory_sync_events: list[InventorySyncEvent] = []
        entity_events: list[tuple[EntityInstance, str]] = []

        for item, event_type in pending:
            match event_type:
                case "zone_synced":
                    zone_events.append(item)  # type: ignore[arg-type]
                case "room_synced":
                    room_events.append(item)  # type: ignore[arg-type]
                case "orphan_detected":
                    orphan_events.append(item)  # type: ignore[arg-type]
                case "inventory_sync":
                    inventory_sync_events.append(item)  # type: ignore[arg-type]
                case _:
                    entity_events.append((item, event_type))  # type: ignore[arg-type]

        # Process for each guild
        for guild in self.bot.guilds:
            # 1. Process zone events (create categories)
            for evt in zone_events:
                await self._ensure_zone_category(guild, evt)

            # 2. Process room events (create channels)
            for evt in room_events:
                await self._ensure_room_channel(guild, evt)

            # 3. Process orphan events (report to console)
            for evt in orphan_events:
                if evt.guild_id == guild.id:
                    await self._report_orphan(guild, evt)

            # 4. Process inventory sync events (unified handler)
            # Deduplicate by user_id - multiple events for same user only need one sync
            synced_users: set[int] = set()
            for evt in inventory_sync_events:
                # Handle guild_id=0 (from BalanceChangedEvent/EntityPickedUpEvent)
                # or matching guild
                if evt.guild_id != 0 and evt.guild_id != guild.id:
                    continue
                if evt.user_id in synced_users:
                    continue
                synced_users.add(evt.user_id)
                await self._ensure_user_inventory(guild, evt.user_id)

        # 5. Process entity events (drop/destroy - pickup handled by inventory sync)
        for instance, event_type in entity_events:
            await self._handle_entity_event(instance, event_type)

    async def _handle_entity_event(self, instance: EntityInstance, event: str) -> None:
        """Handle a single entity event (drop/destroy only).

        Pickup is now handled by InventorySyncEvent through _ensure_user_inventory().

        Args:
            instance: The entity instance that changed
            event: The event name
        """
        if not self.bot.guilds:
            logger.warning("No guilds available, skipping Discord reconciliation")
            return

        guild = self.bot.guilds[0]  # Single-guild bot

        match event:
            case "dropped" | "destroyed":
                await self._delete_inventory_thread(guild, instance)

    async def _ensure_zone_category(
        self, guild: discord.Guild, event: ZoneSyncedEvent
    ) -> discord.CategoryChannel | None:
        """Idempotent: create category for zone if missing, return existing otherwise.

        Args:
            guild: Discord guild
            event: Zone synced event with zone_id and name

        Returns:
            The category channel, or None if creation failed
        """
        # Initialize guild's zone categories dict if needed
        if guild.id not in self._zone_categories:
            self._zone_categories[guild.id] = {}

        # Check if already cached this session
        if event.zone_id in self._zone_categories[guild.id]:
            return self._zone_categories[guild.id][event.zone_id]

        # Normalize zone name to match Discord category naming
        normalized_name = event.name.lower().replace(" ", "-")

        # Look for existing category by normalized name
        for category in guild.categories:
            category_normalized = category.name.lower().replace(" ", "-")
            if category_normalized == normalized_name:
                self._zone_categories[guild.id][event.zone_id] = category
                return category

        # Create new category with fog-of-war permissions
        try:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False)
            }
            category = await guild.create_category(event.name, overwrites=overwrites)
            self._zone_categories[guild.id][event.zone_id] = category
            logger.info(f"Created category '{event.name}' for zone {event.zone_id}")
            return category
        except discord.HTTPException as e:
            logger.error(f"Failed to create category for zone {event.zone_id}: {e}")
            return None

    async def _ensure_room_channel(
        self, guild: discord.Guild, event: RoomSyncedEvent
    ) -> None:
        """Idempotent: create text/voice channels for room if missing.

        Args:
            guild: Discord guild
            event: Room synced event with room details
        """
        # Get category for this room's zone
        if guild.id not in self._zone_categories:
            self._zone_categories[guild.id] = {}

        category = self._zone_categories[guild.id].get(event.zone_id)
        if category is None:
            logger.warning(
                f"No category for zone {event.zone_id}, skipping room {event.room_id}"
            )
            return

        # Find existing text channel by name (anywhere in guild)
        existing_text = discord.utils.get(guild.text_channels, name=event.room_id)

        if existing_text is None:
            # Create text channel
            try:
                await category.create_text_channel(
                    event.room_id, topic=event.description
                )
                logger.info(
                    f"Created text channel '{event.room_id}' in {category.name}"
                )
            except discord.HTTPException as e:
                logger.error(f"Failed to create text channel {event.room_id}: {e}")
        else:
            # Update if topic or category changed
            needs_update = (
                existing_text.topic != event.description
                or existing_text.category_id != category.id
            )
            if needs_update:
                try:
                    await existing_text.edit(topic=event.description, category=category)
                    logger.debug(f"Updated text channel '{event.room_id}'")
                except discord.HTTPException as e:
                    logger.error(f"Failed to update text channel {event.room_id}: {e}")

        # Handle voice channel if needed
        if event.has_voice:
            existing_voice = discord.utils.get(guild.voice_channels, name=event.room_id)
            if existing_voice is None:
                try:
                    await category.create_voice_channel(event.room_id)
                    logger.info(
                        f"Created voice channel '{event.room_id}' in {category.name}"
                    )
                except discord.HTTPException as e:
                    logger.error(f"Failed to create voice channel {event.room_id}: {e}")
            elif existing_voice.category_id != category.id:
                try:
                    await existing_voice.edit(category=category)
                    logger.debug(
                        f"Moved voice channel '{event.room_id}' to {category.name}"
                    )
                except discord.HTTPException as e:
                    logger.error(f"Failed to move voice channel {event.room_id}: {e}")

    async def _report_orphan(
        self, guild: discord.Guild, event: OrphanChannelDetectedEvent
    ) -> None:
        """Report orphan channel to console if not already seen.

        Args:
            guild: Discord guild
            event: Orphan channel detected event
        """
        key = (event.guild_id, event.channel_name, event.category_name)
        if key in self._seen_orphans:
            return

        self._seen_orphans.add(key)

        console = discord.utils.get(guild.text_channels, name=self._console_channel)
        if console is None:
            logger.warning(
                f"Console channel #{self._console_channel} not found, "
                f"cannot report orphan #{event.channel_name}"
            )
            return

        try:
            await console.send(
                f"**Orphan channel detected**: #{event.channel_name} "
                f"in {event.category_name}\n"
                "Consider deleting this channel or adding it to the world file."
            )
            logger.info(f"Reported orphan channel #{event.channel_name} to console")
        except discord.HTTPException as e:
            logger.error(f"Failed to report orphan to console: {e}")

    async def _render_on_look(self, instance: EntityInstance) -> str:
        """Render on_look using LookCommand with EntityModal context.

        Creates a minimal scene with the inventory item and executes
        LookCommand to render the item's description.

        Args:
            instance: The entity instance to render

        Returns:
            Rendered on_look output
        """
        from mudd.commands2 import LookCommand
        from mudd.models.room import InventoryThread
        from mudd.models.user import User
        from mudd.observers import EffectsObserver
        from mudd.scene import Scene

        if instance.owner_id is None:
            return "You see nothing special."

        # Get user who owns the item
        user = await User.get(self.pool, instance.owner_id)
        if user is None:
            return "You see nothing special."

        # Create modal for the inventory item
        modal = InventoryThread(
            _pool=self.pool,
            id=f"inventory:{instance.instance_id}",
            entity_instance=instance,
            owner=user,
        )

        # Create scene with effects observer (required by execute)
        effects = EffectsObserver()
        scene = Scene(_pool=self.pool, user=user, room=modal)
        scene = scene.with_observers(effects)

        # Execute look command
        command = LookCommand()
        result = await command.execute(scene, instance)

        return result.output

    async def _ensure_inventory_category(
        self, guild: discord.Guild
    ) -> discord.CategoryChannel:
        """Ensure the Inventory category exists, create if missing.

        The category is created with @everyone view_channel=False (hidden by default).

        Args:
            guild: Discord guild

        Returns:
            The Inventory category channel
        """
        # Check cache first
        if guild.id in self._category_cache:
            category = guild.get_channel(self._category_cache[guild.id])
            if category and isinstance(category, discord.CategoryChannel):
                return category
            # Cache is stale, clear it
            del self._category_cache[guild.id]

        # Look for existing category
        for category in guild.categories:
            if category.name == INVENTORY_CATEGORY_NAME:
                self._category_cache[guild.id] = category.id
                return category

        # Create new category with fog-of-war permissions
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False)
        }
        category = await guild.create_category(
            INVENTORY_CATEGORY_NAME, overwrites=overwrites
        )
        self._category_cache[guild.id] = category.id
        logger.info(f"Created Inventory category in {guild.name}")
        return category

    async def _delete_inventory_thread(
        self, guild: discord.Guild, instance: EntityInstance
    ) -> None:
        """Idempotent: delete inventory thread for a dropped/destroyed item.

        Safe to call multiple times - noops if thread doesn't exist.

        Args:
            guild: Discord guild
            instance: The entity instance that was dropped or destroyed
        """
        # Get thread ID from database
        row = await self.pool.fetchrow(
            "SELECT discord_thread_id FROM entity_instances WHERE id = $1",
            instance.instance_id,
        )
        if row is None or row["discord_thread_id"] is None:
            # No thread reference - already deleted or never created (idempotent)
            return

        thread_id = row["discord_thread_id"]

        # Delete Discord thread first (before DB update to avoid orphaning)
        thread = guild.get_thread(thread_id)
        if thread:
            try:
                await thread.delete()
                logger.info(
                    f"Deleted thread {thread_id} for instance {instance.instance_id}"
                )
            except discord.HTTPException as e:
                logger.error(f"Failed to delete thread {thread_id}: {e}")
                return
        else:
            # Thread doesn't exist in Discord - already deleted (idempotent)
            logger.debug(
                f"Thread {thread_id} not found in Discord, clearing DB reference"
            )

        # Clear DB reference (thread either deleted or doesn't exist)
        await self.pool.execute(
            """UPDATE entity_instances
            SET discord_thread_id = NULL, discord_description_msg_id = NULL
            WHERE id = $1""",
            instance.instance_id,
        )

    def get_inventory_forum_stats(self) -> dict[str, int]:
        """Get accumulated inventory forum sync stats.

        Returns:
            Stats dict with keys: created, recovered, existing, renamed,
            fixed, threads_pruned, errors
        """
        return self._inventory_forum_stats.copy()

    def reset_inventory_forum_stats(self) -> None:
        """Reset inventory forum sync stats to zero."""
        self._inventory_forum_stats = {
            "created": 0,
            "recovered": 0,
            "existing": 0,
            "renamed": 0,
            "fixed": 0,
            "threads_pruned": 0,
            "errors": 0,
        }

    async def _prune_orphan_threads(
        self, forum: discord.ForumChannel, user_id: int
    ) -> int:
        """Delete threads that don't correspond to inventory items.

        Args:
            forum: User's inventory forum
            user_id: Discord user ID

        Returns:
            Number of threads pruned
        """
        # Query all valid thread IDs for this user's inventory items
        rows = await self.pool.fetch(
            """
            SELECT discord_thread_id FROM entity_instances
            WHERE owner_id = $1 AND discord_thread_id IS NOT NULL
            """,
            user_id,
        )
        valid_thread_ids = {row["discord_thread_id"] for row in rows}

        pruned = 0
        for thread in forum.threads:
            if thread.id in valid_thread_ids:
                continue

            # Orphan thread - delete it
            try:
                await thread.delete()
                pruned += 1
                logger.info(
                    f"Pruned orphan thread '{thread.name}' (ID: {thread.id}) "
                    f"from inventory forum for user {user_id}"
                )
            except discord.HTTPException as e:
                logger.error(f"Failed to prune thread {thread.id}: {e}")

        return pruned

    async def _ensure_user_inventory(self, guild: discord.Guild, user_id: int) -> None:
        """Idempotent: ensure user's complete inventory is synced.

        This unified handler consolidates all inventory sync operations:
        1. Ensure Inventory category exists
        2. Ensure user's forum exists (create or recover by name search)
        3. Fix forum name/permissions if needed
        4. Ensure wallet exists with pinned thread
        5. Ensure all inventory items have threads
        6. Update thread descriptions if content changed
        7. Prune orphan threads

        Args:
            guild: Discord guild
            user_id: Discord user ID
        """
        member = guild.get_member(user_id)
        if member is None:
            logger.debug(f"User {user_id} not found in guild {guild.name}")
            return
        if member.bot:
            return

        try:
            # 1. Ensure Inventory category exists
            category = await self._ensure_inventory_category(guild)
            forum_name = _get_inventory_forum_name(member.name)

            # 2. Find or create user's inventory forum
            forum = await self._find_or_create_forum(
                guild, category, member, forum_name
            )
            if forum is None:
                self._inventory_forum_stats["errors"] += 1
                return

            # 3. Fix forum name if username changed
            if forum.name != forum_name:
                try:
                    await forum.edit(name=forum_name)
                    logger.info(
                        f"Renamed forum '{forum.name}' -> '{forum_name}' "
                        f"for user {user_id}"
                    )
                    self._inventory_forum_stats["renamed"] += 1
                except discord.HTTPException as e:
                    logger.error(f"Failed to rename forum {forum.id}: {e}")

            # 4. Fix permissions if needed (remove thread creation ability)
            overwrites = forum.overwrites_for(member)
            if overwrites.create_public_threads is not False:
                try:
                    await forum.set_permissions(
                        member,
                        view_channel=True,
                        send_messages_in_threads=True,
                        create_public_threads=False,
                        send_messages=False,
                    )
                    self._inventory_forum_stats["fixed"] += 1
                except discord.HTTPException as e:
                    logger.error(f"Failed to fix permissions for forum {forum.id}: {e}")

            # 5. Ensure wallet exists and has thread
            await self._ensure_wallet_thread(guild, user_id, forum)

            # 6. Get all inventory items and ensure threads with current descriptions
            await self._sync_inventory_threads(guild, user_id, forum)

            # 7. Prune orphan threads
            pruned = await self._prune_orphan_threads(forum, user_id)
            self._inventory_forum_stats["threads_pruned"] += pruned

        except discord.HTTPException as e:
            logger.error(f"Failed to ensure inventory for user {user_id}: {e}")
            self._inventory_forum_stats["errors"] += 1

    async def _find_or_create_forum(
        self,
        guild: discord.Guild,
        category: discord.CategoryChannel,
        member: discord.Member,
        forum_name: str,
    ) -> discord.ForumChannel | None:
        """Find existing forum or create new one. Handles recovery from DB loss.

        Search order:
        1. Check DB for existing forum record
        2. Search Discord by name (recovery case)
        3. Create new forum

        Args:
            guild: Discord guild
            category: Inventory category
            member: Discord member
            forum_name: Expected forum name

        Returns:
            Forum channel, or None if creation failed
        """
        # Check DB for existing forum record
        forum_data = await self.pool.fetchrow(
            """SELECT forum_id FROM user_inventory_forums WHERE user_id = $1""",
            member.id,
        )

        if forum_data:
            forum = guild.get_channel(forum_data["forum_id"])
            if forum and isinstance(forum, discord.ForumChannel):
                self._inventory_forum_stats["existing"] += 1
                return forum
            # Forum was deleted from Discord, clear stale DB record
            logger.info(
                f"Forum {forum_data['forum_id']} was deleted from Discord, "
                f"clearing DB record for user {member.id}"
            )
            await self.pool.execute(
                "DELETE FROM user_inventory_forums WHERE user_id = $1", member.id
            )

        # Search Discord for existing forums (recovery case)
        matching_forums = [
            f
            for f in guild.forums
            if f.category_id == category.id and f.name == forum_name
        ]
        matching_forums.sort(key=lambda f: f.id)

        if matching_forums:
            # Keep oldest (smallest ID), delete duplicates
            forum = matching_forums[0]
            for dup in matching_forums[1:]:
                try:
                    await dup.delete(
                        reason="Duplicate inventory forum cleanup during sync"
                    )
                    logger.info(f"Deleted duplicate inventory forum (ID: {dup.id})")
                except discord.HTTPException as e:
                    logger.error(f"Failed to delete duplicate forum {dup.id}: {e}")

            # Ensure user exists and update DB
            await self._register_forum_in_db(member.id, forum.id, category.id)
            self._inventory_forum_stats["recovered"] += 1
            logger.info(
                f"Recovered inventory forum '{forum.name}' (ID: {forum.id}) "
                f"for user {member.id}"
            )
            return forum

        # Create new forum
        return await self._create_new_forum(guild, category, member, forum_name)

    async def _create_new_forum(
        self,
        guild: discord.Guild,
        category: discord.CategoryChannel,
        member: discord.Member,
        forum_name: str,
    ) -> discord.ForumChannel | None:
        """Create a new inventory forum for a user.

        Args:
            guild: Discord guild
            category: Inventory category
            member: Discord member
            forum_name: Forum name

        Returns:
            Created forum, or None if failed
        """
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages_in_threads=True,
                create_public_threads=False,
                send_messages=False,
            ),
        }

        try:
            forum = await category.create_forum(
                name=forum_name,
                topic=f"Personal inventory for {member.display_name}",
                overwrites=overwrites,
            )

            await self._register_forum_in_db(member.id, forum.id, category.id)
            self._inventory_forum_stats["created"] += 1
            logger.info(f"Created inventory forum '{forum_name}' for user {member.id}")
            return forum
        except discord.HTTPException as e:
            logger.error(f"Failed to create inventory forum for {member.id}: {e}")
            return None

    async def _register_forum_in_db(
        self, user_id: int, forum_id: int, category_id: int
    ) -> None:
        """Register forum in database. Ensures user exists first.

        Args:
            user_id: Discord user ID
            forum_id: Discord forum channel ID
            category_id: Discord category ID
        """
        # Ensure user exists in users table
        await self.pool.execute(
            """
            INSERT INTO users (id, current_room)
            SELECT $1, (SELECT id FROM rooms WHERE is_default = TRUE)
            WHERE NOT EXISTS (SELECT 1 FROM users WHERE id = $1)
            """,
            user_id,
        )

        # Store forum in database
        await self.pool.execute(
            """
            INSERT INTO user_inventory_forums (user_id, forum_id, category_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE SET forum_id = $2, category_id = $3
            """,
            user_id,
            forum_id,
            category_id,
        )

    async def _ensure_wallet_thread(
        self, guild: discord.Guild, user_id: int, forum: discord.ForumChannel
    ) -> None:
        """Ensure user has a wallet with a pinned thread.

        Args:
            guild: Discord guild
            user_id: Discord user ID
            forum: User's inventory forum
        """
        from mudd.models.user import User
        from mudd.services.currency import STARTING_BALANCE

        # Get or create user
        user = await User.get_or_create(self.pool, user_id)

        # Check for existing wallet
        wallet = await user.get_wallet()
        if wallet is None:
            # Create currency account (idempotent)
            await self.pool.execute(
                """
                INSERT INTO currency_accounts (user_id, balance)
                VALUES ($1, $2)
                ON CONFLICT (user_id) DO NOTHING
                """,
                user_id,
                STARTING_BALANCE,
            )

            # Create wallet instance
            wallet = await EntityInstance.create(
                self.pool,
                "wallet",
                owner_id=user_id,
            )

            if wallet is None:
                logger.warning(f"Wallet entity not found, skipping for {user_id}")
                return

            # Link wallet instance to currency account
            await self.pool.execute(
                """
                UPDATE currency_accounts
                SET wallet_instance_id = $2
                WHERE user_id = $1
                """,
                user_id,
                str(wallet.instance_id),
            )
            logger.info(f"Created wallet for user {user_id}")

        # Ensure wallet has a thread
        row = await self.pool.fetchrow(
            "SELECT discord_thread_id FROM entity_instances WHERE id = $1",
            wallet.instance_id,
        )
        if row and row["discord_thread_id"]:
            thread = guild.get_thread(row["discord_thread_id"])
            if thread:
                # Thread exists - ensure it's pinned
                if not thread.flags.pinned:
                    try:
                        await thread.edit(pinned=True)
                        logger.debug(f"Pinned wallet thread {thread.id}")
                    except discord.HTTPException as e:
                        logger.error(f"Failed to pin wallet thread: {e}")
                return

        # Create wallet thread
        description = await self._render_on_look(wallet)
        try:
            thread, message = await forum.create_thread(
                name=wallet.entity.name,
                content=description or f"You have a {wallet.entity.name}.",
            )

            await self.pool.execute(
                """UPDATE entity_instances
                SET discord_thread_id = $1, discord_description_msg_id = $2
                WHERE id = $3""",
                thread.id,
                message.id,
                wallet.instance_id,
            )

            # Pin wallet thread
            await thread.edit(pinned=True)
            logger.info(f"Created and pinned wallet thread for user {user_id}")
        except discord.HTTPException as e:
            logger.error(f"Failed to create wallet thread: {e}")

    async def _sync_inventory_threads(
        self, guild: discord.Guild, user_id: int, forum: discord.ForumChannel
    ) -> None:
        """Ensure all inventory items have threads with current descriptions.

        Args:
            guild: Discord guild
            user_id: Discord user ID
            forum: User's inventory forum
        """
        # Query all inventory items for this user
        rows = await self.pool.fetch(
            """
            SELECT ei.id, ei.entity_id,
                   ei.discord_thread_id, ei.discord_description_msg_id
            FROM entity_instances ei
            WHERE ei.owner_id = $1
            """,
            user_id,
        )

        for row in rows:
            instance_id = row["id"]
            thread_id = row["discord_thread_id"]
            msg_id = row["discord_description_msg_id"]

            # Get instance for rendering
            instance = await EntityInstance.get(self.pool, instance_id)
            if instance is None:
                continue

            if thread_id:
                thread = guild.get_thread(thread_id)
                if thread and msg_id:
                    # Thread exists - check if description needs update
                    await self._update_thread_description(thread, msg_id, instance)
                    continue
                # Thread was deleted, clear reference and recreate
                if not thread:
                    await self.pool.execute(
                        """UPDATE entity_instances
                        SET discord_thread_id = NULL, discord_description_msg_id = NULL
                        WHERE id = $1""",
                        instance_id,
                    )

            # Create thread for this item
            await self._create_item_thread(forum, instance)

    async def _update_thread_description(
        self, thread: discord.Thread, msg_id: int, instance: EntityInstance
    ) -> None:
        """Update thread description if content has changed.

        Args:
            thread: Discord thread
            msg_id: Description message ID
            instance: Entity instance
        """
        new_description = await self._render_on_look(instance)

        try:
            message = await thread.fetch_message(msg_id)
            if message.content != new_description:
                await message.edit(content=new_description)
                logger.debug(
                    f"Updated description for instance {instance.instance_id} "
                    f"in thread {thread.id}"
                )
        except discord.NotFound:
            logger.warning(f"Description message {msg_id} not found in {thread.id}")
        except discord.HTTPException as e:
            logger.error(f"Failed to update description message {msg_id}: {e}")

    async def _create_item_thread(
        self, forum: discord.ForumChannel, instance: EntityInstance
    ) -> None:
        """Create a thread for an inventory item.

        Args:
            forum: User's inventory forum
            instance: Entity instance
        """
        description = await self._render_on_look(instance)

        try:
            thread, message = await forum.create_thread(
                name=instance.entity.name,
                content=description or f"You have a {instance.entity.name}.",
            )

            await self.pool.execute(
                """UPDATE entity_instances
                SET discord_thread_id = $1, discord_description_msg_id = $2
                WHERE id = $3""",
                thread.id,
                message.id,
                instance.instance_id,
            )

            logger.info(
                f"Created thread '{instance.entity.name}' for instance "
                f"{instance.instance_id}"
            )
        except discord.HTTPException as e:
            logger.error(f"Failed to create item thread: {e}")
        except asyncpg.PostgresError as e:
            logger.error(f"Failed to store thread ID: {e}")
