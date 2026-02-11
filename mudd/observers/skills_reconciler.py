"""Discord reconciler for skills channels, nicknames, and milestone roles."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import asyncpg
import discord

if TYPE_CHECKING:
    from mudd.observers.discord import RoomChannelCache

from mudd.events.types import GameEvent, LevelUpEvent, UserLeftEvent, XPGainedEvent
from mudd.models.skills import UserSkill
from mudd.models.skills_channel import UserSkillsChannel
from mudd.models.user import User
from mudd.observers.skills_announcements import SkillsAnnouncements
from mudd.skills.formatting import (
    MILESTONE_ROLE_NAMES,
    format_nickname,
    format_skills_message,
    get_milestone_role,
)
from mudd.skills.registry import Skill
from mudd.utils.discord import normalize_channel_name

logger = logging.getLogger(__name__)

SKILLS_CATEGORY_NAME = "Skills"


def _get_skills_channel_name(username: str) -> str:
    """Get the channel name for a user's skills channel."""
    return normalize_channel_name(username, "skills")


async def ensure_roles(guild: discord.Guild) -> None:
    """Ensure all milestone roles exist in the guild.

    Args:
        guild: Discord guild
    """
    existing = {r.name for r in guild.roles}
    for role_name in MILESTONE_ROLE_NAMES:
        if role_name not in existing:
            try:
                await guild.create_role(name=role_name, reason="Skills milestone role")
                logger.info(
                    "Created milestone role '%s' in %s",
                    role_name,
                    guild.name,
                )
            except Exception:
                logger.exception("Failed to create role '%s'", role_name)


async def ensure_category(guild: discord.Guild) -> discord.CategoryChannel:
    """Ensure the Skills category exists.

    Args:
        guild: Discord guild

    Returns:
        The Skills category channel
    """
    for cat in guild.categories:
        if cat.name == SKILLS_CATEGORY_NAME:
            return cat

    # Create hidden category
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
        ),
    }
    category = await guild.create_category(
        SKILLS_CATEGORY_NAME,
        overwrites=overwrites,
        reason="Skills progression system",
    )
    logger.info("Created Skills category in %s", guild.name)
    return category


class SkillsReconciler:
    """Reconciles Discord state for the skills system.

    Handles:
    - XPGainedEvent: Queues skills channel update
    - LevelUpEvent: Queues level-up announcement + nickname update

    During flush(), executes all queued Discord operations.
    Announcements are always deferred — call post_announcements()
    to send them after the caller is ready.
    """

    def __init__(
        self,
        bot: discord.Client,
        pool: asyncpg.Pool,
        guild_id: int,
        room_cache: RoomChannelCache | None = None,
    ) -> None:
        self._bot = bot
        self._pool = pool
        self._guild_id = guild_id
        self._announcements = SkillsAnnouncements(bot, guild_id, room_cache)
        self._xp_events: list[XPGainedEvent] = []
        self._level_up_events: list[LevelUpEvent] = []
        self._user_left_events: list[UserLeftEvent] = []

    def notify(self, event: GameEvent) -> None:
        """Queue XP and level-up events for processing."""
        match event:
            case XPGainedEvent() as evt:
                self._xp_events.append(evt)
            case LevelUpEvent() as evt:
                self._level_up_events.append(evt)
            case UserLeftEvent() as evt:
                self._user_left_events.append(evt)

    async def flush(self) -> None:
        """Process queued events, deferring announcements to post_announcements()."""
        xp_events = self._xp_events
        self._xp_events = []
        level_up_events = self._level_up_events
        self._level_up_events = []
        user_left_events = self._user_left_events
        self._user_left_events = []

        # Collect unique user IDs that need updates and aggregate deltas
        user_ids: set[int] = set()
        user_deltas: dict[int, dict[Skill, int]] = {}
        for evt in xp_events:
            user_ids.add(evt.user_id)
            deltas = user_deltas.setdefault(evt.user_id, {})
            deltas[evt.skill] = deltas.get(evt.skill, 0) + (evt.new_xp - evt.old_xp)
        for evt in level_up_events:
            user_ids.add(evt.user_id)

        # Fetch skills once per user and run all updates
        for user_id in user_ids:
            skills = await UserSkill.get_all(self._pool, user_id)
            total_level = sum(s.level for s in skills)
            deltas = user_deltas.get(user_id)

            try:
                await self._update_skills_channel(
                    user_id, skills, total_level, deltas=deltas
                )
            except Exception:
                logger.exception(
                    "Failed to update skills channel for user %d",
                    user_id,
                )

            try:
                await self._update_nickname(user_id, total_level)
            except Exception:
                logger.exception(
                    "Failed to update nickname for user %d",
                    user_id,
                )

            try:
                await self._update_milestone_role(user_id, total_level)
            except Exception:
                logger.exception(
                    "Failed to update milestone role for user %d",
                    user_id,
                )

        # Handle user departures
        guild = self._bot.get_guild(self._guild_id)
        if guild is not None:
            for evt in user_left_events:
                await self._handle_user_left(guild, evt)

        # Prepare level-up announcements (sent later via post_announcements)
        logger.info(
            "SkillsReconciler flushing %d level-up events",
            len(level_up_events),
        )
        for evt in level_up_events:
            try:
                self._announcements.prepare(evt)
            except Exception:
                logger.exception(
                    "Failed to prepare level-up announcement for user %d",
                    evt.user_id,
                )

    async def post_announcements(self) -> None:
        """Send all pending level-up announcements and clear them."""
        await self._announcements.post_announcements()

    async def sync_user(self, guild: discord.Guild, member: discord.Member) -> None:
        """Full skills sync for a single user during periodic sync.

        Creates/updates their skills channel, nickname, and role.

        Args:
            guild: Discord guild
            member: Guild member to sync
        """
        user_id = member.id
        await UserSkill.create_defaults(self._pool, user_id)
        skills = await UserSkill.get_all(self._pool, user_id)
        total_level = sum(s.level for s in skills)

        try:
            channel_id = await self._ensure_skills_channel(guild, user_id)
            await self._update_skills_channel(user_id, skills, total_level)

            # Repair thread/command permissions on existing channels
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                expected_name = _get_skills_channel_name(member.name)
                if channel.name != expected_name:
                    try:
                        await channel.edit(name=expected_name)
                        logger.info(
                            "Renamed skills channel '%s' -> '%s' for user %d",
                            channel.name,
                            expected_name,
                            user_id,
                        )
                    except discord.HTTPException as e:
                        logger.error(
                            "Failed to rename skills channel %d: %s",
                            channel.id,
                            e,
                        )

                overwrites = channel.overwrites_for(member)
                if overwrites.create_public_threads is not False:
                    await channel.set_permissions(
                        member,
                        view_channel=True,
                        send_messages=False,
                        create_public_threads=False,
                        create_private_threads=False,
                        send_messages_in_threads=False,
                        use_application_commands=False,
                    )
        except Exception:
            logger.exception(
                "Failed to sync skills channel for user %d",
                user_id,
            )

        try:
            await self._update_nickname(user_id, total_level)
        except Exception:
            logger.exception("Failed to sync nickname for user %d", user_id)

        try:
            await self._update_milestone_role(user_id, total_level)
        except Exception:
            logger.exception(
                "Failed to sync milestone role for user %d",
                user_id,
            )

    async def _ensure_skills_channel(self, guild: discord.Guild, user_id: int) -> int:
        """Ensure a per-user skills channel exists.

        Args:
            guild: Discord guild
            user_id: Discord user ID

        Returns:
            Channel ID
        """
        # Check DB first
        record = await UserSkillsChannel.get(self._pool, user_id)
        if record is not None:
            channel = guild.get_channel(record.channel_id)
            if channel is not None:
                return record.channel_id
            # Channel was deleted from Discord, clear stale DB record
            logger.info(
                "Skills channel %d was deleted from Discord, "
                "clearing DB record for user %d",
                record.channel_id,
                user_id,
            )
            await UserSkillsChannel.delete_by_user(self._pool, user_id)

        # Look up member and expected name
        category = await ensure_category(guild)
        member = guild.get_member(user_id)
        if member is None:
            raise ValueError(f"Member {user_id} not in guild")

        channel_name = _get_skills_channel_name(member.name)

        # Try to recover existing channel by name (e.g. after DB reset)
        matching = [
            ch
            for ch in category.channels
            if isinstance(ch, discord.TextChannel) and ch.name == channel_name
        ]
        matching.sort(key=lambda ch: ch.id)

        if matching:
            recovered = matching[0]
            # Delete duplicates
            for dup in matching[1:]:
                try:
                    await dup.delete(
                        reason="Duplicate skills channel cleanup during sync"
                    )
                    logger.info("Deleted duplicate skills channel (ID: %d)", dup.id)
                except discord.HTTPException as e:
                    logger.error("Failed to delete duplicate channel %d: %s", dup.id, e)

            await UserSkillsChannel.create_or_update(
                self._pool, user_id, recovered.id, category.id
            )
            logger.info(
                "Recovered skills channel '%s' (ID: %d) for user %d",
                recovered.name,
                recovered.id,
                user_id,
            )
            return recovered.id

        # Create new channel
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                create_public_threads=False,
                create_private_threads=False,
                send_messages_in_threads=False,
                use_application_commands=False,
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
            ),
        }
        channel = await guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites,
            reason="Per-user skills channel",
        )

        await UserSkillsChannel.create_or_update(
            self._pool,
            user_id,
            channel.id,
            category.id,
        )

        logger.info(
            "Created skills channel for user %d in %s",
            user_id,
            guild.name,
        )
        return channel.id

    async def _update_skills_channel(
        self,
        user_id: int,
        skills: list[UserSkill],
        total_level: int,
        *,
        deltas: dict[Skill, int] | None = None,
    ) -> None:
        """Update the skills overview message in the user's channel.

        Args:
            user_id: Discord user ID
            skills: Pre-fetched list of user skills
            total_level: Pre-computed total level
            deltas: Optional XP deltas per skill to show (+N) indicators
        """
        record = await UserSkillsChannel.get(self._pool, user_id)
        if record is None:
            return

        channel_id = record.channel_id
        message_id = record.message_id

        # Find the channel across all guilds
        channel = self._bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        # Build message content
        member = channel.guild.get_member(user_id)
        display_name = member.display_name if member else str(user_id)
        content = format_skills_message(skills, total_level, display_name, deltas)

        if message_id is not None:
            # Try to edit existing message
            try:
                msg = await channel.fetch_message(message_id)
                await msg.edit(content=content)
                return
            except discord.NotFound:
                pass  # Message deleted, create new one

        # Send new message and store ID
        msg = await channel.send(content)
        await UserSkillsChannel.update_message_id(self._pool, user_id, msg.id)

    async def _update_nickname(self, user_id: int, total_level: int) -> None:
        """Update user's nickname with total level.

        Args:
            user_id: Discord user ID
            total_level: Pre-computed total level
        """

        guild = self._bot.get_guild(self._guild_id)
        if guild is None:
            return

        member = guild.get_member(user_id)
        if member is None:
            return
        if member.id == guild.owner_id:
            return

        nick = format_nickname(member.display_name, total_level)
        try:
            await member.edit(nick=nick)
            await User.update_display_name(self._pool, user_id, nick)
        except discord.Forbidden:
            logger.warning(
                "Cannot edit nickname for %s (owner?)",
                member.display_name,
            )

    async def _update_milestone_role(self, user_id: int, total_level: int) -> None:
        """Update milestone role for a user.

        Removes old milestone roles and assigns the new one.

        Args:
            user_id: Discord user ID
            total_level: Pre-computed total level
        """
        target_role_name = get_milestone_role(total_level)

        guild = self._bot.get_guild(self._guild_id)
        if guild is None:
            return

        member = guild.get_member(user_id)
        if member is None:
            return

        # Build set of milestone role objects
        milestone_roles = {r for r in guild.roles if r.name in MILESTONE_ROLE_NAMES}

        # Current milestone roles on the member
        current = milestone_roles & set(member.roles)

        if target_role_name is None:
            # Remove all milestone roles
            for role in current:
                await member.remove_roles(role)
            return

        # Find target role
        target_role = discord.utils.get(guild.roles, name=target_role_name)
        if target_role is None:
            return

        # Remove wrong roles, add correct one
        for role in current:
            if role != target_role:
                await member.remove_roles(role)

        if target_role not in member.roles:
            await member.add_roles(target_role)

    async def _handle_user_left(
        self, guild: discord.Guild, event: UserLeftEvent
    ) -> None:
        """Handle a user leaving: clean up their skills channel."""
        record = await UserSkillsChannel.get(self._pool, event.user_id)
        if record is None:
            return
        channel = guild.get_channel(record.channel_id)
        if channel:
            try:
                await channel.delete()
                logger.info(
                    "Deleted skills channel for departing user %d",
                    event.user_id,
                )
            except discord.HTTPException as e:
                logger.error(
                    "Failed to delete skills channel for %d: %s",
                    event.user_id,
                    e,
                )

    async def prune_orphan_channels(self, guild: discord.Guild) -> int:
        """Delete skills channels not tracked in the database.

        Args:
            guild: Discord guild

        Returns:
            Number of channels pruned
        """
        category = None
        for cat in guild.categories:
            if cat.name == SKILLS_CATEGORY_NAME:
                category = cat
                break

        if category is None:
            return 0

        valid_ids = await UserSkillsChannel.get_all_channel_ids(self._pool)
        pruned = 0

        for channel in list(category.channels):
            if channel.id not in valid_ids:
                try:
                    await channel.delete(reason="Orphan skills channel pruning")
                    logger.info(
                        "Pruned orphan skills channel '%s' (ID: %d)",
                        channel.name,
                        channel.id,
                    )
                    pruned += 1
                except discord.HTTPException as e:
                    logger.error(
                        "Failed to prune skills channel %d: %s",
                        channel.id,
                        e,
                    )

        return pruned
