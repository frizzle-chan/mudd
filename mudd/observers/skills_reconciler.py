"""Discord reconciler for skills channels, nicknames, and milestone roles."""

from __future__ import annotations

import logging

import asyncpg
import discord

from mudd.events.types import GameEvent, LevelUpEvent, XPGainedEvent
from mudd.models.skills import UserSkill
from mudd.models.skills_channel import UserSkillsChannel
from mudd.skills.formatting import (
    MILESTONE_ROLE_NAMES,
    format_level_up_message,
    format_nickname,
    format_skills_message,
    get_milestone_role,
)

logger = logging.getLogger(__name__)

SKILLS_CATEGORY_NAME = "Skills"


class SkillsReconciler:
    """Reconciles Discord state for the skills system.

    Handles:
    - XPGainedEvent: Queues skills channel update
    - LevelUpEvent: Queues level-up announcement + nickname update

    During flush(), executes all queued Discord operations.
    """

    def __init__(
        self,
        bot: discord.Client,
        pool: asyncpg.Pool,
    ) -> None:
        self._bot = bot
        self._pool = pool
        self._xp_events: list[XPGainedEvent] = []
        self._level_up_events: list[LevelUpEvent] = []

    def notify(self, event: GameEvent) -> None:
        """Queue XP and level-up events for processing."""
        match event:
            case XPGainedEvent() as evt:
                self._xp_events.append(evt)
            case LevelUpEvent() as evt:
                self._level_up_events.append(evt)

    async def flush(self) -> None:
        """Process queued events."""
        # Collect unique user IDs that need updates
        user_ids: set[int] = set()
        for evt in self._xp_events:
            user_ids.add(evt.user_id)
        for evt in self._level_up_events:
            user_ids.add(evt.user_id)

        # Fetch skills once per user and run all updates
        for user_id in user_ids:
            skills = await UserSkill.get_all(self._pool, user_id)
            total_level = sum(s.level for s in skills)

            try:
                await self._update_skills_channel(user_id, skills, total_level)
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

        # Post level-up announcements
        for evt in self._level_up_events:
            try:
                await self._announce_level_up(evt)
            except Exception:
                logger.exception(
                    "Failed to announce level-up for user %d",
                    evt.user_id,
                )

        self._xp_events.clear()
        self._level_up_events.clear()

    async def sync_user(self, guild: discord.Guild, member: discord.Member) -> None:
        """Full skills sync for a single user during periodic sync.

        Creates/updates their skills channel, nickname, and role.

        Args:
            guild: Discord guild
            member: Guild member to sync
        """
        user_id = member.id
        skills = await UserSkill.get_all(self._pool, user_id)
        total_level = sum(s.level for s in skills)

        try:
            channel_id = await self._ensure_skills_channel(guild, user_id)
            await self._update_skills_channel(user_id, skills, total_level)

            # Repair thread/command permissions on existing channels
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
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

    async def ensure_roles(self, guild: discord.Guild) -> None:
        """Ensure all milestone roles exist in the guild.

        Args:
            guild: Discord guild
        """
        existing = {r.name for r in guild.roles}
        for role_name in MILESTONE_ROLE_NAMES:
            if role_name not in existing:
                try:
                    await guild.create_role(
                        name=role_name, reason="Skills milestone role"
                    )
                    logger.info(
                        "Created milestone role '%s' in %s",
                        role_name,
                        guild.name,
                    )
                except Exception:
                    logger.exception("Failed to create role '%s'", role_name)

    async def ensure_category(self, guild: discord.Guild) -> discord.CategoryChannel:
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

        # Create channel
        category = await self.ensure_category(guild)
        member = guild.get_member(user_id)
        if member is None:
            raise ValueError(f"Member {user_id} not in guild")

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
            f"{member.display_name}-skills",
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
    ) -> None:
        """Update the skills overview message in the user's channel.

        Args:
            user_id: Discord user ID
            skills: Pre-fetched list of user skills
            total_level: Pre-computed total level
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
        content = format_skills_message(skills, total_level)

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

    async def _announce_level_up(self, event: LevelUpEvent) -> None:
        """Post a level-up announcement to the user's room channel.

        Args:
            event: LevelUpEvent with user/skill/level info
        """
        # Find the room channel by name across guilds
        for guild in self._bot.guilds:
            member = guild.get_member(event.user_id)
            if member is None:
                continue

            # Find room channel by iterating text channels
            for channel in guild.text_channels:
                if channel.name == event.room_id:
                    message = format_level_up_message(
                        member.display_name,
                        event.skill,
                        event.new_level,
                    )
                    await channel.send(message)
                    return

    async def _update_nickname(self, user_id: int, total_level: int) -> None:
        """Update user's nickname with total level.

        Args:
            user_id: Discord user ID
            total_level: Pre-computed total level
        """

        for guild in self._bot.guilds:
            member = guild.get_member(user_id)
            if member is None:
                continue

            nick = format_nickname(member.display_name, total_level)
            try:
                await member.edit(nick=nick)
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

        for guild in self._bot.guilds:
            member = guild.get_member(user_id)
            if member is None:
                continue

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
