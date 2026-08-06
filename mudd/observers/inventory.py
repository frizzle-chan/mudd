"""Inventory reconciler for Discord state."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from io import BytesIO
from typing import ClassVar, cast

import asyncpg
import discord

from mudd.events import (
    BalanceChangedEvent,
    EntityDestroyedEvent,
    EntityDroppedEvent,
    EntityPickedUpEvent,
    GameEvent,
    InventorySyncEvent,
    UserLeftEvent,
)
from mudd.map.rendering import generate_map_image
from mudd.models.entity import EntityInstance
from mudd.models.inventory_forum import UserInventoryForum
from mudd.models.room import InventoryThread, Room
from mudd.models.user import STARTING_BALANCE, User
from mudd.observers.effects import EffectsObserver
from mudd.observers.inventory_dedup import ForumCandidate, plan_dedup
from mudd.utils.categories import (
    CategoryOverwrites,
    create_with_overflow,
    matching_categories,
)
from mudd.utils.discord import fetch_forum, fetch_thread, normalize_channel_name
from mudd.views import ViewEntity

logger = logging.getLogger(__name__)

INVENTORY_CATEGORY_NAME = "Inventory"
MAP_ENTITY_ID = "map"


def _new_forum_stats() -> dict[str, int]:
    """Zeroed inventory forum sync counters."""
    return {
        "created": 0,
        "recovered": 0,
        "existing": 0,
        "renamed": 0,
        "fixed": 0,
        "threads_pruned": 0,
        "forums_pruned": 0,
        "errors": 0,
    }


def _get_inventory_forum_name(username: str) -> str:
    """Get the forum channel name for a user's inventory."""
    return normalize_channel_name(username, "inventory")


def _format_transaction_message(event: BalanceChangedEvent) -> str:
    """Format a transaction notification message for a wallet thread."""
    sign = "+" if event.delta >= 0 else "-"
    abs_amount = abs(event.delta)
    balance = event.new_balance
    return f"{sign}\u00a4{abs_amount:,} | {event.memo} | Balance: \u00a4{balance:,}"


class InventoryReconciler:
    """Reconciles inventory forums, threads, wallets, and user departure cleanup.

    Handles:
    - EntityPickedUpEvent: Routes to inventory sync
    - EntityDroppedEvent: Deletes inventory thread
    - EntityDestroyedEvent: Deletes inventory thread
    - BalanceChangedEvent: Routes to inventory sync
    - InventorySyncEvent: Full inventory sync for a user
    - UserLeftEvent: Cleans up inventory forum on departure
    """

    # Serialize inventory work per-user across all reconciler instances
    # to prevent duplicate thread creation from concurrent sync + commands.
    _user_locks: ClassVar[dict[int, asyncio.Lock]] = {}

    @classmethod
    def _get_user_lock(cls, user_id: int) -> asyncio.Lock:
        lock = cls._user_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            cls._user_locks[user_id] = lock
        return lock

    def __init__(
        self,
        bot: discord.Client,
        pool: asyncpg.Pool,
        guild_id: int,
    ) -> None:
        self.bot = bot
        self.pool = pool
        self._guild_id = guild_id
        self._inventory_sync_events: list[InventorySyncEvent] = []
        self._balance_changed_events: list[BalanceChangedEvent] = []
        self._user_left_events: list[UserLeftEvent] = []
        self._entity_drop_events: list[tuple[EntityInstance, int | None]] = []
        # Stats for inventory forum sync
        self._inventory_forum_stats: dict[str, int] = _new_forum_stats()

    def notify(self, event: GameEvent) -> None:
        """Queue inventory-related events for async processing."""
        match event:
            case EntityPickedUpEvent(instance=instance):
                if instance.owner_id:
                    self._inventory_sync_events.append(
                        InventorySyncEvent(
                            guild_id=self._guild_id, user_id=instance.owner_id
                        )
                    )
            case EntityDroppedEvent(instance=instance):
                self._entity_drop_events.append((instance, None))
            case EntityDestroyedEvent(instance=instance, thread_id=thread_id):
                self._entity_drop_events.append((instance, thread_id))
            case BalanceChangedEvent() as evt:
                self._balance_changed_events.append(evt)
                self._inventory_sync_events.append(
                    InventorySyncEvent(guild_id=self._guild_id, user_id=evt.user_id)
                )
            case InventorySyncEvent() as evt:
                self._inventory_sync_events.append(evt)
            case UserLeftEvent() as evt:
                self._user_left_events.append(evt)

    async def flush(self) -> None:
        """Process queued inventory events."""
        inventory_sync_events = self._inventory_sync_events
        self._inventory_sync_events = []
        balance_changed_events = self._balance_changed_events
        self._balance_changed_events = []
        user_left_events = self._user_left_events
        self._user_left_events = []
        entity_drop_events = self._entity_drop_events
        self._entity_drop_events = []

        guild = self.bot.get_guild(self._guild_id)
        if guild is None:
            logger.warning(
                "Guild %d not available, skipping inventory flush", self._guild_id
            )
            return

        # Process inventory sync events (deduplicated by user_id)
        synced_users: set[int] = set()
        for evt in inventory_sync_events:
            if evt.user_id in synced_users:
                continue
            synced_users.add(evt.user_id)
            await self._ensure_user_inventory(guild, evt.user_id)

        # Post transaction notifications after inventory sync
        # (which ensures wallet threads exist)
        for evt in balance_changed_events:
            await self._post_transaction_notification(guild, evt)

        # Process user left events
        for evt in user_left_events:
            await self._handle_user_left(guild, evt)

        # Process entity drop/destroy events
        for instance, thread_id in entity_drop_events:
            await self._delete_inventory_thread(guild, instance, thread_id=thread_id)

    def get_inventory_forum_stats(self) -> dict[str, int]:
        """Get accumulated inventory forum sync stats."""
        return self._inventory_forum_stats.copy()

    def reset_inventory_forum_stats(self) -> None:
        """Reset inventory forum sync stats to zero."""
        self._inventory_forum_stats = _new_forum_stats()

    async def _handle_user_left(
        self, guild: discord.Guild, event: UserLeftEvent
    ) -> None:
        """Handle a user leaving: clean up their inventory forum."""
        self._user_locks.pop(event.user_id, None)
        forum_id = await UserInventoryForum.get_forum_id(self.pool, event.user_id)
        if forum_id:
            forum = guild.get_channel(forum_id)
            if forum:
                try:
                    await forum.delete()
                    logger.info(
                        f"Deleted inventory forum for departing user {event.user_id}"
                    )
                except discord.HTTPException as e:
                    logger.error(
                        f"Failed to delete inventory forum for {event.user_id}: {e}"
                    )

    async def _render_on_look(self, instance: EntityInstance) -> str:
        """Render on_look using LookCommand with EntityModal context."""
        from mudd.commands import LookCommand

        if instance.owner_id is None:
            return "You see nothing special."

        user = await User.get(self.pool, instance.owner_id)
        if user is None:
            return "You see nothing special."

        modal = InventoryThread(
            _pool=self.pool,
            id=f"inventory:{instance.instance_id}",
            entity_instance=instance,
            owner=user,
        )

        effects = EffectsObserver()
        command = LookCommand()
        result = await command.execute(user, modal, effects, instance)

        return result.output

    async def _thread_count(self, forum: discord.ForumChannel) -> int:
        """Count a forum's threads, for deletion-safety decisions.

        ``forum.threads`` caches *active* threads only, so a forum whose
        contents are all archived would otherwise read as empty and become
        eligible for deletion. A single archived thread is enough to make the
        count non-zero — the exact number does not matter once it is > 0.

        On any error, reports 1. Failing closed means an unreadable forum is
        never deleted.
        """
        active = len(forum.threads)
        if active:
            return active
        try:
            async for _ in forum.archived_threads(limit=1):
                return 1
        except discord.HTTPException as e:
            logger.error(
                "Could not list archived threads for forum %d, "
                "treating it as non-empty: %s",
                forum.id,
                e,
            )
            return 1
        return 0

    async def _delete_inventory_thread(
        self,
        guild: discord.Guild,
        instance: EntityInstance,
        *,
        thread_id: int | None = None,
    ) -> None:
        """Idempotent: delete inventory thread for a dropped/destroyed item."""
        if thread_id is None:
            thread_id = await EntityInstance.get_thread_id(
                self.pool, instance.instance_id
            )
        if thread_id is None:
            return

        thread = await fetch_thread(guild, thread_id)
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
            logger.debug(
                f"Thread {thread_id} not found in Discord, clearing DB reference"
            )

        await EntityInstance.clear_thread_ids(self.pool, instance.instance_id)

    async def _prune_orphan_threads(
        self, forum: discord.ForumChannel, user_id: int
    ) -> int:
        """Delete threads that don't correspond to inventory items."""
        valid_thread_ids = await EntityInstance.get_thread_ids_by_owner(
            self.pool, user_id
        )

        pruned = 0
        for thread in forum.threads:
            if thread.id in valid_thread_ids:
                continue

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

        Uses a per-user class-level lock to serialize concurrent calls
        (e.g. sync cog + /buy command) and prevent duplicate thread creation.
        """
        async with self._get_user_lock(user_id):
            await self._ensure_user_inventory_locked(guild, user_id)

    async def _ensure_user_inventory_locked(
        self, guild: discord.Guild, user_id: int
    ) -> None:
        """Inner implementation of _ensure_user_inventory, called under lock."""
        member = guild.get_member(user_id)
        if member is None:
            logger.debug(f"User {user_id} not found in guild {guild.name}")
            return
        if member.bot:
            return

        try:
            forum_name = _get_inventory_forum_name(member.name)

            forum = await self._find_or_create_forum(guild, member, forum_name)
            if forum is None:
                self._inventory_forum_stats["errors"] += 1
                return

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

            user = await User.get_or_create(self.pool, user_id)
            await self._ensure_wallet_thread(guild, user, forum)
            await self._ensure_map_thread(guild, user, forum)

            await self._sync_inventory_threads(guild, user_id, forum)

            pruned = await self._prune_orphan_threads(forum, user_id)
            self._inventory_forum_stats["threads_pruned"] += pruned

        except Exception:
            # Widened from HTTPException: _register_forum_in_db raises
            # RuntimeError and asyncpg errors, which previously escaped and
            # aborted flush() for every remaining user in the pass.
            logger.exception("Failed to ensure inventory for user %d", user_id)
            self._inventory_forum_stats["errors"] += 1

    async def _find_or_create_forum(
        self,
        guild: discord.Guild,
        member: discord.Member,
        forum_name: str,
    ) -> discord.ForumChannel | None:
        """Find the user's forum, recover it, or create one.

        Returns None when this user's forum cannot be resolved this pass; the
        caller counts that as an error and tries again next sync.
        """
        forum_id = await UserInventoryForum.get_forum_id(self.pool, member.id)

        if forum_id:
            try:
                forum = await fetch_forum(guild, forum_id)
            except discord.HTTPException as e:
                # Not a confirmed deletion. Leave the DB record alone and skip
                # this user — falling through to recovery here is what made a
                # transient cache miss destructive.
                logger.error(
                    "Could not resolve inventory forum %d for user %d, "
                    "skipping this pass: %s",
                    forum_id,
                    member.id,
                    e,
                )
                return None

            if forum is not None:
                self._inventory_forum_stats["existing"] += 1
                return forum

            logger.info(
                "Forum %d confirmed deleted from Discord, "
                "clearing DB record for user %d",
                forum_id,
                member.id,
            )
            await UserInventoryForum.delete_by_user(self.pool, member.id)

        recovered = await self._recover_forum(guild, member, forum_name)
        if recovered is not None:
            return recovered

        return await self._create_new_forum(guild, member, forum_name)

    async def _recover_forum(
        self,
        guild: discord.Guild,
        member: discord.Member,
        forum_name: str,
    ) -> discord.ForumChannel | None:
        """Adopt an existing forum matching this user's name, deduping safely.

        Scans every Inventory* category, not just the resolved one, so a user
        whose forum sits in an overflow category is not given a second forum.
        """
        category_ids = {
            c.id for c in matching_categories(guild, INVENTORY_CATEGORY_NAME)
        }
        owners = await UserInventoryForum.get_owners_by_forum_id(self.pool)

        # Exclude forums registered to somebody else: normalized channel names
        # collide (#304), and without this guard one user's recovery can adopt
        # or delete another user's live forum.
        forums = [
            f
            for f in guild.forums
            if f.category_id in category_ids
            and f.name == forum_name
            and owners.get(f.id, member.id) == member.id
        ]
        if not forums:
            return None

        candidates = [
            ForumCandidate(
                id=f.id,
                thread_count=await self._thread_count(f),
                registered=owners.get(f.id) == member.id,
            )
            for f in forums
        ]
        plan = plan_dedup(candidates)
        by_id = {f.id: f for f in forums}
        survivor = by_id[plan.survivor_id]

        for forum_id in plan.delete_ids:
            try:
                await by_id[forum_id].delete(
                    reason="Duplicate inventory forum cleanup during sync"
                )
                logger.info("Deleted empty duplicate inventory forum %d", forum_id)
            except discord.HTTPException as e:
                logger.error("Failed to delete duplicate forum %d: %s", forum_id, e)

        for forum_id in plan.keep_ids:
            logger.error(
                "Duplicate inventory forum %d for user %d contains threads; "
                "leaving it in place for manual review",
                forum_id,
                member.id,
            )

        # category_id is non-None by construction: the forum was matched on it.
        await self._register_forum_in_db(
            member.id, survivor.id, cast(int, survivor.category_id)
        )
        self._inventory_forum_stats["recovered"] += 1
        logger.info(
            "Recovered inventory forum '%s' (ID: %d) for user %d",
            survivor.name,
            survivor.id,
            member.id,
        )
        return survivor

    async def _create_new_forum(
        self,
        guild: discord.Guild,
        member: discord.Member,
        forum_name: str,
    ) -> discord.ForumChannel | None:
        """Create a new inventory forum, overflowing categories as needed.

        Create and register are made atomic by a compensating delete: if
        registration fails the forum would otherwise be orphaned and the next
        pass would create another, which is how three duplicates accumulated
        in production.
        """
        overwrites: CategoryOverwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages_in_threads=True,
                create_public_threads=False,
                send_messages=False,
            ),
        }
        category_overwrites: CategoryOverwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False)
        }

        try:
            forum = await create_with_overflow(
                guild,
                INVENTORY_CATEGORY_NAME,
                category_overwrites,
                lambda category: category.create_forum(
                    name=forum_name,
                    topic=f"Personal inventory for {member.display_name}",
                    overwrites=overwrites,
                ),
                reason="Inventory forums",
            )
        except Exception:
            logger.exception("Failed to create inventory forum for %d", member.id)
            return None

        try:
            await self._register_forum_in_db(
                member.id, forum.id, cast(int, forum.category_id)
            )
        except Exception:
            logger.exception(
                "Registration failed for user %d, rolling back forum %d",
                member.id,
                forum.id,
            )
            # Safe under the deletion policy: this forum was created
            # microseconds ago by this call and is provably empty.
            with contextlib.suppress(discord.HTTPException):
                await forum.delete(reason="Rollback: DB registration failed")
            return None

        self._inventory_forum_stats["created"] += 1
        logger.info("Created inventory forum '%s' for user %d", forum_name, member.id)
        return forum

    async def _register_forum_in_db(
        self, user_id: int, forum_id: int, category_id: int
    ) -> None:
        """Register forum in database. Ensures user exists first."""
        default = await Room.get_default(self.pool)
        if default is None:
            raise RuntimeError("No default room found in database.")
        await User.create_if_not_exists(self.pool, user_id, default.id)
        await UserInventoryForum.create_or_update(
            self.pool, user_id, forum_id, category_id
        )

    async def _ensure_wallet_thread(
        self, guild: discord.Guild, user: User, forum: discord.ForumChannel
    ) -> None:
        """Ensure user has a wallet with a pinned thread."""
        user_id = user.id

        wallet = await user.get_wallet()
        if wallet is None:
            await User.create_currency_account(self.pool, user_id, STARTING_BALANCE)

            wallet = await EntityInstance.create(
                self.pool,
                "wallet",
                owner_id=user_id,
            )

            if wallet is None:
                logger.warning(f"Wallet entity not found, skipping for {user_id}")
                return

            await User.update_wallet_instance(
                self.pool, user_id, str(wallet.instance_id)
            )
            logger.info(f"Created wallet for user {user_id}")

        wallet_thread_id = await EntityInstance.get_thread_id(
            self.pool, wallet.instance_id
        )
        if wallet_thread_id:
            thread = await fetch_thread(guild, wallet_thread_id)
            if thread:
                expected_name = ViewEntity(wallet).display_name
                needs_pin = not thread.flags.pinned
                needs_rename = thread.name != expected_name

                if needs_pin and needs_rename:
                    try:
                        await thread.edit(pinned=True, name=expected_name)
                        logger.debug(f"Pinned wallet thread {thread.id}")
                        logger.debug(
                            f"Renamed wallet thread {thread.id}: "
                            f"'{thread.name}' -> '{expected_name}'"
                        )
                    except discord.HTTPException as e:
                        logger.error(f"Failed to edit wallet thread: {e}")
                elif needs_pin:
                    try:
                        await thread.edit(pinned=True)
                        logger.debug(f"Pinned wallet thread {thread.id}")
                    except discord.HTTPException as e:
                        logger.error(f"Failed to pin wallet thread: {e}")
                elif needs_rename:
                    try:
                        await thread.edit(name=expected_name)
                        logger.debug(
                            f"Renamed wallet thread {thread.id}: "
                            f"'{thread.name}' -> '{expected_name}'"
                        )
                    except discord.HTTPException as e:
                        logger.error(f"Failed to rename wallet thread: {e}")
                return

        # Re-check: another reconciler may have created the thread
        wallet_thread_id = await EntityInstance.get_thread_id(
            self.pool, wallet.instance_id
        )
        if wallet_thread_id:
            return

        description = await self._render_on_look(wallet)
        view = ViewEntity(wallet)
        try:
            thread, message = await forum.create_thread(
                name=view.display_name,
                content=description or f"You have a {view.name}.",
            )

            claimed = await EntityInstance.claim_thread_ids(
                self.pool, wallet.instance_id, thread.id, message.id
            )

            if claimed:
                await thread.edit(pinned=True)
                logger.info(f"Created and pinned wallet thread for user {user_id}")
            else:
                logger.warning(
                    f"Lost wallet thread claim race for user {user_id}, "
                    f"deleting orphan thread {thread.id}"
                )
                with contextlib.suppress(discord.HTTPException):
                    await thread.delete()
        except discord.HTTPException as e:
            logger.error(f"Failed to create wallet thread: {e}")

    async def _ensure_map_thread(
        self, guild: discord.Guild, user: User, forum: discord.ForumChannel
    ) -> None:
        """Ensure user has a map with a thread.

        Not pinned — Discord forums allow only 1 pinned thread and the
        wallet already occupies that slot.
        """
        user_id = user.id

        map_instance = await user.get_map()
        if map_instance is None:
            map_instance = await EntityInstance.create(
                self.pool,
                MAP_ENTITY_ID,
                owner_id=user_id,
            )

            if map_instance is None:
                logger.warning(f"Map entity not found, skipping for {user_id}")
                return

            await User.update_map_instance(
                self.pool, user_id, str(map_instance.instance_id)
            )

            # Record current room as first visit
            await User.record_room_visit(self.pool, user_id, user.current_room)
            logger.info(f"Created map for user {user_id}")

        map_thread_id = await EntityInstance.get_thread_id(
            self.pool, map_instance.instance_id
        )
        if map_thread_id:
            thread = await fetch_thread(guild, map_thread_id)
            if thread:
                expected_name = ViewEntity(map_instance).display_name
                if thread.name != expected_name:
                    try:
                        await thread.edit(name=expected_name)
                    except discord.HTTPException as e:
                        logger.error(f"Failed to rename map thread: {e}")
                return

        # Re-check: another reconciler may have created the thread
        map_thread_id = await EntityInstance.get_thread_id(
            self.pool, map_instance.instance_id
        )
        if map_thread_id:
            return

        # Create new map thread
        room = await Room.get(self.pool, user.current_room)
        room_content = (
            f"Shows rooms you have discovered.\n## {room.name}\n{room.description}"
            if room
            else "Unknown location."
        )

        view = ViewEntity(map_instance)
        try:
            thread, description_msg = await forum.create_thread(
                name=view.display_name,
                content=room_content,
            )

            claimed = await EntityInstance.claim_thread_ids(
                self.pool, map_instance.instance_id, thread.id, description_msg.id
            )

            if claimed:
                # Generate and send map image as second message
                visited = await User.get_visited_rooms(self.pool, user_id)
                image_bytes = generate_map_image(visited)
                image_file = discord.File(BytesIO(image_bytes), filename="map.png")
                image_msg = await thread.send(file=image_file)
                await User.update_map_image_msg_id(self.pool, user_id, image_msg.id)

                logger.info(f"Created map thread for user {user_id}")
            else:
                logger.warning(
                    f"Lost map thread claim race for user {user_id}, "
                    f"deleting orphan thread {thread.id}"
                )
                with contextlib.suppress(discord.HTTPException):
                    await thread.delete()
        except discord.HTTPException as e:
            logger.error(f"Failed to create map thread: {e}")

    async def _post_transaction_notification(
        self, guild: discord.Guild, event: BalanceChangedEvent
    ) -> None:
        """Post a transaction summary message to a user's wallet thread."""
        user = await User.get(self.pool, event.user_id)
        if user is None:
            return

        wallet = await user.get_wallet()
        if wallet is None:
            return

        thread_id = await EntityInstance.get_thread_id(self.pool, wallet.instance_id)
        if thread_id is None:
            return

        thread = await fetch_thread(guild, thread_id)
        if thread is None:
            return

        message = _format_transaction_message(event)
        try:
            await thread.send(message)
        except discord.HTTPException as e:
            logger.error(
                f"Failed to post transaction notification for user {event.user_id}: {e}"
            )

    async def _sync_inventory_threads(
        self, guild: discord.Guild, user_id: int, forum: discord.ForumChannel
    ) -> None:
        """Ensure all inventory items have threads with current descriptions."""
        thread_infos = await EntityInstance.get_thread_info_by_owner(self.pool, user_id)

        for info in thread_infos:
            instance_id = info.instance_id
            thread_id = info.thread_id
            msg_id = info.msg_id

            instance = await EntityInstance.get(self.pool, instance_id)
            if instance is None:
                continue

            # Map thread content is managed by MapReconciler
            if instance.entity.id == MAP_ENTITY_ID:
                continue

            if thread_id:
                thread = await fetch_thread(guild, thread_id)
                if thread and msg_id:
                    await self._update_thread_description(thread, msg_id, instance)
                    continue
                if not thread:
                    await EntityInstance.clear_thread_ids(self.pool, instance_id)

            await self._create_item_thread(forum, instance)

    async def _update_thread_description(
        self, thread: discord.Thread, msg_id: int, instance: EntityInstance
    ) -> None:
        """Update thread title and description if content has changed."""
        new_description = await self._render_on_look(instance)
        new_name = ViewEntity(instance).display_name

        if thread.name != new_name:
            try:
                await thread.edit(name=new_name)
                logger.debug(
                    f"Updated title for instance {instance.instance_id} "
                    f"in thread {thread.id}: '{thread.name}' -> '{new_name}'"
                )
            except discord.HTTPException as e:
                logger.error(f"Failed to update thread title {thread.id}: {e}")

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

        Re-checks the DB before creating to guard against races where another
        reconciler already created the thread. Uses claim_thread_ids() so that
        if two callers slip past the lock, only the winner keeps its thread.
        """
        # Re-check: another reconciler may have created the thread
        existing = await EntityInstance.get_thread_id(self.pool, instance.instance_id)
        if existing is not None:
            return

        description = await self._render_on_look(instance)
        view = ViewEntity(instance)

        try:
            thread, message = await forum.create_thread(
                name=view.display_name,
                content=description or f"You have a {view.name}.",
            )

            claimed = await EntityInstance.claim_thread_ids(
                self.pool, instance.instance_id, thread.id, message.id
            )

            if claimed:
                logger.info(
                    f"Created thread '{view.display_name}' for instance "
                    f"{instance.instance_id}"
                )
            else:
                # Another caller won the race — delete the orphan thread
                logger.warning(
                    f"Lost thread claim race for instance {instance.instance_id}, "
                    f"deleting orphan thread {thread.id}"
                )
                with contextlib.suppress(discord.HTTPException):
                    await thread.delete()
        except discord.HTTPException as e:
            logger.error(f"Failed to create item thread: {e}")
        except asyncpg.PostgresError as e:
            logger.error(f"Failed to store thread ID: {e}")
