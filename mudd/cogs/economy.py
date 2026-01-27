"""Economy commands for MUDD."""

import logging
from typing import TYPE_CHECKING
from uuid import UUID

import asyncpg
import discord
from discord import Interaction, app_commands
from discord.ext import commands

from mudd.services.currency import TransferError

if TYPE_CHECKING:
    from mudd.services.currency import CurrencyService
    from mudd.services.entity import EntityService
    from mudd.services.inventory import InventoryService
    from mudd.services.rendering import RenderingService
    from mudd.services.visibility import VisibilityServiceProtocol

logger = logging.getLogger(__name__)


class Economy(commands.Cog):
    """Commands for the in-game economy."""

    def __init__(
        self,
        bot: commands.Bot | None,
        currency_service: "CurrencyService",
        visibility_service: "VisibilityServiceProtocol",
        inventory_service: "InventoryService",
        entity_service: "EntityService",
        rendering_service: "RenderingService",
        pool: asyncpg.Pool,
    ) -> None:
        self.bot = bot
        self.currency_service = currency_service
        self.visibility_service = visibility_service
        self.inventory_service = inventory_service
        self.entity_service = entity_service
        self.rendering_service = rendering_service
        self._pool = pool

    async def recipient_autocomplete(
        self, interaction: Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete for pay recipients - only shows users in the same room."""
        if not interaction.guild:
            return []

        user = interaction.user
        if not isinstance(user, discord.Member):
            return []

        # Get sender's current room (room name, not channel ID)
        sender_room = await self.visibility_service.get_user_room(user.id)
        if sender_room is None:
            return [app_commands.Choice(name="You're not in a room", value="invalid")]

        # Get all user IDs in the same room
        rows = await self._pool.fetch(
            "SELECT id FROM users WHERE current_room = $1", sender_room
        )
        user_ids_in_room = {row["id"] for row in rows}

        # Get guild members for those IDs, filtering out bots and self
        valid_recipients: list[discord.Member] = []
        for user_id in user_ids_in_room:
            if user_id == user.id:
                continue
            # Try cache first, then fetch from API
            member = interaction.guild.get_member(user_id)
            if member is None:
                try:
                    member = await interaction.guild.fetch_member(user_id)
                except discord.NotFound:
                    continue
            if not member.bot:
                valid_recipients.append(member)

        # If no valid recipients, return placeholder
        if not valid_recipients:
            return [app_commands.Choice(name="There's nobody to pay", value="invalid")]

        # Filter by current input (case-insensitive prefix match)
        current_lower = current.lower()
        filtered = [
            m
            for m in valid_recipients
            if m.display_name.lower().startswith(current_lower)
            or m.name.lower().startswith(current_lower)
        ]

        # If filtering yields no results but we have valid recipients,
        # show all valid recipients
        if not filtered and current == "":
            filtered = valid_recipients

        # Sort by display name and limit to 25 (Discord limit)
        filtered.sort(key=lambda m: m.display_name.lower())
        return [
            app_commands.Choice(name=m.display_name, value=str(m.id))
            for m in filtered[:25]
        ]

    @app_commands.command(name="pay", description="Give yen to another player")
    @app_commands.describe(recipient="Player to pay", amount="Amount in yen")
    @app_commands.rename(recipient="to")
    @app_commands.autocomplete(recipient=recipient_autocomplete)
    async def pay(
        self,
        interaction: Interaction,
        recipient: str,
        amount: int,
    ):
        """Transfer yen to another player in the same room."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command must be used in a server.", ephemeral=True
            )
            return

        sender = interaction.user
        if not isinstance(sender, discord.Member):
            await interaction.response.send_message(
                "This command must be used in a server.", ephemeral=True
            )
            return

        # Handle invalid autocomplete selection (e.g., "There's nobody to pay")
        if recipient == "invalid":
            await interaction.response.send_message(
                "No valid recipient selected.", ephemeral=True
            )
            return

        # Resolve recipient from user ID string
        try:
            recipient_id = int(recipient)
        except ValueError:
            await interaction.response.send_message(
                "Invalid recipient.", ephemeral=True
            )
            return

        recipient_member = interaction.guild.get_member(recipient_id)
        if recipient_member is None:
            await interaction.response.send_message(
                "Recipient not found.", ephemeral=True
            )
            return

        # Validate amount
        if amount <= 0:
            await interaction.response.send_message(
                "Amount must be positive.", ephemeral=True
            )
            return

        # Prevent self-payment
        if sender.id == recipient_member.id:
            await interaction.response.send_message(
                "You can't pay yourself.", ephemeral=True
            )
            return

        # Prevent paying bots
        if recipient_member.bot:
            await interaction.response.send_message(
                "You can't pay a bot.", ephemeral=True
            )
            return

        # Check both players are in the same room
        sender_location = await self.visibility_service.get_user_location(sender.id)
        recipient_location = await self.visibility_service.get_user_location(
            recipient_member.id
        )

        if sender_location is None or recipient_location is None:
            await interaction.response.send_message(
                "Could not determine player locations.", ephemeral=True
            )
            return

        if sender_location != recipient_location:
            await interaction.response.send_message(
                f"**{recipient_member.display_name}** is not in the same room.",
                ephemeral=True,
            )
            return

        # Execute transfer
        result = await self.currency_service.transfer(
            sender_id=sender.id,
            recipient_id=recipient_member.id,
            amount=amount,
            memo=f"Payment to {recipient_member.display_name}",
        )

        if not result.success:
            if result.error == TransferError.INSUFFICIENT_BALANCE:
                await interaction.response.send_message(
                    "You don't have enough yen.", ephemeral=True
                )
            elif result.error == TransferError.SENDER_NOT_FOUND:
                await interaction.response.send_message(
                    "You don't have a currency account. Try looking at your wallet.",
                    ephemeral=True,
                )
            elif result.error == TransferError.RECIPIENT_NOT_FOUND:
                name = recipient_member.display_name
                await interaction.response.send_message(
                    f"**{name}** doesn't have a currency account.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Transfer failed. Please try again.", ephemeral=True
                )
            return

        # Format balances for display
        sender_balance = f"\u00a5{result.sender_new_balance:,}"
        recipient_balance = f"\u00a5{result.recipient_new_balance:,}"
        amount_str = f"\u00a5{amount:,}"

        # Update wallet thread descriptions and post notifications
        await self._update_wallet_thread(
            interaction.guild,
            sender.id,
            sender_balance,
            f"\U0001f4e4 Paid {amount_str} to **{recipient_member.display_name}**",
        )
        await self._update_wallet_thread(
            interaction.guild,
            recipient_member.id,
            recipient_balance,
            f"\U0001f4e5 Received {amount_str} from **{sender.display_name}**",
        )

        # Respond with confirmation
        await interaction.response.send_message(
            f"You paid {amount_str} to **{recipient_member.display_name}**.\n"
            f"Your balance: {sender_balance}",
            ephemeral=True,
        )

    async def _update_wallet_thread(
        self,
        guild: discord.Guild,
        user_id: int,
        balance_str: str,
        notification: str,
    ) -> None:
        """Update a user's wallet thread description and post a notification.

        Args:
            guild: Discord guild
            user_id: User whose wallet to update
            balance_str: Formatted balance string (e.g., "\\u00a51,000")
            notification: Notification message to post
        """
        try:
            # Get wallet instance ID from currency account
            wallet_instance_id = await self.currency_service.get_wallet_instance_id(
                user_id
            )
            if wallet_instance_id is None:
                logger.warning(f"No wallet instance found for user {user_id}")
                return

            # Get entity instance to find thread ID
            wallet_instance = await self.entity_service.get_entity_instance(
                UUID(wallet_instance_id)
            )
            if wallet_instance is None:
                logger.warning(f"Wallet instance {wallet_instance_id} not found")
                return

            # Get thread ID from database
            row = await self._pool.fetchrow(
                """
                SELECT discord_thread_id, discord_description_msg_id
                FROM entity_instances WHERE id = $1
                """,
                wallet_instance_id,
            )
            if row is None or row["discord_thread_id"] is None:
                logger.warning(f"No thread for wallet instance {wallet_instance_id}")
                return

            thread_id = row["discord_thread_id"]
            msg_id = row["discord_description_msg_id"]

            # Get thread
            thread = guild.get_thread(thread_id)
            if thread is None:
                logger.warning(f"Thread {thread_id} not found in guild")
                return

            # Render new description with updated balance
            new_description = await self.rendering_service.render_entity_on_look(
                wallet_instance,
                self.entity_service,
                None,  # room is None for inventory items
                balance_str,
            )

            # Update thread description message
            if msg_id:
                try:
                    message = await thread.fetch_message(msg_id)
                    await message.edit(content=new_description)
                except discord.NotFound:
                    logger.warning(f"Description message {msg_id} not found")
                except discord.HTTPException as e:
                    logger.error(f"Failed to update wallet description: {e}")

            # Post notification
            try:
                await thread.send(notification)
            except discord.HTTPException as e:
                logger.error(f"Failed to post wallet notification: {e}")

        except Exception:
            logger.exception(f"Failed to update wallet thread for user {user_id}")
