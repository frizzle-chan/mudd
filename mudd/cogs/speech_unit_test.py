"""Unit tests for the Speech cog filtering and cooldown logic."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mudd.cogs.speech import SPEECH_COOLDOWN_SECONDS, SPEECH_XP_PER_MESSAGE, Speech
from mudd.skills.registry import Skill


def _make_cog() -> tuple[Speech, MagicMock]:
    """Create a Speech cog with mock dependencies.

    Returns the cog and the mock room_cache so tests can configure it
    without going through the typed attribute.
    """
    bot = MagicMock()
    pool = MagicMock()
    room_cache = MagicMock()
    cog = Speech(bot, pool, room_cache)
    return cog, room_cache


_SENTINEL = object()


def _make_message(
    *,
    author_id: int = 123,
    channel_id: int = 456,
    is_bot: bool = False,
    guild: Any = _SENTINEL,
) -> MagicMock:
    """Create a mock Discord message.

    Pass guild=None to simulate a DM (no guild).
    """
    msg = MagicMock()
    msg.author.bot = is_bot
    msg.author.id = author_id
    msg.guild = MagicMock() if guild is _SENTINEL else guild
    msg.channel.id = channel_id
    return msg


class TestFiltering:
    @pytest.mark.asyncio
    async def test_bot_messages_ignored(self) -> None:
        cog, room_cache = _make_cog()
        msg = _make_message(is_bot=True)
        await cog.on_message(msg)
        # room_cache should never be consulted
        room_cache.get_room_for_channel.assert_not_called()

    @pytest.mark.asyncio
    async def test_dm_messages_ignored(self) -> None:
        cog, room_cache = _make_cog()
        msg = _make_message(guild=None)
        await cog.on_message(msg)
        room_cache.get_room_for_channel.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_room_channel_ignored(self) -> None:
        cog, room_cache = _make_cog()
        room_cache.get_room_for_channel.return_value = None
        msg = _make_message()

        with patch("mudd.cogs.speech.User") as mock_user:
            await cog.on_message(msg)
            mock_user.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_user_ignored(self) -> None:
        """Messages from users not in the game DB are ignored."""
        cog, room_cache = _make_cog()
        room_cache.get_room_for_channel.return_value = "foyer"

        with patch("mudd.cogs.speech.User") as mock_user:
            mock_user.get = AsyncMock(return_value=None)
            with patch("mudd.cogs.speech.build_observers") as mock_build:
                await cog.on_message(_make_message())
                mock_build.assert_not_called()


class TestXPGrant:
    @pytest.mark.asyncio
    async def test_valid_message_grants_xp(self) -> None:
        cog, room_cache = _make_cog()
        room_cache.get_room_for_channel.return_value = "foyer"

        mock_observer = MagicMock()
        with (
            patch("mudd.cogs.speech.User") as mock_user,
            patch(
                "mudd.cogs.speech.build_observers", return_value=[mock_observer]
            ) as mock_build,
            patch("mudd.cogs.speech.flush_all", new_callable=AsyncMock) as mock_flush,
        ):
            mock_user.get = AsyncMock(return_value=MagicMock())
            await cog.on_message(_make_message(author_id=42, channel_id=789))

            mock_build.assert_called_once_with(
                cog._pool, 42, "foyer", bot=cog.bot, room_cache=room_cache
            )
            mock_observer.notify.assert_called_once()
            signal = mock_observer.notify.call_args[0][0]
            assert signal.skill == Skill.SPEECH
            assert signal.amount == SPEECH_XP_PER_MESSAGE
            mock_flush.assert_awaited_once_with([mock_observer])


class TestCooldown:
    @pytest.mark.asyncio
    async def test_cooldown_prevents_rapid_grants(self) -> None:
        cog, room_cache = _make_cog()
        room_cache.get_room_for_channel.return_value = "foyer"

        with (
            patch("mudd.cogs.speech.User") as mock_user,
            patch(
                "mudd.cogs.speech.build_observers",
                return_value=[MagicMock()],
            ) as mock_build,
            patch("mudd.cogs.speech.flush_all", new_callable=AsyncMock),
        ):
            mock_user.get = AsyncMock(return_value=MagicMock())

            # First message: grants XP
            await cog.on_message(_make_message(author_id=42))
            assert mock_build.call_count == 1

            # Second message immediately: blocked by cooldown
            await cog.on_message(_make_message(author_id=42))
            assert mock_build.call_count == 1  # still 1

    @pytest.mark.asyncio
    async def test_different_users_independent_cooldowns(self) -> None:
        cog, room_cache = _make_cog()
        room_cache.get_room_for_channel.return_value = "foyer"

        with (
            patch("mudd.cogs.speech.User") as mock_user,
            patch(
                "mudd.cogs.speech.build_observers",
                return_value=[MagicMock()],
            ) as mock_build,
            patch("mudd.cogs.speech.flush_all", new_callable=AsyncMock),
        ):
            mock_user.get = AsyncMock(return_value=MagicMock())

            await cog.on_message(_make_message(author_id=42))
            await cog.on_message(_make_message(author_id=99))
            assert mock_build.call_count == 2  # both got XP

    @pytest.mark.asyncio
    async def test_cooldown_expires(self) -> None:
        cog, room_cache = _make_cog()
        room_cache.get_room_for_channel.return_value = "foyer"

        with (
            patch("mudd.cogs.speech.User") as mock_user,
            patch(
                "mudd.cogs.speech.build_observers",
                return_value=[MagicMock()],
            ) as mock_build,
            patch("mudd.cogs.speech.flush_all", new_callable=AsyncMock),
            patch("mudd.cogs.speech.time") as mock_time,
        ):
            mock_user.get = AsyncMock(return_value=MagicMock())

            # First message at t=0
            mock_time.monotonic.return_value = 0.0
            await cog.on_message(_make_message(author_id=42))
            assert mock_build.call_count == 1

            # Second message at t=COOLDOWN (exactly at boundary, still within)
            mock_time.monotonic.return_value = SPEECH_COOLDOWN_SECONDS - 0.01
            await cog.on_message(_make_message(author_id=42))
            assert mock_build.call_count == 1  # still blocked

            # Third message at t=COOLDOWN + 1 (expired)
            mock_time.monotonic.return_value = SPEECH_COOLDOWN_SECONDS + 1.0
            await cog.on_message(_make_message(author_id=42))
            assert mock_build.call_count == 2  # granted again
