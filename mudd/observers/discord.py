"""Discord reconciler that syncs Discord state with model changes."""

from __future__ import annotations

import logging

import asyncpg
import discord

from mudd.events import GameEvent
from mudd.models.room import Room
from mudd.models.user import User
from mudd.models.zone import Zone
from mudd.observers.inventory import InventoryReconciler
from mudd.observers.permissions import PermissionReconciler
from mudd.observers.zone_room import ZoneRoomReconciler

logger = logging.getLogger(__name__)


class RoomChannelCache:
    """Cache mapping rooms to Discord channels.

    Extracted from VisibilityService. Provides room <-> channel lookups
    for movement and permission operations.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._default_room: str | None = None
        # Room name caches (rebuilt on each sync)
        self._room_to_channel: dict[str, int] = {}
        self._channel_to_room: dict[int, str] = {}
        # Zone tracking (rebuilt on each sync)
        self._zone_to_category: dict[str, int] = {}
        self._category_to_zone: dict[int, str] = {}

    async def rebuild(self, guild: discord.Guild) -> None:
        """Build the room name <-> channel ID caches from database and Discord."""
        # Query zones from database
        zones = await Zone.get_all(self._pool)

        # Query rooms with zone_id from database
        room_to_zone = await Room.get_all_zone_mappings(self._pool)

        # Precompute zone lookup by id to avoid nested loops
        zone_id_map = {z.id: z for z in zones}

        # Match Discord categories to zones by name
        zone_to_category: dict[str, int] = {}
        category_to_zone: dict[int, str] = {}
        for category in guild.categories:
            # Match category name to zone id (both are lowercase, hyphenated)
            category_name = category.name.lower().replace(" ", "-")
            zone = zone_id_map.get(category_name)
            if zone is not None:
                zone_to_category[zone.id] = category.id
                category_to_zone[category.id] = zone.id

        # Build room caches only for channels in matched categories
        room_to_channel: dict[str, int] = {}
        channel_to_room: dict[int, str] = {}
        for channel in guild.text_channels:
            if channel.category_id in category_to_zone:
                room_name = channel.name
                # Only cache if this room exists in our database
                if room_name in room_to_zone:
                    room_to_channel[room_name] = channel.id
                    channel_to_room[channel.id] = room_name

        # Atomic swap
        self._room_to_channel = room_to_channel
        self._channel_to_room = channel_to_room
        self._zone_to_category = zone_to_category
        self._category_to_zone = category_to_zone

        logger.info(
            f"Built room cache with {len(self._room_to_channel)} rooms "
            f"across {len(self._zone_to_category)} zones"
        )

    def get_channel_for_room(self, room_id: str) -> int | None:
        """Get channel ID for a room name."""
        return self._room_to_channel.get(room_id)

    def get_room_for_channel(self, channel_id: int) -> str | None:
        """Get room name for a channel ID."""
        return self._channel_to_room.get(channel_id)

    async def get_default_room(self) -> str:
        """Get the default room ID from the database (cached after first call)."""
        if self._default_room is None:
            room = await Room.get_default(self._pool)
            if room is None:
                raise RuntimeError("No default room found in database.")
            self._default_room = room.id
        return self._default_room

    async def get_default_channel_id(self) -> int | None:
        """Get the default room's channel ID."""
        default_room = await self.get_default_room()
        return self.get_channel_for_room(default_room)

    def get_mud_locations(self, guild: discord.Guild) -> list[discord.TextChannel]:
        """Get all MUD location channels in a guild."""
        return [
            ch for ch in guild.text_channels if ch.category_id in self._category_to_zone
        ]

    def get_paired_voice_channel(
        self, text_channel: discord.TextChannel
    ) -> discord.VoiceChannel | None:
        """Find a voice channel paired with a text channel.

        A voice channel is considered paired if it has the same name and is in the
        same category as the text channel.
        """
        guild = text_channel.guild
        for voice_channel in guild.voice_channels:
            if (
                voice_channel.name == text_channel.name
                and voice_channel.category_id == text_channel.category_id
            ):
                return voice_channel
        return None

    async def get_user_room(self, user_id: int) -> str | None:
        """Get the room name of the user's current location."""
        return await User.get_current_room(self._pool, user_id)


class DiscordReconciler:
    """Composite observer that delegates to focused sub-reconcilers.

    Handles Discord operations when models change:
    - Zone/room infrastructure (ZoneRoomReconciler)
    - User permissions and location sync (PermissionReconciler)
    - Inventory forums, threads, and wallets (InventoryReconciler)

    The reconciler implements the Observer protocol: notify() is sync
    and queues notifications for async processing. Call flush() after
    sending the response to execute queued Discord operations.

    Events are idempotent - fire an event a million times, it creates
    the resource once and noops thereafter.

    Usage:
        reconciler = DiscordReconciler(bot, pool, room_cache)
        await Zone.sync_all(pool, zones, observers=(reconciler,))
        await Room.sync_all(pool, rooms, default_room, observers=(reconciler,))
        await reconciler.flush()  # Idempotently reconciles Discord state
    """

    def __init__(
        self,
        bot: discord.Client,
        pool: asyncpg.Pool,
        room_cache: RoomChannelCache | None = None,
        console_channel: str = "console",
    ) -> None:
        self._zone_room = ZoneRoomReconciler(bot, pool, console_channel)
        self._permissions = PermissionReconciler(bot, pool, room_cache)
        self._inventory = InventoryReconciler(bot, pool)

    @property
    def _seen_orphans(self) -> set[tuple[int, str, str]]:
        """Delegate orphan tracking to ZoneRoomReconciler."""
        return self._zone_room._seen_orphans

    @_seen_orphans.setter
    def _seen_orphans(self, value: set[tuple[int, str, str]]) -> None:
        self._zone_room._seen_orphans = value

    def notify(self, event: GameEvent) -> None:
        """Receive notification (sync). Delegate to sub-reconcilers."""
        self._zone_room.notify(event)
        self._permissions.notify(event)
        self._inventory.notify(event)

    async def flush(self) -> None:
        """Process queued notifications. Call after response sent.

        Preserves ordering: zones/rooms/orphans -> inventory -> permissions.
        """
        await self._zone_room.flush()
        await self._inventory.flush()
        await self._permissions.flush()

    def get_inventory_forum_stats(self) -> dict[str, int]:
        """Get accumulated inventory forum sync stats."""
        return self._inventory.get_inventory_forum_stats()

    def reset_inventory_forum_stats(self) -> None:
        """Reset inventory forum sync stats to zero."""
        self._inventory.reset_inventory_forum_stats()
