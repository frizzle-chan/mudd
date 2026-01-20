"""Inventory service for managing per-user inventory forum channels."""

import contextlib
import logging
from dataclasses import dataclass
from uuid import UUID

import asyncpg
import discord

from mudd.services.entity import EntityInstance, EntityService

logger = logging.getLogger(__name__)

# Base62 encoding for shorter forum names
BASE62_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

INVENTORY_CATEGORY_NAME = "Inventory"


def encode_base62(num: int) -> str:
    """Encode an integer to base62 string.

    Used to shorten Discord user IDs (18-19 digits) to ~11 characters
    for more readable inventory forum names.

    Args:
        num: Non-negative integer to encode

    Raises:
        ValueError: If num is negative
    """
    if num < 0:
        raise ValueError("Cannot encode negative numbers to base62")
    if num == 0:
        return "0"
    result = []
    while num:
        result.append(BASE62_CHARS[num % 62])
        num //= 62
    return "".join(reversed(result))


def get_inventory_forum_name(user_id: int) -> str:
    """Get the forum channel name for a user's inventory."""
    return f"{encode_base62(user_id)}-inventory"


@dataclass(frozen=True)
class UserInventoryForum:
    """User's inventory forum data from database."""

    user_id: int
    forum_id: int
    category_id: int


class InventoryService:
    """Manages per-user inventory forum channels and item threads.

    Each user gets a private forum channel in the Inventory category.
    When items are taken, a thread is created in the forum.
    When items are dropped, the thread is deleted.

    Usage:
        service = InventoryService(pool, entity_service)
        await service.sync_user_forums(guild)
        await service.ensure_user_forum(guild, user_id)
    """

    def __init__(self, pool: asyncpg.Pool, entity_service: EntityService) -> None:
        self._pool = pool
        self._entity_service = entity_service
        # Cache category ID per guild to avoid repeated lookups
        self._category_cache: dict[int, int] = {}  # guild_id -> category_id

    async def ensure_inventory_category(
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

    async def get_user_forum_from_db(self, user_id: int) -> UserInventoryForum | None:
        """Get user's inventory forum info from database.

        Args:
            user_id: Discord user ID

        Returns:
            UserInventoryForum if exists, None otherwise
        """
        row = await self._pool.fetchrow(
            """SELECT user_id, forum_id, category_id
            FROM user_inventory_forums WHERE user_id = $1""",
            user_id,
        )
        if row is None:
            return None
        return UserInventoryForum(
            user_id=row["user_id"],
            forum_id=row["forum_id"],
            category_id=row["category_id"],
        )

    async def ensure_user_forum(
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

        # Check database first
        forum_data = await self.get_user_forum_from_db(user_id)
        if forum_data:
            # Verify forum still exists
            forum = guild.get_channel(forum_data.forum_id)
            if forum and isinstance(forum, discord.ForumChannel):
                return forum
            # Forum was deleted, remove from DB and recreate
            logger.info(
                f"Forum {forum_data.forum_id} was deleted, "
                f"recreating for user {user_id}"
            )
            await self._pool.execute(
                "DELETE FROM user_inventory_forums WHERE user_id = $1", user_id
            )

        # Ensure user exists in users table first
        await self._pool.execute(
            """
            INSERT INTO users (id, current_room)
            SELECT $1, (SELECT id FROM rooms WHERE is_default = TRUE)
            WHERE NOT EXISTS (SELECT 1 FROM users WHERE id = $1)
            """,
            user_id,
        )

        # Create forum
        category = await self.ensure_inventory_category(guild)
        forum_name = get_inventory_forum_name(user_id)

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
        await self._pool.execute(
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

    async def sync_user_forums(self, guild: discord.Guild) -> dict[str, int]:
        """Sync inventory forums for all guild members.

        Creates missing forums for existing members.
        Does NOT delete forums for members who left (preserves inventory).

        Args:
            guild: Discord guild

        Returns:
            Stats dict with keys: 'created' (new forums), 'existing' (already
            had forum), 'fixed' (permissions corrected), 'errors' (failed)
        """
        stats = {"created": 0, "existing": 0, "fixed": 0, "errors": 0}

        # Ensure category exists first
        await self.ensure_inventory_category(guild)

        for member in guild.members:
            if member.bot:
                continue

            try:
                forum_data = await self.get_user_forum_from_db(member.id)
                if forum_data:
                    # Verify it still exists
                    forum = guild.get_channel(forum_data.forum_id)
                    if forum and isinstance(forum, discord.ForumChannel):
                        # Fix permissions if needed (remove thread creation ability)
                        overwrites = forum.overwrites_for(member)
                        if overwrites.create_public_threads is not False:
                            await forum.set_permissions(
                                member,
                                view_channel=True,
                                send_messages_in_threads=True,
                                create_public_threads=False,
                                send_messages=False,
                            )
                            stats["fixed"] += 1
                        stats["existing"] += 1
                        continue

                # Create forum (handles DB cleanup if needed)
                forum = await self.ensure_user_forum(guild, member.id)
                if forum:
                    stats["created"] += 1

            except discord.HTTPException as e:
                logger.error(f"Failed to sync inventory forum for {member.id}: {e}")
                stats["errors"] += 1

        logger.info(f"Inventory forum sync for {guild.name}: {stats}")
        return stats

    async def create_item_thread(
        self,
        guild: discord.Guild,
        user_id: int,
        instance_id: UUID,
        item_name: str,
        item_description: str,
    ) -> discord.Thread | None:
        """Create a thread for an inventory item.

        Args:
            guild: Discord guild
            user_id: Owner's Discord ID
            instance_id: Entity instance UUID
            item_name: Name for the thread
            item_description: Content for the starter message

        Returns:
            The created thread, or None if failed
        """
        forum = await self.ensure_user_forum(guild, user_id)
        if forum is None:
            return None

        thread: discord.Thread | None = None
        try:
            thread, message = await forum.create_thread(
                name=item_name,
                content=item_description or f"You have a {item_name}.",
            )

            # Store thread ID on instance
            await self._pool.execute(
                "UPDATE entity_instances SET discord_thread_id = $1 WHERE id = $2",
                thread.id,
                instance_id,
            )

            logger.info(f"Created thread '{item_name}' for instance {instance_id}")
            return thread

        except discord.HTTPException as e:
            logger.error(f"Failed to create item thread: {e}")
            return None
        except asyncpg.PostgresError as e:
            logger.error(f"Failed to store thread ID, deleting orphaned thread: {e}")
            if thread:
                with contextlib.suppress(discord.HTTPException):
                    await thread.delete()
            return None

    async def delete_item_thread(self, guild: discord.Guild, instance_id: UUID) -> bool:
        """Delete the thread for an inventory item.

        Args:
            guild: Discord guild
            instance_id: Entity instance UUID

        Returns:
            True if deleted or thread was already gone (DB reference cleared),
            False if instance has no thread reference or Discord deletion failed
        """
        # Get thread ID from database
        row = await self._pool.fetchrow(
            "SELECT discord_thread_id FROM entity_instances WHERE id = $1",
            instance_id,
        )
        if row is None or row["discord_thread_id"] is None:
            return False

        thread_id = row["discord_thread_id"]

        # Delete Discord thread first (before DB update to avoid orphaning)
        thread = guild.get_thread(thread_id)
        if thread:
            try:
                await thread.delete()
                logger.info(f"Deleted thread {thread_id} for instance {instance_id}")
            except discord.HTTPException as e:
                logger.error(f"Failed to delete thread {thread_id}: {e}")
                return False

        # Only clear DB reference after successful Discord deletion
        await self._pool.execute(
            "UPDATE entity_instances SET discord_thread_id = NULL WHERE id = $1",
            instance_id,
        )

        return True

    async def get_instance_by_thread_id(self, thread_id: int) -> EntityInstance | None:
        """Get entity instance by its Discord thread ID.

        Args:
            thread_id: Discord thread ID

        Returns:
            EntityInstance if found, None otherwise
        """
        row = await self._pool.fetchrow(
            "SELECT id FROM entity_instances WHERE discord_thread_id = $1",
            thread_id,
        )
        if row is None:
            return None

        return await self._entity_service.get_entity_instance(row["id"])

    async def get_thread_item(
        self, channel: discord.abc.GuildChannel | discord.Thread | None
    ) -> EntityInstance | None:
        """Check if channel is an inventory thread and return the item.

        Used by autocomplete to detect inventory context and limit
        suggestions to just the thread's item.

        Args:
            channel: The interaction channel

        Returns:
            EntityInstance if in an inventory thread, None otherwise
        """
        if not isinstance(channel, discord.Thread):
            return None
        if not isinstance(channel.parent, discord.ForumChannel):
            return None

        # Check if this thread belongs to an inventory item
        return await self.get_instance_by_thread_id(channel.id)
