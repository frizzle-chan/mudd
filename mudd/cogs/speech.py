"""Speech XP cog — awards XP when players chat in room channels."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import asyncpg
import discord
from discord.ext import commands

if TYPE_CHECKING:
    from mudd.bot import MuddBot

from mudd.events.types import GrantXPSignal
from mudd.models.user import User
from mudd.observers import RoomChannelCache, build_observers, flush_all, post_flush_all
from mudd.skills.registry import Skill

logger = logging.getLogger(__name__)

# XP granted per qualifying message
SPEECH_XP_PER_MESSAGE: int = 15

# Minimum seconds between XP grants for the same user
SPEECH_COOLDOWN_SECONDS: float = 30


class Speech(commands.Cog):
    """Awards Speech XP when players send messages in room channels."""

    def __init__(
        self,
        bot: commands.Bot,
        pool: asyncpg.Pool,
        room_cache: RoomChannelCache,
    ) -> None:
        self.bot = bot
        self._pool = pool
        self._room_cache = room_cache
        self._cooldowns: dict[int, float] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Grant Speech XP for messages in room channels."""
        # Skip bots and DMs
        if message.author.bot or message.guild is None:
            return

        bot: MuddBot = self.bot  # type: ignore[assignment]
        if message.guild.id != bot.guild_id:
            return

        # Only grant XP in room channels
        room_id = self._room_cache.get_room_for_channel(message.channel.id)
        if room_id is None:
            return

        # Cooldown check
        now = time.monotonic()
        last_grant = self._cooldowns.get(message.author.id)
        if last_grant is not None and (now - last_grant) < SPEECH_COOLDOWN_SECONDS:
            return

        # Verify the user exists in the game
        user = await User.get(self._pool, message.author.id)
        if user is None:
            return

        # Grant XP
        self._cooldowns[message.author.id] = now

        observers = build_observers(
            self._pool,
            message.author.id,
            room_id,
            bot=self.bot,
            guild_id=bot.guild_id,
            room_cache=self._room_cache,
        )

        for obs in observers:
            obs.notify(GrantXPSignal(skill=Skill.SPEECH, amount=SPEECH_XP_PER_MESSAGE))

        try:
            await flush_all(observers)
            await post_flush_all(observers)
        except Exception:
            logger.exception("Failed to grant speech XP to user %d", message.author.id)
