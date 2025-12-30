"""Channel visibility management service."""

import asyncio
import logging

import discord

from mudd.services.redis import get_redis

logger = logging.getLogger(__name__)


class VisibilityService:
    """Manages user location assignments and Discord channel visibility."""

    def __init__(self, world_category_id: int, default_channel_id: int):
        self.world_category_id = world_category_id
        self.default_channel_id = default_channel_id
        self._startup_complete = asyncio.Event()
        self._startup_lock = asyncio.Lock()

    async def wait_for_startup(self) -> None:
        """Block until startup sync is complete."""
        await self._startup_complete.wait()

    def is_mud_location(self, channel: discord.abc.GuildChannel) -> bool:
        """Check if a channel is a MUD location (in the world category)."""
        return (
            isinstance(channel, discord.TextChannel)
            and channel.category_id == self.world_category_id
        )

    def get_mud_locations(self, guild: discord.Guild) -> list[discord.TextChannel]:
        """Get all MUD location channels in a guild."""
        return [
            ch for ch in guild.text_channels if ch.category_id == self.world_category_id
        ]

    async def get_user_location(self, user_id: int) -> int | None:
        """Get the channel ID of the user's current location, or None if not set."""
        client = await get_redis()
        location = await client.get(f"user:{user_id}:location")
        return int(location) if location else None

    async def set_user_location(self, user_id: int, channel_id: int) -> None:
        """Set the user's current location in Redis."""
        client = await get_redis()
        await client.set(f"user:{user_id}:location", str(channel_id))

    async def delete_user_location(self, user_id: int) -> None:
        """Remove user's location assignment from Redis."""
        client = await get_redis()
        await client.delete(f"user:{user_id}:location")

    async def sync_user_to_discord(
        self,
        member: discord.Member,
        current_location_id: int | None = None,
    ) -> None:
        """
        Ensure Discord permissions match the user's Redis state.

        Args:
            member: The guild member to sync
            current_location_id: The user's current location (from Redis).
                               If None, will fetch from Redis.
        """
        if current_location_id is None:
            current_location_id = await self.get_user_location(member.id)

        guild = member.guild
        mud_locations = self.get_mud_locations(guild)

        for location in mud_locations:
            should_see = location.id == current_location_id

            overwrite = discord.PermissionOverwrite(view_channel=should_see)

            try:
                await location.set_permissions(
                    member, overwrite=overwrite, reason="MUDD visibility sync"
                )
            except discord.HTTPException as e:
                logger.error(
                    f"Failed to set permissions for {member.id} on {location.id}: {e}"
                )
                raise

    async def move_user_to_channel(
        self,
        member: discord.Member,
        channel_id: int,
    ) -> bool:
        """
        Move user to a new location. Idempotent.

        Updates Redis first, then syncs Discord permissions.

        Returns:
            True if user was moved, False if already in that location.

        Raises:
            redis.RedisError: If Redis operation fails
            discord.HTTPException: If Discord API call fails
        """
        current = await self.get_user_location(member.id)
        if current == channel_id:
            return False

        await self.set_user_location(member.id, channel_id)
        await self.sync_user_to_discord(member, current_location_id=channel_id)

        logger.info(f"Moved user {member.id} from {current} to {channel_id}")
        return True

    async def startup_sync(self, guild: discord.Guild) -> dict[str, int]:
        """
        Synchronize all users at bot startup.

        - Users with existing Redis entries: sync Discord to match
        - Users without Redis entries: assign to default channel

        Returns:
            Stats dict with counts of users synced/assigned
        """
        async with self._startup_lock:
            if self._startup_complete.is_set():
                return {"skipped": 1}

            stats = {"synced": 0, "assigned_default": 0, "errors": 0}

            for member in guild.members:
                if member.bot:
                    continue

                try:
                    location_id = await self.get_user_location(member.id)

                    if location_id is None:
                        await self.set_user_location(member.id, self.default_channel_id)
                        await self.sync_user_to_discord(
                            member, current_location_id=self.default_channel_id
                        )
                        stats["assigned_default"] += 1
                    else:
                        location = guild.get_channel(location_id)
                        if location is None or not self.is_mud_location(location):
                            await self.set_user_location(
                                member.id, self.default_channel_id
                            )
                            location_id = self.default_channel_id

                        await self.sync_user_to_discord(
                            member, current_location_id=location_id
                        )
                        stats["synced"] += 1

                except Exception as e:
                    logger.error(f"Failed to sync user {member.id}: {e}")
                    stats["errors"] += 1

            self._startup_complete.set()
            logger.info(f"Startup sync complete: {stats}")
            return stats


_service: VisibilityService | None = None


def get_visibility_service() -> VisibilityService:
    """Get the visibility service singleton."""
    if _service is None:
        raise RuntimeError("VisibilityService not initialized")
    return _service


def init_visibility_service(
    world_category_id: int, default_channel_id: int
) -> VisibilityService:
    """Initialize the visibility service singleton."""
    global _service
    _service = VisibilityService(world_category_id, default_channel_id)
    return _service
