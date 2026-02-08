"""Unit tests for SkillsReconciler thread/command permission restrictions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from mudd.observers.skills_reconciler import SkillsReconciler


def _make_reconciler() -> SkillsReconciler:
    return SkillsReconciler(
        bot=MagicMock(spec=discord.Client),
        pool=MagicMock(),
    )


def _make_guild(
    member: discord.Member,
    *,
    existing_channel: discord.TextChannel | None = None,
) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.get_member.return_value = member
    guild.default_role = MagicMock(spec=discord.Role)
    guild.me = MagicMock(spec=discord.Member)
    guild.categories = []
    guild.get_channel.return_value = existing_channel

    # ensure_category creates the category
    category = MagicMock(spec=discord.CategoryChannel)
    guild.create_category = AsyncMock(return_value=category)

    return guild


class TestEnsureSkillsChannelOverwrites:
    @pytest.mark.asyncio
    async def test_new_channel_denies_threads_and_commands(self) -> None:
        """When creating a new skills channel, overwrites deny thread creation
        and application commands."""
        reconciler = _make_reconciler()
        member = MagicMock(spec=discord.Member)
        member.id = 123
        member.display_name = "TestUser"

        new_channel = MagicMock(spec=discord.TextChannel)
        new_channel.id = 456

        guild = _make_guild(member)
        guild.create_text_channel = AsyncMock(return_value=new_channel)

        with (
            patch(
                "mudd.observers.skills_reconciler.UserSkillsChannel.get",
                return_value=None,
            ),
            patch(
                "mudd.observers.skills_reconciler.UserSkillsChannel.create_or_update",
                new_callable=AsyncMock,
            ),
        ):
            channel_id = await reconciler._ensure_skills_channel(guild, 123)

        assert channel_id == 456

        # Extract the overwrites dict passed to create_text_channel
        call_kwargs = guild.create_text_channel.call_args
        overwrites = call_kwargs.kwargs.get(
            "overwrites", call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
        )

        # Find the member overwrite
        member_overwrite = overwrites[member]
        assert member_overwrite.create_public_threads is False
        assert member_overwrite.create_private_threads is False
        assert member_overwrite.send_messages_in_threads is False
        assert member_overwrite.use_application_commands is False
        assert member_overwrite.view_channel is True
        assert member_overwrite.send_messages is False


class TestSyncUserPermissionRepair:
    @pytest.mark.asyncio
    async def test_repairs_when_threads_not_denied(self) -> None:
        """sync_user calls set_permissions when create_public_threads is not False."""
        reconciler = _make_reconciler()
        member = MagicMock(spec=discord.Member)
        member.id = 123

        # Existing channel with wrong permissions
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 789
        bad_overwrites = MagicMock(spec=discord.PermissionOverwrite)
        bad_overwrites.create_public_threads = None  # not denied
        channel.overwrites_for.return_value = bad_overwrites
        channel.set_permissions = AsyncMock()

        guild = _make_guild(member, existing_channel=channel)

        with (
            patch.object(
                reconciler,
                "_ensure_skills_channel",
                new_callable=AsyncMock,
                return_value=789,
            ),
            patch.object(reconciler, "_update_skills_channel", new_callable=AsyncMock),
            patch.object(reconciler, "_update_nickname", new_callable=AsyncMock),
            patch.object(reconciler, "_update_milestone_role", new_callable=AsyncMock),
            patch(
                "mudd.observers.skills_reconciler.UserSkill.get_all",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            await reconciler.sync_user(guild, member)

        channel.set_permissions.assert_awaited_once_with(
            member,
            view_channel=True,
            send_messages=False,
            create_public_threads=False,
            create_private_threads=False,
            send_messages_in_threads=False,
            use_application_commands=False,
        )

    @pytest.mark.asyncio
    async def test_skips_repair_when_permissions_correct(self) -> None:
        """sync_user does not call set_permissions when threads already denied."""
        reconciler = _make_reconciler()
        member = MagicMock(spec=discord.Member)
        member.id = 123

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 789
        good_overwrites = MagicMock(spec=discord.PermissionOverwrite)
        good_overwrites.create_public_threads = False  # already correct
        channel.overwrites_for.return_value = good_overwrites
        channel.set_permissions = AsyncMock()

        guild = _make_guild(member, existing_channel=channel)

        with (
            patch.object(
                reconciler,
                "_ensure_skills_channel",
                new_callable=AsyncMock,
                return_value=789,
            ),
            patch.object(reconciler, "_update_skills_channel", new_callable=AsyncMock),
            patch.object(reconciler, "_update_nickname", new_callable=AsyncMock),
            patch.object(reconciler, "_update_milestone_role", new_callable=AsyncMock),
            patch(
                "mudd.observers.skills_reconciler.UserSkill.get_all",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            await reconciler.sync_user(guild, member)

        channel.set_permissions.assert_not_awaited()
