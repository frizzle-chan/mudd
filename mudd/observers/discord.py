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
)
from mudd.models.entity import EntityInstance

logger = logging.getLogger(__name__)

INVENTORY_CATEGORY_NAME = "Inventory"


def _get_inventory_forum_name(username: str) -> str:
    """Get the forum channel name for a user's inventory."""
    return f"{username}-inventory"


class DiscordReconciler:
    """Observes model changes and reconciles Discord state.

    Handles Discord thread management when entities change state:
    - "picked_up": Creates inventory thread for the item
    - "dropped": Deletes inventory thread
    - "destroyed": Deletes inventory thread

    The reconciler implements the Observer protocol: notify() is sync
    and queues notifications for async processing. Call flush() after
    sending the response to execute queued Discord operations.

    Usage:
        reconciler = DiscordReconciler(bot, pool)
        instance = instance.with_observers(reconciler)
        new_instance = await instance.move_to_inventory(user)
        await interaction.response.send_message(...)
        await reconciler.flush()  # Execute Discord operations after response
    """

    def __init__(
        self,
        bot: discord.Client,
        pool: asyncpg.Pool,
    ) -> None:
        """Initialize the Discord reconciler.

        Args:
            bot: Discord bot client
            pool: Database connection pool
        """
        self.bot = bot
        self.pool = pool
        self._pending: list[tuple[EntityInstance, str]] = []
        # Cache category ID per guild to avoid repeated lookups
        self._category_cache: dict[int, int] = {}

    def notify(self, event: GameEvent) -> None:
        """Receive notification (sync). Queue for async processing.

        This method is called synchronously by EntityInstance._notify().
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
            # Ignore template signals - they're handled by EffectsObserver

    async def flush(self) -> None:
        """Process queued notifications. Call after response sent.

        Processes all pending events and clears the queue. Safe to call
        multiple times; subsequent calls are no-ops if queue is empty.
        """
        pending = self._pending
        self._pending = []

        for instance, event in pending:
            await self._handle_entity_event(instance, event)

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
        """Create inventory thread for a picked-up item.

        Args:
            guild: Discord guild
            instance: The entity instance that was picked up
        """
        if instance.owner_id is None:
            return

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
        """Delete inventory thread for a dropped/destroyed item.

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

        # Only clear DB reference after successful Discord deletion
        await self.pool.execute(
            """UPDATE entity_instances
            SET discord_thread_id = NULL, discord_description_msg_id = NULL
            WHERE id = $1""",
            instance.instance_id,
        )
