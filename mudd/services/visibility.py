"""Channel visibility management service."""

import asyncio
import logging

import discord

from mudd.services.database import get_pool

logger = logging.getLogger(__name__)


class VisibilityService:
    """Manages user location assignments and Discord channel visibility."""

    def __init__(self, default_room: str):
        self.default_room = default_room
        self._startup_complete = asyncio.Event()
        # Room name caches (rebuilt on each sync)
        self._room_to_channel: dict[str, int] = {}
        self._channel_to_room: dict[int, str] = {}
        # Zone tracking (rebuilt on each sync)
        self._zone_to_category: dict[str, int] = {}
        self._category_to_zone: dict[int, str] = {}
        self._room_to_zone: dict[str, str] = {}

    async def wait_for_startup(self) -> None:
        """Block until startup sync is complete."""
        await self._startup_complete.wait()

    async def _build_room_cache(self, guild: discord.Guild) -> None:
        """Build the room name <-> channel ID caches from database and Discord."""
        pool = await get_pool()

        # Query zones from database
        zone_rows = await pool.fetch("SELECT id, name FROM zones")

        # Query rooms with zone_id from database
        room_rows = await pool.fetch("SELECT id, zone_id FROM rooms")

        # Build zone -> room mapping
        room_to_zone: dict[str, str] = {}
        for row in room_rows:
            room_to_zone[row["id"]] = row["zone_id"]

        # Match Discord categories to zones by name
        zone_to_category: dict[str, int] = {}
        category_to_zone: dict[int, str] = {}
        for category in guild.categories:
            # Match category name to zone id (both are lowercase, hyphenated)
            category_name = category.name.lower().replace(" ", "-")
            for zone_row in zone_rows:
                if zone_row["id"] == category_name:
                    zone_to_category[zone_row["id"]] = category.id
                    category_to_zone[category.id] = zone_row["id"]
                    break

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
        self._room_to_zone = room_to_zone

        logger.info(
            f"Built room cache with {len(self._room_to_channel)} rooms "
            f"across {len(self._zone_to_category)} zones"
        )

    def get_channel_for_room(self, room_name: str) -> int | None:
        """Get channel ID for a room name."""
        return self._room_to_channel.get(room_name)

    def get_room_for_channel(self, channel_id: int) -> str | None:
        """Get room name for a channel ID."""
        return self._channel_to_room.get(channel_id)

    def get_default_room(self) -> str:
        """Get the default room name."""
        return self.default_room

    def get_default_channel_id(self) -> int | None:
        """Get the default room's channel ID."""
        return self.get_channel_for_room(self.default_room)

    def is_mud_location(self, channel: discord.abc.GuildChannel) -> bool:
        """Check if a channel is a MUD location (in a zone category)."""
        return (
            isinstance(channel, discord.TextChannel)
            and channel.category_id in self._category_to_zone
        )

    def get_mud_locations(self, guild: discord.Guild) -> list[discord.TextChannel]:
        """Get all MUD location channels in a guild."""
        return [
            ch for ch in guild.text_channels if ch.category_id in self._category_to_zone
        ]

    def get_paired_voice_channel(
        self, text_channel: discord.TextChannel
    ) -> discord.VoiceChannel | None:
        """
        Find a voice channel paired with a text channel.

        A voice channel is considered paired if it has the same name and is in the
        same category as the text channel.

        Args:
            text_channel: The text channel to find a paired voice channel for

        Returns:
            The paired voice channel, or None if no matching voice channel exists
        """
        guild = text_channel.guild
        for voice_channel in guild.voice_channels:
            if (
                voice_channel.name == text_channel.name
                and voice_channel.category_id == text_channel.category_id
            ):
                return voice_channel
        return None

    async def _set_voice_permissions(
        self,
        text_channel: discord.TextChannel,
        member: discord.Member,
        overwrite: discord.PermissionOverwrite | None,
        reason: str,
        *,
        disconnect_if_leaving: bool = False,
    ) -> None:
        """
        Set voice channel permissions (best-effort, non-blocking on errors).

        Voice channel permissions are supplementary to text channel permissions.
        Failures are logged but don't raise exceptions.

        Args:
            text_channel: The text channel whose paired voice channel to update
            member: The guild member to set permissions for
            overwrite: The permission overwrite to apply (None to remove)
            reason: Audit log reason for the permission change
            disconnect_if_leaving: If True and overwrite is None, disconnect user
                                   from voice channel if they're in it
        """
        paired_voice = self.get_paired_voice_channel(text_channel)
        if not paired_voice:
            return

        # Disconnect user from voice before removing permissions if requested
        if (
            disconnect_if_leaving
            and overwrite is None
            and member.voice
            and member.voice.channel == paired_voice
        ):
            try:
                await member.move_to(None)
            except discord.HTTPException as e:
                logger.warning(
                    f"Failed to disconnect {member} from voice channel "
                    f"{paired_voice}: {e}"
                )

        try:
            await paired_voice.set_permissions(
                member, overwrite=overwrite, reason=reason
            )
        except discord.HTTPException as e:
            logger.error(
                f"Failed to set voice channel {paired_voice.id} "
                f"permissions for {member.id}: {e}"
            )

    async def get_user_location(self, user_id: int) -> int | None:
        """
        Get the channel ID of the user's current location, or None if not set.

        Queries the database for the user's room name, then resolves to channel ID.
        """
        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT current_room FROM users WHERE id = $1",
            user_id,
        )
        if row and row["current_room"]:
            return self.get_channel_for_room(row["current_room"])
        return None

    async def get_user_room(self, user_id: int) -> str | None:
        """Get the room name of the user's current location, or None if not set."""
        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT current_room FROM users WHERE id = $1",
            user_id,
        )
        return row["current_room"] if row else None

    async def set_user_location(self, user_id: int, channel_id: int) -> None:
        """
        Set the user's current location in the database.

        Converts channel ID to room name before storing.
        """
        room_name = self.get_room_for_channel(channel_id)
        if room_name is None:
            logger.warning(f"Cannot find room for channel {channel_id}")
            return

        pool = await get_pool()
        await pool.execute(
            """
            INSERT INTO users (id, current_room)
            VALUES ($1, $2)
            ON CONFLICT (id)
            DO UPDATE SET current_room = EXCLUDED.current_room
            """,
            user_id,
            room_name,
        )

    async def set_user_room(self, user_id: int, room_name: str) -> None:
        """
        Set the user's current location by room name.

        Used for assigning users to rooms before channels exist.
        """
        pool = await get_pool()
        await pool.execute(
            """
            INSERT INTO users (id, current_room)
            VALUES ($1, $2)
            ON CONFLICT (id)
            DO UPDATE SET current_room = EXCLUDED.current_room
            """,
            user_id,
            room_name,
        )

    async def delete_user_location(self, user_id: int) -> None:
        """Remove user's location assignment from the database."""
        pool = await get_pool()
        await pool.execute("DELETE FROM users WHERE id = $1", user_id)

    async def sync_user_to_discord(
        self,
        member: discord.Member,
        current_location_id: int | None = None,
    ) -> None:
        """
        Ensure Discord permissions match the user's database state.

        Args:
            member: The guild member to sync
            current_location_id: The user's current location channel ID.
                               If None, will fetch from database.
        """
        if current_location_id is None:
            current_location_id = await self.get_user_location(member.id)

        guild = member.guild
        mud_locations = self.get_mud_locations(guild)

        for location in mud_locations:
            should_see = location.id == current_location_id

            # Use explicit True to grant, None to remove (inherit from category)
            text_overwrite = (
                discord.PermissionOverwrite(view_channel=True) if should_see else None
            )
            voice_overwrite = (
                discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)
                if should_see
                else None
            )

            try:
                await location.set_permissions(
                    member, overwrite=text_overwrite, reason="MUDD visibility sync"
                )
            except discord.HTTPException as e:
                logger.error(
                    f"Failed to set permissions for {member.id} on {location.id}: {e}"
                )
                raise

            await self._set_voice_permissions(
                location, member, voice_overwrite, reason="MUDD visibility sync"
            )

    async def move_user_to_channel(
        self,
        member: discord.Member,
        channel_id: int,
    ) -> bool:
        """
        Move user to a new location. Idempotent.

        Uses Alter-Ego order: revoke old channel first, then grant new channel.

        Returns:
            True if user was moved, False if already in that location.

        Raises:
            asyncpg.PostgresError: If database operation fails
            discord.HTTPException: If Discord API call fails
        """
        current = await self.get_user_location(member.id)
        if current == channel_id:
            return False

        await self.set_user_location(member.id, channel_id)

        guild = member.guild
        new_channel = guild.get_channel(channel_id)
        old_channel = guild.get_channel(current) if current else None

        # Phase 1: Remove access from old channel FIRST (Alter-Ego order)
        # Type guard: explicitly check TextChannel to satisfy type checker
        if (
            old_channel
            and self.is_mud_location(old_channel)
            and isinstance(old_channel, discord.TextChannel)
        ):
            await old_channel.set_permissions(
                member,
                overwrite=None,
                reason="MUDD movement - leaving",
            )

            await self._set_voice_permissions(
                old_channel,
                member,
                overwrite=None,
                reason="MUDD movement - leaving",
                disconnect_if_leaving=True,
            )

        # Phase 2: Grant access to new channel
        if new_channel:
            await new_channel.set_permissions(
                member,
                overwrite=discord.PermissionOverwrite(view_channel=True),
                reason="MUDD movement - entering",
            )

            if isinstance(new_channel, discord.TextChannel):
                await self._set_voice_permissions(
                    new_channel,
                    member,
                    overwrite=discord.PermissionOverwrite(
                        view_channel=True, connect=True, speak=True
                    ),
                    reason="MUDD movement - entering",
                )

        logger.info(f"Moved user {member.id} from {current} to {channel_id}")
        return True

    async def sync_guild(self, guild: discord.Guild) -> dict[str, int]:
        """
        Synchronize all users' Discord permissions to match database state.

        - Users with existing database entries: sync Discord to match
        - Users without database entries: assign to default channel

        This method can be called from any context: startup, periodic sync,
        or in response to Discord events.

        Returns:
            Stats dict with counts of users synced/assigned
        """
        # Build room cache before syncing users
        await self._build_room_cache(guild)

        default_channel_id = self.get_default_channel_id()
        if default_channel_id is None:
            logger.error(
                f"Default room '{self.default_room}' not found in any zone category"
            )
            return {"synced": 0, "assigned_default": 0, "errors": 0}

        stats = {"synced": 0, "assigned_default": 0, "errors": 0}

        for member in guild.members:
            if member.bot:
                continue

            try:
                location_id = await self.get_user_location(member.id)

                if location_id is None:
                    await self.set_user_location(member.id, default_channel_id)
                    await self.sync_user_to_discord(
                        member, current_location_id=default_channel_id
                    )
                    stats["assigned_default"] += 1
                else:
                    location = guild.get_channel(location_id)
                    if location is None or not self.is_mud_location(location):
                        await self.set_user_location(member.id, default_channel_id)
                        await self.sync_user_to_discord(
                            member, current_location_id=default_channel_id
                        )
                        stats["assigned_default"] += 1
                    else:
                        await self.sync_user_to_discord(
                            member, current_location_id=location_id
                        )
                        stats["synced"] += 1

            except Exception as e:
                logger.error(f"Failed to sync user {member.id}: {e}")
                stats["errors"] += 1

        logger.info(f"Guild sync complete for {guild.name}: {stats}")
        return stats

    def mark_startup_complete(self) -> None:
        """Signal that initial startup sync is complete."""
        self._startup_complete.set()


_service: VisibilityService | None = None


def get_visibility_service() -> VisibilityService:
    """Get the visibility service singleton."""
    if _service is None:
        raise RuntimeError("VisibilityService not initialized")
    return _service


def init_visibility_service(default_room: str) -> VisibilityService:
    """Initialize the visibility service singleton."""
    global _service
    _service = VisibilityService(default_room)
    return _service
