"""Movement commands for MUDD."""

import re

import discord
from discord import Interaction, app_commands
from discord.ext import commands

from mudd.services.visibility import get_visibility_service

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
    """
    Find the first valid exit mentioned in user input.

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

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="move", description="Move to another location")
    @app_commands.describe(destination="Where you want to go")
    async def move(self, interaction: Interaction, destination: str):
        """Move to a different location."""
        service = get_visibility_service()

        await service.wait_for_startup()

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

        old_location_id = await service.get_user_location(member.id)
        old_channel = (
            interaction.guild.get_channel(old_location_id) if old_location_id else None
        )

        try:
            moved = await service.move_user_to_channel(member, target.id)

            if moved:
                await interaction.response.send_message(
                    f"You moved! Click {target.mention} to enter.", ephemeral=True
                )

                if old_channel and isinstance(old_channel, discord.TextChannel):
                    await old_channel.send(f"{member.mention} has left")

                await target.send(f"{member.mention} entered")
            else:
                await interaction.response.send_message(
                    "You're already there.", ephemeral=True
                )
        except Exception:
            await interaction.response.send_message(
                "Failed to move. Please try again.", ephemeral=True
            )
            raise

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Assign new members to the default location."""
        if member.bot:
            return

        service = get_visibility_service()
        await service.wait_for_startup()

        await service.move_user_to_channel(member, service.default_channel_id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Clean up Redis when member leaves."""
        service = get_visibility_service()
        await service.delete_user_location(member.id)
