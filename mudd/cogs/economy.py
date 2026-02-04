"""Economy commands for MUDD."""

import logging

import asyncpg
import discord
from discord import Interaction, app_commands
from discord.ext import commands

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
        """Autocomplete for pay recipients - only shows users in the same room."""
        if not interaction.guild:
            return []

        user = interaction.user
        if not isinstance(user, discord.Member):
            return []

        # Build scene to get other players
        try:
            scene = await Scene.from_interaction(self._pool, interaction)
        except ValueError:
            return [app_commands.Choice(name="You're not in a room", value="invalid")]

        other_players = await scene.other_players()
        if not other_players:
            return [app_commands.Choice(name="There's nobody to pay", value="invalid")]

        # Get guild members for those IDs, filtering out bots
        valid_recipients: list[discord.Member] = []
        for player in other_players:
            # Try cache first, then fetch from API
            member = interaction.guild.get_member(player.id)
            if member is None:
                try:
                    member = await interaction.guild.fetch_member(player.id)
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

        # Execute transfer with observers attached
        sender_user = scene.user.with_observers(*scene._observers)
        memo = f"Payment to {recipient_member.display_name}"
        result = await sender_user.transfer_currency_to(recipient_user, amount, memo)

        if result is None:
            # Check specific failure reason
            sender_balance = await sender_user.get_balance()
            if sender_balance == 0:
                await interaction.response.send_message(
                    "You don't have a currency account. Try looking at your wallet.",
                    ephemeral=True,
                )
            elif sender_balance < amount:
                await interaction.response.send_message(
                    "You don't have enough yen.", ephemeral=True
                )
            else:
                # Recipient likely doesn't have account
                name = recipient_member.display_name
                await interaction.response.send_message(
                    f"**{name}** doesn't have a currency account.",
                    ephemeral=True,
                )
            return

        sender_new, _recipient_new = result

        # Format balances for display
        sender_balance_str = f"\u00a5{sender_new:,}"
        amount_str = f"\u00a5{amount:,}"

        # Respond with confirmation
        await interaction.response.send_message(
            f"You paid {amount_str} to **{recipient_member.display_name}**.\n"
            f"Your balance: {sender_balance_str}",
            ephemeral=True,
        )

        # Flush observers after response (wallet thread updates happen here)
        await scene.flush_observers()
