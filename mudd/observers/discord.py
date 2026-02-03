"""Discord reconciler that syncs Discord state with model changes."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

import asyncpg
import discord

if TYPE_CHECKING:
    pass

from mudd.events import (
    EntityDestroyedEvent,
    EntityDroppedEvent,
    EntityPickedUpEvent,
    GameEvent,
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

    def notify(self, event: GameEvent) -> None:
        """Receive notification (sync). Queue for async processing.

        This method is called synchronously by models when state changes.
        It queues the event for later async processing via flush().

        Args:
            event: The game event to process
        """
        match event:
            case EntityPickedUpEvent(instance=instance):
                self._pending.append((instance, "picked_up"))
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
        entity_events: list[tuple[EntityInstance, str]] = []

        for item, event_type in pending:
            match event_type:
                case "zone_synced":
                    zone_events.append(item)  # type: ignore[arg-type]
                case "room_synced":
                    room_events.append(item)  # type: ignore[arg-type]
                case "orphan_detected":
                    orphan_events.append(item)  # type: ignore[arg-type]
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

        # 4. Process entity events (original behavior)
        for instance, event_type in entity_events:
            await self._handle_entity_event(instance, event_type)

    async def _handle_entity_event(self, instance: EntityInstance, event: str) -> None:
        """Handle a single entity event.

        Args:
            instance: The entity instance that changed
            event: The event name
        """
        if not self.bot.guilds:
            logger.warning("No guilds available, skipping Discord reconciliation")
            return

        guild = self.bot.guilds[0]  # Single-guild bot

        match event:
            case "picked_up":
                await self._create_inventory_thread(guild, instance)
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

    async def _ensure_user_forum(
        self, guild: discord.Guild, user_id: int
    ) -> discord.ForumChannel | None:
        """Ensure user has an inventory forum, create if missing.

        Args:
            guild: Discord guild
            user_id: Discord user ID

        Returns:
            The user's forum channel, or None if user not found in guild or is a bot
        """
        member = guild.get_member(user_id)
        if member is None:
            logger.warning(f"User {user_id} not found in guild {guild.name}")
            return None

        if member.bot:
            return None

        # Ensure category exists first
        category = await self._ensure_inventory_category(guild)
        forum_name = _get_inventory_forum_name(member.name)

        # Check database for existing forum
        forum_data = await self.pool.fetchrow(
            """SELECT user_id, forum_id, category_id
            FROM user_inventory_forums WHERE user_id = $1""",
            user_id,
        )

        if forum_data:
            # Verify forum still exists in Discord
            forum = guild.get_channel(forum_data["forum_id"])
            if forum and isinstance(forum, discord.ForumChannel):
                return forum
            # Forum was deleted from Discord, clear stale DB record
            logger.info(
                f"Forum {forum_data['forum_id']} was deleted from Discord, "
                f"clearing DB record for user {user_id}"
            )
            await self.pool.execute(
                "DELETE FROM user_inventory_forums WHERE user_id = $1", user_id
            )

        # Ensure user exists in users table first
        await self.pool.execute(
            """
            INSERT INTO users (id, current_room)
            SELECT $1, (SELECT id FROM rooms WHERE is_default = TRUE)
            WHERE NOT EXISTS (SELECT 1 FROM users WHERE id = $1)
            """,
            user_id,
        )

        # Permissions: only owner can see and reply to threads (not create)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages_in_threads=True,
                create_public_threads=False,
                send_messages=False,
            ),
        }

        forum = await category.create_forum(
            name=forum_name,
            topic=f"Personal inventory for {member.display_name}",
            overwrites=overwrites,
        )

        # Store in database
        await self.pool.execute(
            """
            INSERT INTO user_inventory_forums (user_id, forum_id, category_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE SET forum_id = $2, category_id = $3
            """,
            user_id,
            forum.id,
            category.id,
        )

        logger.info(f"Created inventory forum '{forum_name}' for user {user_id}")
        return forum

    async def _create_inventory_thread(
        self, guild: discord.Guild, instance: EntityInstance
    ) -> None:
        """Idempotent: create inventory thread for a picked-up item if not exists.

        Args:
            guild: Discord guild
            instance: The entity instance that was picked up
        """
        if instance.owner_id is None:
            return

        # Check if thread already exists in database
        row = await self.pool.fetchrow(
            "SELECT discord_thread_id FROM entity_instances WHERE id = $1",
            instance.instance_id,
        )
        if row and row["discord_thread_id"] is not None:
            # Verify thread still exists in Discord
            existing_thread = guild.get_thread(row["discord_thread_id"])
            if existing_thread is not None:
                # Thread already exists - idempotent noop
                return
            # Thread was deleted from Discord, clear stale reference and recreate
            logger.info(
                f"Thread {row['discord_thread_id']} was deleted from Discord, "
                f"recreating for instance {instance.instance_id}"
            )

        # Ensure user has an inventory forum
        forum = await self._ensure_user_forum(guild, instance.owner_id)
        if forum is None:
            return

        # Render description using LookCommand
        description = await self._render_on_look(instance)

        thread: discord.Thread | None = None
        try:
            thread, message = await forum.create_thread(
                name=instance.entity.name,
                content=description or f"You have a {instance.entity.name}.",
            )

            # Store thread ID and description message ID on instance
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
            logger.error(f"Failed to store thread ID, deleting orphaned thread: {e}")
            if thread:
                with contextlib.suppress(discord.HTTPException):
                    await thread.delete()

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
