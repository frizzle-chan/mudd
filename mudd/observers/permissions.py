"""Permission reconciler for Discord state."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import asyncpg
import discord

from mudd.events import (
    GameEvent,
    UserLocationSyncEvent,
    UserSyncEvent,
)
from mudd.models.user import User

if TYPE_CHECKING:
    from mudd.observers.discord import RoomChannelCache

logger = logging.getLogger(__name__)


class PermissionReconciler:
    """Reconciles user permissions and location sync in Discord.

    Handles:
    - UserLocationSyncEvent: Syncs Discord permissions for location changes
    - UserSyncEvent: Upserts user with display_name and grants permissions
    """

    def __init__(
        self,
        bot: discord.Client,
        pool: asyncpg.Pool,
        guild_id: int,
        room_cache: RoomChannelCache | None = None,
    ) -> None:
        self.bot = bot
        self.pool = pool
        self._guild_id = guild_id
        self.room_cache = room_cache
        self._location_sync_events: list[UserLocationSyncEvent] = []
        self._user_sync_events: list[UserSyncEvent] = []

    def notify(self, event: GameEvent) -> None:
        """Queue permission-related events for async processing."""
        match event:
            case UserLocationSyncEvent() as evt:
                self._location_sync_events.append(evt)
            case UserSyncEvent() as evt:
                self._user_sync_events.append(evt)

    async def flush(self) -> None:
        """Process queued permission events."""
        location_sync_events = self._location_sync_events
        self._location_sync_events = []
        user_sync_events = self._user_sync_events
        self._user_sync_events = []

        guild = self.bot.get_guild(self._guild_id)
        if guild is None:
            logger.warning(
                "Guild %d not available, skipping permission flush", self._guild_id
            )
            return

        for evt in location_sync_events:
            await self._sync_user_location(guild, evt)

        for evt in user_sync_events:
            await self._handle_user_sync(guild, evt)

    async def _set_voice_permissions(
        self,
        text_channel: discord.TextChannel,
        member: discord.Member,
        overwrite: discord.PermissionOverwrite | None,
        reason: str,
        *,
        disconnect_if_leaving: bool = False,
    ) -> None:
        """Set voice channel permissions (best-effort, non-blocking on errors).

        Voice channel permissions are supplementary to text channel permissions.
        Failures are logged but don't raise exceptions.
        """
        if self.room_cache is None:
            return

        paired_voice = self.room_cache.get_paired_voice_channel(text_channel)
        if not paired_voice:
            return

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

        # Skip API call if voice permissions already match desired state
        current = paired_voice.overwrites_for(member)
        if overwrite is None:
            if current.is_empty():
                return
        elif current == overwrite:
            return

        try:
            await paired_voice.set_permissions(
                member, overwrite=overwrite, reason=reason
            )
        except discord.HTTPException as e:
            logger.error(
                f"Failed to set voice channel {paired_voice.id} "
                f"permissions for {member.id}: {e}"
            )

    async def _revoke_stale_permissions(
        self,
        guild: discord.Guild,
        member: discord.Member,
        current_room: str,
    ) -> None:
        """Revoke view_channel from all MUD rooms except the current one."""
        if self.room_cache is None:
            return
        for channel in self.room_cache.get_mud_locations(guild):
            room_name = self.room_cache.get_room_for_channel(channel.id)
            if room_name == current_room:
                continue

            overwrites = channel.overwrites_for(member)
            if overwrites.view_channel is True:
                try:
                    await channel.set_permissions(
                        member,
                        overwrite=None,
                        reason="MUDD sync - revoking stale permission",
                    )
                    logger.debug(
                        f"Revoked stale permission for {member.id} on {channel.name}"
                    )
                except discord.HTTPException as e:
                    logger.error(
                        f"Failed to revoke stale permissions on {channel.id}: {e}"
                    )

                await self._set_voice_permissions(
                    channel,
                    member,
                    overwrite=None,
                    reason="MUDD sync - revoking stale permission",
                    disconnect_if_leaving=True,
                )

    async def _sync_user_location(
        self, guild: discord.Guild, event: UserLocationSyncEvent
    ) -> None:
        """Sync Discord permissions for a user's location change.

        Uses Alter-Ego order: revoke old channel first, then grant new channel.

        When from_room is None (sync mode), performs full reconciliation:
        revokes permissions from ALL rooms except the current one.
        """
        if self.room_cache is None:
            logger.warning("RoomChannelCache not available, skipping location sync")
            return

        member = guild.get_member(event.user_id)
        if member is None:
            logger.debug(f"User {event.user_id} not found in guild {guild.name}")
            return

        new_channel_id = self.room_cache.get_channel_for_room(event.to_room)
        new_channel = guild.get_channel(new_channel_id) if new_channel_id else None

        # Phase 1: Revoke stale permissions
        if event.from_room is None:
            # Full sync mode: revoke permissions from ALL rooms except current
            await self._revoke_stale_permissions(guild, member, event.to_room)
        else:
            # Normal movement: just revoke from old channel
            old_channel_id = self.room_cache.get_channel_for_room(event.from_room)
            old_channel = guild.get_channel(old_channel_id) if old_channel_id else None

            if old_channel and isinstance(old_channel, discord.TextChannel):
                try:
                    await old_channel.set_permissions(
                        member,
                        overwrite=None,
                        reason="MUDD movement - leaving",
                    )
                except discord.HTTPException as e:
                    logger.error(
                        f"Failed to revoke permissions on {old_channel.id}: {e}"
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
            try:
                await new_channel.set_permissions(
                    member,
                    overwrite=discord.PermissionOverwrite(view_channel=True),
                    reason="MUDD movement - entering",
                )
            except discord.HTTPException as e:
                logger.error(f"Failed to grant permissions on {new_channel.id}: {e}")

            if isinstance(new_channel, discord.TextChannel):
                await self._set_voice_permissions(
                    new_channel,
                    member,
                    overwrite=discord.PermissionOverwrite(
                        view_channel=True, connect=True, speak=True
                    ),
                    reason="MUDD movement - entering",
                )

        logger.debug(
            f"Synced location for {member.id}: {event.from_room} -> {event.to_room}"
        )

    async def _handle_user_sync(
        self, guild: discord.Guild, event: UserSyncEvent
    ) -> None:
        """Handle user sync: upsert user with display_name and grant permissions.

        This is an idempotent operation that:
        1. Upserts user with display_name (creates new or updates existing)
        2. Grants permissions to current room (or default for new users)
        """
        if self.room_cache is None:
            logger.warning(
                "RoomChannelCache not available, skipping user sync handling"
            )
            return

        member = guild.get_member(event.user_id)
        if member is None:
            logger.debug(f"User {event.user_id} not found in guild {guild.name}")
            return

        user = await User.create_or_update(
            self.pool,
            event.user_id,
            event.display_name,
            event.default_room,
        )

        channel_id = self.room_cache.get_channel_for_room(user.current_room)
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel:
                # Skip if permissions already correct (avoids rate limits during sync)
                overwrites = channel.overwrites_for(member)
                if overwrites.view_channel is not True:
                    try:
                        await channel.set_permissions(
                            member,
                            overwrite=discord.PermissionOverwrite(view_channel=True),
                            reason="MUDD - user sync",
                        )
                    except discord.HTTPException as e:
                        logger.error(f"Failed to grant permissions for user: {e}")

                    if isinstance(channel, discord.TextChannel):
                        await self._set_voice_permissions(
                            channel,
                            member,
                            overwrite=discord.PermissionOverwrite(
                                view_channel=True, connect=True, speak=True
                            ),
                            reason="MUDD - user sync",
                        )

        # Revoke stale permissions from rooms user is no longer in
        await self._revoke_stale_permissions(guild, member, user.current_room)

        logger.debug(
            f"Synced user {event.user_id} (display_name={event.display_name}) "
            f"to room {user.current_room}"
        )
