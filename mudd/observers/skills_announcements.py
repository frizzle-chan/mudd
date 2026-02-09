"""Level-up announcement handling for the skills system."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from mudd.observers.discord import RoomChannelCache

from mudd.events.types import LevelUpEvent
from mudd.skills.formatting import format_level_up_message

logger = logging.getLogger(__name__)


class SkillsAnnouncements:
    """Two-phase level-up announcement lifecycle.

    Announcements are prepared synchronously during flush (prepare),
    then sent asynchronously after the caller is ready (post_announcements).
    """

    def __init__(
        self,
        bot: discord.Client,
        room_cache: RoomChannelCache | None = None,
    ) -> None:
        self._bot = bot
        self._room_cache = room_cache
        self._pending: list[tuple[discord.TextChannel, str]] = []

    def prepare(self, event: LevelUpEvent) -> None:
        """Prepare a level-up announcement for later sending.

        Finds the target channel and formats the message, storing
        them for post_announcements().

        Args:
            event: LevelUpEvent with user/skill/level info
        """
        logger.info(
            "Preparing level-up: user %d, %s to level %d in '%s'",
            event.user_id,
            event.skill,
            event.new_level,
            event.room_id,
        )

        # Fast path: use RoomChannelCache for O(1) lookup
        if self._room_cache is not None:
            channel_id = self._room_cache.get_channel_for_room(event.room_id)
            if channel_id is not None:
                channel = self._bot.get_channel(channel_id)
                if isinstance(channel, discord.TextChannel):
                    member = channel.guild.get_member(event.user_id)
                    if member is not None:
                        message = format_level_up_message(
                            member.mention,
                            event.skill,
                            event.new_level,
                        )
                        self._pending.append((channel, message))
                        return

            logger.warning(
                "No channel found for level-up announcement: room_id='%s', user_id=%d",
                event.room_id,
                event.user_id,
            )
            return

        # Fallback: linear scan when cache is not available
        for guild in self._bot.guilds:
            member = guild.get_member(event.user_id)
            if member is None:
                continue

            for channel in guild.text_channels:
                if channel.name == event.room_id:
                    message = format_level_up_message(
                        member.mention,
                        event.skill,
                        event.new_level,
                    )
                    self._pending.append((channel, message))
                    return

        logger.warning(
            "No channel found for level-up announcement: room_id='%s', user_id=%d",
            event.room_id,
            event.user_id,
        )

    async def post_announcements(self) -> None:
        """Send all pending level-up announcements and clear them."""
        for channel, message in self._pending:
            try:
                await channel.send(message)
                logger.info(
                    "Level-up announcement sent to #%s",
                    channel.name,
                )
            except Exception:
                logger.exception(
                    "Failed to send level-up announcement to #%s",
                    channel.name,
                )
        self._pending.clear()
