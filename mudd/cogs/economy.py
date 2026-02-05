"""Economy commands for MUDD."""

import logging

import asyncpg
import discord
from discord import Interaction, app_commands
from discord.ext import commands
from rapidfuzz import fuzz

from mudd.models.user import TransferError
from mudd.observers import DiscordReconciler, EffectsObserver
from mudd.scene import Scene

logger = logging.getLogger(__name__)


class Economy(commands.Cog):
    """Commands for the in-game economy."""

    def __init__(
        self,
        bot: commands.Bot | None,
        pool: asyncpg.Pool,
    ) -> None:
        self.bot = bot
        self._pool = pool

    async def recipient_autocomplete(
        self, interaction: Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete for pay recipients - only shows users in the same room.

        Uses database-driven autocomplete with fuzzy matching on display_name.
        """
        if not interaction.guild:
            return []

        user = interaction.user
        if not isinstance(user, discord.Member):
            return []

        # Build scene to get other players from DB
        try:
            scene = await Scene.from_interaction(self._pool, interaction)
        except ValueError:
            return [app_commands.Choice(name="You're not in a room", value="invalid")]

        other_players = await scene.other_players()
        if not other_players:
            return [app_commands.Choice(name="There's nobody to pay", value="invalid")]

        # Filter to players with display names (skip unsynced users)
        players_with_names = [p for p in other_players if p.display_name]

        # Fuzzy match on display_name (same pattern as entity autocomplete)
        if current:
            current_lower = current.lower()
            matches = [
                p
                for p in players_with_names
                if fuzz.partial_ratio(current_lower, p.display_name.lower()) >= 75
            ]
        else:
            matches = players_with_names

        if not matches:
            return [app_commands.Choice(name="There's nobody to pay", value="invalid")]

        # Sort by display name and limit to 25 (Discord limit)
        matches.sort(key=lambda p: p.display_name.lower())
        return [
            app_commands.Choice(name=p.display_name, value=str(p.id))
            for p in matches[:25]
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

        # Build scene with observers
        effects = EffectsObserver()
        try:
            scene = await Scene.from_interaction(self._pool, interaction)
        except ValueError:
            await interaction.response.send_message(
                "Could not determine your location.", ephemeral=True
            )
            return

        if self.bot:
            reconciler = DiscordReconciler(self.bot, self._pool)
            scene = scene.with_observers(effects, reconciler)
        else:
            scene = scene.with_observers(effects)

        # Get recipient from other_players
        other_players = await scene.other_players()
        recipient_user = next((p for p in other_players if p.id == recipient_id), None)
        if recipient_user is None:
            await interaction.response.send_message(
                f"**{recipient_member.display_name}** is not in the same room.",
                ephemeral=True,
            )
            return

        # Execute transfer (scene.user already has observers from with_observers)
        memo = f"Payment to {recipient_member.display_name}"
        result = await scene.user.transfer_currency_to(recipient_user, amount, memo)

        if not result.success:
            match result.error:
                case TransferError.INSUFFICIENT_FUNDS:
                    msg = "You don't have enough yen."
                case TransferError.NO_SENDER_ACCOUNT:
                    msg = (
                        "You don't have a currency account. Try looking at your wallet."
                    )
                case TransferError.NO_RECIPIENT_ACCOUNT:
                    name = recipient_member.display_name
                    msg = f"**{name}** doesn't have a currency account."
                case _:
                    msg = "Transfer failed."
            await interaction.response.send_message(msg, ephemeral=True)
            return

        # Format balances for display
        sender_balance_str = f"\u00a5{result.sender_balance:,}"
        amount_str = f"\u00a5{amount:,}"

        # Respond with confirmation
        await interaction.response.send_message(
            f"You paid {amount_str} to **{recipient_member.display_name}**.\n"
            f"Your balance: {sender_balance_str}",
            ephemeral=True,
        )

        # Flush observers after response (wallet thread updates happen here)
        await scene.flush_observers()
