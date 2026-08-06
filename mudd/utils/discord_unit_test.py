"""Unit tests for Discord utility helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import discord

from mudd.utils.discord import is_older_than, normalize_channel_name

NOW = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)
ONE_HOUR = timedelta(hours=1)


def snowflake_at(moment: datetime) -> int:
    return discord.utils.time_snowflake(moment)


class TestIsOlderThan:
    def test_well_past_the_threshold(self) -> None:
        assert is_older_than(snowflake_at(NOW - timedelta(days=180)), NOW, ONE_HOUR)

    def test_just_past_the_threshold(self) -> None:
        created = NOW - ONE_HOUR - timedelta(seconds=1)
        assert is_older_than(snowflake_at(created), NOW, ONE_HOUR)

    def test_just_inside_the_threshold(self) -> None:
        created = NOW - ONE_HOUR + timedelta(seconds=1)
        assert not is_older_than(snowflake_at(created), NOW, ONE_HOUR)

    def test_created_now(self) -> None:
        assert not is_older_than(snowflake_at(NOW), NOW, ONE_HOUR)

    def test_created_in_the_future(self) -> None:
        future = NOW + timedelta(minutes=5)
        assert not is_older_than(snowflake_at(future), NOW, ONE_HOUR)

    def test_zero_delta_treats_anything_past_as_old(self) -> None:
        created = NOW - timedelta(seconds=1)
        assert is_older_than(snowflake_at(created), NOW, timedelta(0))


class TestNormalizeChannelName:
    def test_strips_disallowed_characters(self) -> None:
        assert normalize_channel_name("John.Doe!", "inventory") == "johndoe-inventory"

    def test_spaces_become_hyphens(self) -> None:
        result = normalize_channel_name("Molly Computer", "skills")
        assert result == "molly-computer-skills"
