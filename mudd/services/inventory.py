"""Inventory service for managing per-user inventory forum channels."""

import contextlib
import logging
from dataclasses import dataclass
from uuid import UUID

import asyncpg
import discord

from mudd.models.entity import EntityInstance as ModelEntityInstance
from mudd.services.currency import CurrencyService
from mudd.services.entity import EntityInstance, EntityService
from mudd.services.rendering import RenderingService

logger = logging.getLogger(__name__)

INVENTORY_CATEGORY_NAME = "Inventory"


def _find_inventory_forums_by_name(
    guild: discord.Guild,
    category: discord.CategoryChannel,
    forum_name: str,
) -> list[discord.ForumChannel]:
    """Find all forum channels with the given name in the category.

    Used for duplicate detection during sync recovery when the database
    loses track of existing Discord forums.

    Note: We search guild.forums instead of category.channels because
    Discord.py's CategoryChannel.channels doesn't include ForumChannels.

    Args:
        guild: The Discord guild to search
        category: The Inventory category to filter by
        forum_name: Expected forum name (e.g., "inventory-{braille_user_id}")

    Returns:
        List of matching forums sorted by ID (oldest first).
    """
    matches = [
        forum
        for forum in guild.forums
        if forum.category_id == category.id and forum.name == forum_name
    ]
    matches.sort(key=lambda ch: ch.id)
    return matches


def get_inventory_forum_name(username: str) -> str:
    """Get the forum channel name for a user's inventory."""
    return f"{username}-inventory"


# Legacy base62 encoding for migration
_BASE62_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _encode_base62_legacy(num: int) -> str:
    """Legacy base62 encoding for migration purposes."""
    if num == 0:
        return "0"
    result = []
    while num:
        result.append(_BASE62_CHARS[num % 62])
        num //= 62
    return "".join(reversed(result))


def _get_legacy_forum_name(user_id: int) -> str:
    """Get the legacy base62 forum name for migration."""
    return f"inventory-{_encode_base62_legacy(user_id)}"


def _find_legacy_forums(
    guild: discord.Guild,
    category: discord.CategoryChannel,
    user_id: int,
) -> list[discord.ForumChannel]:
    """Find forums with legacy base62 names for migration.

    Discord lowercases channel names, so we match case-insensitively.
    """
    legacy_name_lower = _get_legacy_forum_name(user_id).lower()
    matches = [
        forum
        for forum in guild.forums
        if forum.category_id == category.id and forum.name.lower() == legacy_name_lower
    ]
    matches.sort(key=lambda ch: ch.id)
    return matches


@dataclass(frozen=True)
class UserInventoryForum:
    """User's inventory forum data from database."""

    user_id: int
    forum_id: int
    category_id: int


@dataclass(frozen=True)
class DropTarget:
    """Where an item goes when removed from inventory."""

    room: str
    container_entity_id: str | None = None


@dataclass(frozen=True)
class InventoryResult:
    """Result of an inventory operation."""

    success: bool
    instance_id: UUID | None = None
    thread: discord.Thread | None = None
    error: str | None = None


class InventoryService:
    """Manages per-user inventory forum channels and item threads.

    Each user gets a private forum channel in the Inventory category.
    When items are taken, a thread is created in the forum.
    When items are dropped, the thread is deleted.

    Usage:
        service = InventoryService(pool, entity_service, rendering_service)
        await service.sync_user_forums(guild)
        await service.ensure_user_forum(guild, user_id)
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        entity_service: EntityService,
        rendering_service: RenderingService | None = None,
    ) -> None:
        self._pool = pool
        self._entity_service = entity_service
        self._rendering = rendering_service
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

        Handles sync recovery: if the database loses track of an existing
        Discord forum (e.g., after DB reset), searches Discord by name
        and recovers the existing forum instead of creating a duplicate.

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

        # Ensure category exists first (needed for both recovery and creation)
        category = await self.ensure_inventory_category(guild)
        forum_name = get_inventory_forum_name(member.name)

        # Check database first
        forum_data = await self.get_user_forum_from_db(user_id)
        if forum_data:
            # Verify forum still exists in Discord
            forum = guild.get_channel(forum_data.forum_id)
            if forum and isinstance(forum, discord.ForumChannel):
                # Check if name needs migration to Braille format
                if forum.name != forum_name:
                    try:
                        old_name = forum.name
                        await forum.edit(name=forum_name)
                        logger.info(
                            f"Migrated forum name '{old_name}' -> '{forum_name}' "
                            f"for user {user_id}"
                        )
                    except discord.HTTPException as e:
                        logger.error(
                            f"Failed to rename forum {forum.id} to '{forum_name}': {e}"
                        )
                return forum
            # Forum was deleted from Discord, clear stale DB record
            logger.info(
                f"Forum {forum_data.forum_id} was deleted from Discord, "
                f"clearing DB record for user {user_id}"
            )
            await self._pool.execute(
                "DELETE FROM user_inventory_forums WHERE user_id = $1", user_id
            )

        # DB doesn't know about a forum - search Discord for existing forums
        # This handles sync recovery after DB reset
        existing_forums = _find_inventory_forums_by_name(guild, category, forum_name)

        if existing_forums:
            # Keep oldest forum (smallest ID), delete duplicates
            forum = existing_forums[0]

            for duplicate in existing_forums[1:]:
                try:
                    await duplicate.delete(
                        reason="Duplicate inventory forum cleanup during sync"
                    )
                    logger.info(
                        f"Deleted duplicate inventory forum '{forum_name}' "
                        f"(ID: {duplicate.id})"
                    )
                except discord.HTTPException as e:
                    logger.error(
                        f"Failed to delete duplicate forum {duplicate.id}: {e}"
                    )

            # Ensure user exists in users table
            await self._pool.execute(
                """
                INSERT INTO users (id, current_room)
                SELECT $1, (SELECT id FROM rooms WHERE is_default = TRUE)
                WHERE NOT EXISTS (SELECT 1 FROM users WHERE id = $1)
                """,
                user_id,
            )

            # Update DB to track the recovered forum
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

            logger.info(
                f"Recovered existing inventory forum '{forum_name}' "
                f"(ID: {forum.id}) for user {user_id}"
            )
            return forum

        # No new-style forum found - check for legacy base62-named forums
        legacy_forums = _find_legacy_forums(guild, category, user_id)

        if legacy_forums:
            # Keep oldest forum (smallest ID), delete duplicates
            forum = legacy_forums[0]

            for duplicate in legacy_forums[1:]:
                try:
                    await duplicate.delete(
                        reason="Duplicate legacy inventory forum cleanup during sync"
                    )
                    logger.info(
                        f"Deleted duplicate legacy inventory forum (ID: {duplicate.id})"
                    )
                except discord.HTTPException as e:
                    logger.error(
                        f"Failed to delete duplicate legacy forum {duplicate.id}: {e}"
                    )

            # Migrate forum name from legacy base62 to Braille
            old_name = forum.name
            try:
                await forum.edit(name=forum_name)
                logger.info(
                    f"Migrated legacy forum '{old_name}' -> '{forum_name}' "
                    f"for user {user_id}"
                )
            except discord.HTTPException as e:
                logger.error(
                    f"Failed to rename legacy forum {forum.id} to '{forum_name}': {e}"
                )

            # Ensure user exists in users table
            await self._pool.execute(
                """
                INSERT INTO users (id, current_room)
                SELECT $1, (SELECT id FROM rooms WHERE is_default = TRUE)
                WHERE NOT EXISTS (SELECT 1 FROM users WHERE id = $1)
                """,
                user_id,
            )

            # Update DB to track the migrated forum
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

            return forum

        # No existing forum found - create new one

        # Ensure user exists in users table first
        await self._pool.execute(
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

        Creates missing forums for existing members. Handles sync recovery
        when DB loses track of existing Discord forums (e.g., after DB reset).
        Prunes orphan threads that don't correspond to inventory items.

        Does NOT delete forums for members who left (preserves inventory).

        Args:
            guild: Discord guild

        Returns:
            Stats dict with keys:
            - 'created': New forums created
            - 'recovered': Existing Discord forums recovered after DB lost track
            - 'migrated': Legacy base62-named forums renamed to Braille
            - 'existing': Forums already tracked in DB
            - 'fixed': Permissions corrected
            - 'threads_pruned': Orphan threads deleted
            - 'errors': Failed operations
        """
        stats = {
            "created": 0,
            "recovered": 0,
            "migrated": 0,
            "existing": 0,
            "fixed": 0,
            "threads_pruned": 0,
            "errors": 0,
        }

        # Ensure category exists first
        category = await self.ensure_inventory_category(guild)

        for member in guild.members:
            if member.bot:
                continue

            try:
                forum_data = await self.get_user_forum_from_db(member.id)
                forum: discord.ForumChannel | None = None

                if forum_data:
                    # Verify it still exists
                    channel = guild.get_channel(forum_data.forum_id)
                    if channel and isinstance(channel, discord.ForumChannel):
                        forum = channel
                        forum_name = get_inventory_forum_name(member.name)

                        # Migrate legacy name to Braille if needed
                        if forum.name != forum_name:
                            try:
                                old_name = forum.name
                                await forum.edit(name=forum_name)
                                logger.info(
                                    f"Migrated forum name '{old_name}' -> "
                                    f"'{forum_name}' for user {member.id}"
                                )
                                stats["migrated"] += 1
                            except discord.HTTPException as e:
                                logger.error(f"Failed to rename forum {forum.id}: {e}")

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
                    # If forum was deleted, fall through to ensure_user_forum

                if forum is None:
                    # Check if forum exists in Discord but not DB (recovery case)
                    forum_name = get_inventory_forum_name(member.name)
                    existing_forums = _find_inventory_forums_by_name(
                        guild, category, forum_name
                    )
                    legacy_forums = _find_legacy_forums(guild, category, member.id)
                    will_recover = len(existing_forums) > 0
                    will_migrate = len(legacy_forums) > 0 and not will_recover

                    # Create, recover, or migrate forum
                    forum = await self.ensure_user_forum(guild, member.id)
                    if forum:
                        if will_recover:
                            stats["recovered"] += 1
                        elif will_migrate:
                            stats["migrated"] += 1
                        else:
                            stats["created"] += 1

                # Prune orphan threads from the forum
                if forum:
                    prune_stats = await self.prune_orphan_threads(guild, member.id)
                    stats["threads_pruned"] += prune_stats["pruned"]

            except discord.HTTPException as e:
                logger.error(f"Failed to sync inventory forum for {member.id}: {e}")
                stats["errors"] += 1

        logger.info(f"Inventory forum sync for {guild.name}: {stats}")
        return stats

    async def prune_orphan_threads(
        self, guild: discord.Guild, user_id: int
    ) -> dict[str, int]:
        """Delete threads that don't correspond to inventory items.

        Handles cleanup of orphan threads that can result from:
        - DB reset while Discord threads persist
        - Manual thread creation by users (if permissions allow)
        - Failed item deletions that removed DB record but not thread

        Args:
            guild: Discord guild
            user_id: Discord user ID

        Returns:
            Stats dict with keys: 'pruned' (deleted threads), 'kept' (valid threads)
        """
        stats = {"pruned": 0, "kept": 0}

        # Get user's forum from DB
        forum_data = await self.get_user_forum_from_db(user_id)
        if forum_data is None:
            return stats

        forum = guild.get_channel(forum_data.forum_id)
        if not forum or not isinstance(forum, discord.ForumChannel):
            return stats

        # Query all valid thread IDs for this user's inventory items
        rows = await self._pool.fetch(
            """
            SELECT discord_thread_id FROM entity_instances
            WHERE owner_id = $1 AND discord_thread_id IS NOT NULL
            """,
            user_id,
        )
        valid_thread_ids = {row["discord_thread_id"] for row in rows}

        # Iterate over forum's threads and prune orphans
        # Forum threads include both active and archived threads
        for thread in forum.threads:
            if thread.id in valid_thread_ids:
                stats["kept"] += 1
                continue

            # Orphan thread - delete it
            try:
                await thread.delete()
                stats["pruned"] += 1
                logger.info(
                    f"Pruned orphan thread '{thread.name}' (ID: {thread.id}) "
                    f"from inventory forum for user {user_id}"
                )
            except discord.HTTPException as e:
                logger.error(f"Failed to prune thread {thread.id}: {e}")

        return stats

    async def create_item_thread(
        self,
        guild: discord.Guild,
        user_id: int,
        instance_id: UUID,
        item_name: str,
        item_description: str,
        pinned: bool = False,
    ) -> discord.Thread | None:
        """Create a thread for an inventory item.

        The starter message contains the item's description (rendered on_look).
        The message ID is stored in discord_description_msg_id for sync updates.

        Args:
            guild: Discord guild
            user_id: Owner's Discord ID
            instance_id: Entity instance UUID
            item_name: Name for the thread (display name with rarity emoji)
            item_description: Item description (rendered on_look output)
            pinned: Whether to pin the thread in the forum (default False)

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

            # Store thread ID and description message ID on instance
            await self._pool.execute(
                """UPDATE entity_instances
                SET discord_thread_id = $1, discord_description_msg_id = $2
                WHERE id = $3""",
                thread.id,
                message.id,
                instance_id,
            )

            # Pin thread if requested (e.g., for wallet threads)
            if pinned:
                await thread.edit(pinned=True)

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

    async def create_item_thread_v2(
        self,
        guild: discord.Guild,
        instance: ModelEntityInstance,
        description: str,
        pinned: bool = False,
    ) -> discord.Thread | None:
        """Create thread for inventory item using new model type.

        Takes EntityInstance from mudd.models instead of primitives.

        Args:
            guild: Discord guild
            instance: Entity instance from mudd.models
            description: Pre-rendered item description
            pinned: Whether to pin the thread (default False)

        Returns:
            The created thread, or None if failed
        """
        if instance.owner_id is None:
            return None
        return await self.create_item_thread(
            guild,
            instance.owner_id,
            instance.instance_id,
            instance.entity.name,
            description,
            pinned,
        )

    async def delete_item_thread_v2(
        self,
        guild: discord.Guild,
        instance: ModelEntityInstance,
    ) -> bool:
        """Delete thread for inventory item using new model type.

        Args:
            guild: Discord guild
            instance: Entity instance from mudd.models

        Returns:
            True if deleted, False otherwise
        """
        return await self.delete_item_thread(guild, instance.instance_id)

    async def _create_inventory_thread(
        self,
        guild: discord.Guild,
        user_id: int,
        instance_id: UUID,
        pinned: bool = False,
    ) -> discord.Thread | None:
        """Render description and create thread for inventory item.

        Fetches user's balance to make it available in all entity templates.

        Args:
            guild: Discord guild
            user_id: Owner's Discord ID
            instance_id: Entity instance UUID
            pinned: Whether to pin the thread

        Returns:
            Created thread, or None on failure
        """
        instance = await self._entity_service.get_entity_instance(instance_id)
        if instance is None:
            logger.error("Instance %s not found for thread creation", instance_id)
            return None

        entity = instance.entity

        # Fetch balance for template context (available to all entities)
        balance = await self._pool.fetchval(
            "SELECT balance FROM currency_accounts WHERE user_id = $1",
            user_id,
        )
        balance_str = f"\u00a5{balance:,}" if balance else "\u00a50"

        if self._rendering:
            description = await self._rendering.render_entity_on_look(
                instance,
                self._entity_service,
                None,
                balance_str,
                include_heading=False,
            )
        else:
            description = "You see nothing special."

        thread = await self.create_item_thread(
            guild, user_id, instance_id, entity.display_name, description, pinned
        )
        if thread is None:
            logger.warning("Failed to create thread for item %s", entity.id)

        return thread

    async def grant_item(
        self,
        guild: discord.Guild,
        user_id: int,
        entity_id: str,
        pinned: bool = False,
    ) -> InventoryResult:
        """Create new entity instance directly in inventory.

        Used by effects.grant() and effects.grant_random().

        Args:
            guild: Discord guild
            user_id: Owner's Discord ID
            entity_id: ID of entity to create
            pinned: Whether to pin the thread (e.g., for wallets)

        Returns:
            InventoryResult with success/failure info
        """
        # Verify entity exists
        entity = await self._entity_service.get_entity(entity_id)
        if entity is None:
            return InventoryResult(
                success=False, error=f"Entity '{entity_id}' not found"
            )

        # Create instance in user's inventory
        instance_id = await self._pool.fetchval(
            """INSERT INTO entity_instances (entity_id, owner_id)
            VALUES ($1, $2) RETURNING id""",
            entity_id,
            user_id,
        )
        if instance_id is None:
            return InventoryResult(
                success=False, error=f"Failed to create instance for {entity_id}"
            )

        # Create thread via shared path
        return await self.add_to_inventory(guild, user_id, instance_id, pinned=pinned)

    async def add_to_inventory(
        self,
        guild: discord.Guild,
        user_id: int,
        instance_id: UUID,
        source_room: str | None = None,
        pinned: bool = False,
    ) -> InventoryResult:
        """Move entity instance to inventory with thread creation.

        Handles recursive container contents: when picking up a container,
        all its contents move to inventory with it.

        Args:
            guild: Discord guild
            user_id: Owner's Discord ID
            instance_id: Entity instance UUID
            source_room: For atomic validation - ensures item is still in room
            pinned: Whether to pin the thread (e.g., for wallets)

        Returns:
            InventoryResult with success/failure info
        """
        # Get the instance first to get entity info (for recursive container handling)
        instance = await self._entity_service.get_entity_instance(instance_id)
        if instance is None:
            return InventoryResult(success=False, error="The item is no longer there.")

        entity = instance.entity

        # Move the item instance to the user's inventory
        # Clear spawning_pool_id so the pool can spawn a replacement
        if source_room:
            # Atomic validation - ensures item is still in expected room
            result = await self._pool.execute(
                """UPDATE entity_instances
                SET room = NULL, owner_id = $1, player_dropped = FALSE,
                    container_entity_id = NULL, is_world_instance = FALSE,
                    spawning_pool_id = NULL
                WHERE id = $2 AND room = $3""",
                user_id,
                instance_id,
                source_room,
            )
            if result == "UPDATE 0":
                return InventoryResult(
                    success=False, error="The item is no longer there."
                )

            # Recursive container pickup: move all contents with the container
            await self._pool.execute(
                """UPDATE entity_instances
                SET room = NULL, owner_id = $1,
                    player_dropped = FALSE, is_world_instance = FALSE,
                    spawning_pool_id = NULL
                WHERE container_entity_id = $2 AND room = $3""",
                user_id,
                entity.id,
                source_room,
            )
        else:
            # No source room validation - just move to inventory
            await self._pool.execute(
                """UPDATE entity_instances
                SET room = NULL, owner_id = $1, player_dropped = FALSE,
                    container_entity_id = NULL, is_world_instance = FALSE,
                    spawning_pool_id = NULL
                WHERE id = $2""",
                user_id,
                instance_id,
            )

        # Create thread with rendered description (includes balance)
        thread = await self._create_inventory_thread(
            guild, user_id, instance_id, pinned
        )

        return InventoryResult(success=True, instance_id=instance_id, thread=thread)

    async def remove_from_inventory(
        self,
        guild: discord.Guild,
        user_id: int,
        instance_id: UUID,
        entity_id: str,
        target: DropTarget,
    ) -> InventoryResult:
        """Move item from inventory to room.

        Handles recursive container contents: when dropping a container,
        all its contents move to the room with it.

        Does NOT delete thread - caller must call delete_item_thread() after response.
        This allows dropping from inventory threads without "Unknown Channel" errors.

        Args:
            guild: Discord guild
            user_id: Owner's Discord ID
            instance_id: Entity instance UUID
            entity_id: Entity ID (for recursive container handling)
            target: DropTarget specifying room and optional container

        Returns:
            InventoryResult with success/failure info
        """
        # Move instance from inventory to room (or container)
        result = await self._pool.execute(
            """UPDATE entity_instances
            SET room = $1, owner_id = NULL, player_dropped = TRUE,
                container_entity_id = $4, is_world_instance = FALSE
            WHERE id = $2 AND owner_id = $3""",
            target.room,
            instance_id,
            user_id,
            target.container_entity_id,
        )
        if result == "UPDATE 0":
            return InventoryResult(success=False, error="You no longer have that item.")

        # Recursive container drop: move all contents to room with the container
        # Contents keep their container_entity_id link so they stay inside
        await self._pool.execute(
            """UPDATE entity_instances
            SET room = $1, owner_id = NULL
            WHERE container_entity_id = $2 AND owner_id = $3""",
            target.room,
            entity_id,
            user_id,
        )

        return InventoryResult(success=True, instance_id=instance_id)

    async def destroy_instance(
        self,
        guild: discord.Guild,
        instance_id: UUID,
    ) -> bool:
        """Delete entity instance and its thread (if any).

        Works on any instance (room or inventory). Safe to call even if no thread.

        Args:
            guild: Discord guild
            instance_id: Entity instance UUID

        Returns:
            True if instance was deleted, False otherwise
        """
        # Delete inventory thread first (if exists) - must happen before DB delete
        await self.delete_item_thread(guild, instance_id)

        result = await self._pool.execute(
            "DELETE FROM entity_instances WHERE id = $1",
            instance_id,
        )
        return result == "DELETE 1"

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

    async def sync_inventory_descriptions(
        self,
        guild: discord.Guild,
        rendering_service: RenderingService,
        currency_service: CurrencyService,
    ) -> dict[str, int]:
        """Sync inventory thread descriptions for all users.

        Updates the first message in each inventory thread to reflect
        current entity on_look rendering. This keeps item descriptions
        up-to-date when entity definitions change.

        Args:
            guild: Discord guild
            rendering_service: Service to render entity descriptions
            currency_service: Service to get balance for wallet entities

        Returns:
            Stats dict with 'updated', 'unchanged', 'skipped', 'errors' counts
        """
        stats = {"updated": 0, "unchanged": 0, "skipped": 0, "errors": 0}

        # Query all inventory items with thread and message IDs
        rows = await self._pool.fetch(
            """
            SELECT ei.id, ei.entity_id, ei.owner_id,
                   ei.discord_thread_id, ei.discord_description_msg_id
            FROM entity_instances ei
            WHERE ei.owner_id IS NOT NULL
              AND ei.discord_thread_id IS NOT NULL
              AND ei.discord_description_msg_id IS NOT NULL
            """
        )

        for row in rows:
            try:
                thread_id = row["discord_thread_id"]
                msg_id = row["discord_description_msg_id"]
                instance_id = row["id"]

                # Get thread from guild
                thread = guild.get_thread(thread_id)
                if not thread:
                    stats["skipped"] += 1
                    continue

                # Get entity instance for rendering
                instance = await self._entity_service.get_entity_instance(instance_id)
                if not instance:
                    stats["skipped"] += 1
                    continue

                # Fetch balance for wallet templates
                balance_str = ""
                if instance.entity.id == "wallet" and instance.owner_id:
                    balance = await currency_service.get_balance(instance.owner_id)
                    balance_str = f"¥{balance:,}" if balance else "¥0"

                # Render description (room=None for inventory, no heading since title
                # already shows item name)
                new_description = await rendering_service.render_entity_on_look(
                    instance,
                    self._entity_service,
                    None,
                    balance_str,
                    include_heading=False,
                )

                # Fetch and compare message
                try:
                    message = await thread.fetch_message(msg_id)
                    if message.content != new_description:
                        await message.edit(content=new_description)
                        stats["updated"] += 1
                        logger.debug(
                            f"Updated description for instance {instance_id} "
                            f"in thread {thread_id}"
                        )
                    else:
                        stats["unchanged"] += 1
                except discord.NotFound:
                    stats["skipped"] += 1
                    logger.warning(
                        f"Description message {msg_id} not found in thread {thread_id}"
                    )
                except discord.HTTPException as e:
                    stats["errors"] += 1
                    logger.error(f"Failed to update description message {msg_id}: {e}")

            except Exception:
                logger.exception(f"Failed to sync description for instance {row['id']}")
                stats["errors"] += 1

        return stats
