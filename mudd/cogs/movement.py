"""Movement commands for MUDD."""

import logging
import re
from typing import TYPE_CHECKING

import discord
from discord import Interaction, app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from mudd.services.inventory import InventoryService
    from mudd.services.player_context import PlayerContextService
    from mudd.services.visibility import VisibilityServiceProtocol

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

    def __init__(
        self,
        bot: commands.Bot | None,
        visibility_service: "VisibilityServiceProtocol",
        player_context: "PlayerContextService",
        inventory_service: "InventoryService",
    ) -> None:
        self.bot = bot
        self.visibility_service = visibility_service
        self.player_context = player_context
        self.inventory_service = inventory_service

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
        await self.visibility_service.wait_for_startup()

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

        old_location_id = await self.visibility_service.get_user_location(member.id)
        old_channel = (
            interaction.guild.get_channel(old_location_id) if old_location_id else None
        )

        try:
            moved = await self.visibility_service.move_user_to_channel(
                member, target.id
            )

            if moved:
                # Clear focus when moving rooms (per ADR 0003)
                await self.player_context.clear_focus(member.id, reason="movement")

                await interaction.response.send_message(
                    f"You moved! Click {target.mention} to enter.", ephemeral=True
                )

                if old_channel and isinstance(old_channel, discord.TextChannel):
                    await old_channel.send(
                        f"**{member.display_name}** moved to {target.name}"
                    )

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
        """Assign new members to the default location and create inventory forum."""
        if member.bot:
            return

        try:
            await self.visibility_service.wait_for_startup()
            default_channel_id = await self.visibility_service.get_default_channel_id()
            if default_channel_id:
                await self.visibility_service.move_user_to_channel(
                    member, default_channel_id
                )
            else:
                default_room = await self.visibility_service.get_default_room()
                logger.error(
                    f"Cannot assign default location to {member.id}: "
                    f"default room '{default_room}' not found"
                )

            # Create inventory forum for new member
            await self.inventory_service.ensure_user_forum(member.guild, member.id)
        except Exception:
            logger.exception("Failed to assign default location to %s", member.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Clean up user location, focus, and inventory forum when member leaves."""
        try:
            # Delete inventory forum first (needs guild context before DB cleanup)
            forum_data = await self.inventory_service.get_user_forum_from_db(member.id)
            if forum_data:
                forum = member.guild.get_channel(forum_data.forum_id)
                if forum:
                    try:
                        await forum.delete()
                        logger.info(
                            f"Deleted inventory forum for departing user {member.id}"
                        )
                    except discord.HTTPException as e:
                        logger.error(
                            f"Failed to delete inventory forum for {member.id}: {e}"
                        )

            # Database cleanup (CASCADE will handle user_inventory_forums)
            await self.visibility_service.delete_user_location(member.id)

            # Clean up focus context
            await self.player_context.clear_focus(member.id, reason="interaction")
        except Exception:
            logger.exception("Failed to clean up for member %s", member.id)
