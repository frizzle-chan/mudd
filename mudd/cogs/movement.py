"""Movement commands for MUDD."""

import logging
import re
from typing import cast

import asyncpg
import discord
from discord import Interaction, app_commands
from discord.ext import commands

from mudd.events import InventorySyncEvent, UserLeftEvent, UserSyncEvent
from mudd.models.user import User
from mudd.observers import DiscordReconciler, FocusClearingObserver, RoomChannelCache

logger = logging.getLogger(__name__)

PLAINTEXT_CHANNEL_PATTERN = re.compile(r"#([\w-]+)")


def extract_exits_from_topic(
    topic: str | None, guild: discord.Guild
) -> list[discord.TextChannel]:
    """Extract valid exit channels from a channel's topic (plaintext #channel-name)."""
    if not topic:
        return []

    channel_by_name = {ch.name.lower(): ch for ch in guild.text_channels}

    exits: list[discord.TextChannel] = []
    for match in PLAINTEXT_CHANNEL_PATTERN.finditer(topic):
        name = match.group(1).lower()
        if name in channel_by_name:
            exits.append(channel_by_name[name])

    return exits


def find_exit_in_input(
    text: str, valid_exits: list[discord.TextChannel]
) -> discord.TextChannel | None:
    """Find the first valid exit mentioned in user input.

    Scans for #channel mentions first, then channel names (case-insensitive).
    """
    if not valid_exits:
        return None

    valid_exit_names = {ch.name.lower(): ch for ch in valid_exits}

    for match in PLAINTEXT_CHANNEL_PATTERN.finditer(text):
        name = match.group(1).lower()
        if name in valid_exit_names:
            return valid_exit_names[name]

    text_lower = text.lower()
    for exit_ch in valid_exits:
        if exit_ch.name.lower() in text_lower:
            return exit_ch

    return None


class Movement(commands.Cog):
    """Commands for moving between locations."""

    def __init__(
        self,
        bot: commands.Bot | None,
        pool: asyncpg.Pool,
        room_cache: RoomChannelCache,
    ) -> None:
        self.bot = bot
        self._pool = pool
        self.room_cache = room_cache

    async def destination_autocomplete(
        self, interaction: Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete callback for the destination parameter."""
        if not interaction.guild:
            return []

        channel = interaction.channel
        topic = getattr(channel, "topic", None)
        valid_exits = extract_exits_from_topic(topic, interaction.guild)

        # Filter exits based on current input (case-insensitive)
        current_lower = current.lower()
        choices = [
            app_commands.Choice(name=f"#{exit_ch.name}", value=exit_ch.name)
            for exit_ch in valid_exits
            if exit_ch.name.lower().startswith(current_lower)
        ]

        # Discord limits autocomplete to 25 choices
        return choices[:25]

    @app_commands.command(name="move", description="Move to another location")
    @app_commands.describe(destination="Where you want to go")
    @app_commands.autocomplete(destination=destination_autocomplete)
    async def move(self, interaction: Interaction, destination: str):
        """Move to a different location."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command must be used in a server.", ephemeral=True
            )
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "This command must be used in a server.", ephemeral=True
            )
            return

        channel = interaction.channel
        topic = getattr(channel, "topic", None)
        valid_exits = extract_exits_from_topic(topic, interaction.guild)

        if not valid_exits:
            await interaction.response.send_message(
                "There are no obvious exits.", ephemeral=True
            )
            return

        target = find_exit_in_input(destination, valid_exits)

        if target is None:
            exit_list = ", ".join(f"#{ch.name}" for ch in valid_exits)
            await interaction.response.send_message(
                f"You can't go there. Exits: {exit_list}", ephemeral=True
            )
            return

        # Get user via model
        user = await User.get(self._pool, member.id)
        if user is None:
            user = await User.get_or_create(self._pool, member.id)

        # Check if already in target room
        target_room = self.room_cache.get_room_for_channel(target.id)
        if target_room is None:
            await interaction.response.send_message(
                "That destination is not a valid room.", ephemeral=True
            )
            return

        if user.current_room == target_room:
            await interaction.response.send_message(
                "You're already there.", ephemeral=True
            )
            return

        old_room = user.current_room
        old_channel_id = self.room_cache.get_channel_for_room(old_room)
        old_channel = (
            interaction.guild.get_channel(old_channel_id) if old_channel_id else None
        )

        try:
            # Create observers
            focus_observer = FocusClearingObserver(self._pool)
            reconciler = DiscordReconciler(
                cast(discord.Client, self.bot),
                self._pool,
                room_cache=self.room_cache,
            )

            # Attach observers and move
            user_with_observers = user.with_observers(focus_observer, reconciler)
            await user_with_observers.move_to(
                target_room, guild_id=interaction.guild.id
            )

            # Defer response to give us time for permission sync
            await interaction.response.defer(ephemeral=True)

            # Flush observers (syncs permissions, clears focus)
            await reconciler.flush()
            await focus_observer.flush()

            # Send followup (user now has access to target channel)
            await interaction.followup.send(
                f"You moved! Click {target.mention} to enter.", ephemeral=True
            )

            # Announce movement
            if old_channel and isinstance(old_channel, discord.TextChannel):
                await old_channel.send(
                    f"**{member.display_name}** moved to {target.name}"
                )

            await target.send(f"{member.mention} entered")

        except Exception:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Failed to move. Please try again.", ephemeral=True
                )
            raise

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Assign new members to the default location and create inventory forum."""
        if member.bot:
            return

        try:
            # Get default room
            default_room = await self.room_cache.get_default_room()

            # Create reconciler and emit events
            reconciler = DiscordReconciler(
                cast(discord.Client, self.bot),
                self._pool,
                room_cache=self.room_cache,
            )

            # Emit UserSyncEvent - creates user with display_name and grants permissions
            reconciler.notify(
                UserSyncEvent(
                    user_id=member.id,
                    display_name=member.display_name,
                    default_room=default_room,
                    guild_id=member.guild.id,
                )
            )

            # Emit InventorySyncEvent for inventory forum creation
            reconciler.notify(
                InventorySyncEvent(guild_id=member.guild.id, user_id=member.id)
            )

            await reconciler.flush()

            logger.info(f"New member {member.id} spawned in {default_room}")
        except Exception:
            logger.exception("Failed to handle member join for %s", member.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Clean up user data when member leaves."""
        try:
            # Create reconciler and emit event
            reconciler = DiscordReconciler(
                cast(discord.Client, self.bot),
                self._pool,
                room_cache=self.room_cache,
            )

            reconciler.notify(
                UserLeftEvent(user_id=member.id, guild_id=member.guild.id)
            )

            # Flush to delete inventory forum
            await reconciler.flush()

            # Delete user from database (CASCADE handles related records)
            await User.delete(self._pool, member.id)

            logger.info(f"Cleaned up data for departing member {member.id}")
        except Exception:
            logger.exception("Failed to clean up for member %s", member.id)
