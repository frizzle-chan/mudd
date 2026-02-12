"""Betting cog — /bet slash command for horse race wagering."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import asyncpg
import discord
from discord import Interaction, app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from mudd.bot import MuddBot

from mudd.events import BalanceChangedEvent
from mudd.models.bet import MIN_BET, Bet, BetError, BetResult
from mudd.models.race import ActiveRace, RaceHorseInfo
from mudd.observers import RoomChannelCache, build_observers, flush_all
from mudd.racing.betting import format_payout_message
from mudd.racing.config import RACE_TRACK_ROOM
from mudd.racing.persistence import get_race_thread_id, get_race_winner
from mudd.utils.discord import fetch_thread

logger = logging.getLogger(__name__)


class Betting(commands.Cog):
    """Horse race betting commands."""

    bot: MuddBot

    def __init__(
        self,
        bot: MuddBot,
        pool: asyncpg.Pool,
        room_cache: RoomChannelCache,
    ) -> None:
        self.bot = bot
        self._pool = pool
        self._room_cache = room_cache

    async def horse_autocomplete(
        self, interaction: Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete callback for horse selection."""
        race = await ActiveRace.get(self._pool)
        if race is None or not race.is_announcing():
            return [
                app_commands.Choice(
                    name="No race accepting bets right now", value="invalid"
                )
            ]

        horses = await RaceHorseInfo.get_for_race(self._pool, race.id)
        if not horses:
            return [app_commands.Choice(name="No horses found", value="invalid")]

        current_lower = current.lower()
        filtered = (
            [h for h in horses if current_lower in h.name.lower()]
            if current
            else horses
        )

        return [
            app_commands.Choice(
                name=f"{h.name} ({h.displayed_payout:.1f}:1)",
                value=h.id,
            )
            for h in filtered[:25]
        ]

    @app_commands.command(
        name="bet",
        description="Bet on a horse in the current race",
    )
    @app_commands.describe(
        horse="Horse to bet on",
        amount="Amount to bet in yen (0 to cancel)",
    )
    @app_commands.autocomplete(horse=horse_autocomplete)
    async def bet(
        self,
        interaction: Interaction,
        horse: str,
        amount: int,
    ) -> None:
        """Place a bet on a horse race."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command must be used in a server.", ephemeral=True
            )
            return

        # Verify channel is race-track (or a thread within it)
        channel_id = interaction.channel_id
        if channel_id is None:
            await interaction.response.send_message(
                "You can only place bets at the race track!", ephemeral=True
            )
            return
        room_id = self._room_cache.get_room_for_channel(channel_id)
        if room_id != RACE_TRACK_ROOM:
            # Check if this is a thread whose parent is the race-track
            channel = interaction.channel
            parent_id = getattr(channel, "parent_id", None)
            if parent_id is None or (
                self._room_cache.get_room_for_channel(parent_id) != RACE_TRACK_ROOM
            ):
                await interaction.response.send_message(
                    "You can only place bets at the race track!",
                    ephemeral=True,
                )
                return

        # Handle invalid autocomplete selection
        if horse == "invalid":
            await interaction.response.send_message(
                "No valid horse selected.", ephemeral=True
            )
            return

        # Get active race
        race = await ActiveRace.get(self._pool)
        if race is None:
            await interaction.response.send_message(
                "There's no active race right now.", ephemeral=True
            )
            return

        user_id = interaction.user.id

        # Cancel bet if amount is 0
        if amount == 0:
            if not race.is_announcing():
                await interaction.response.send_message(
                    "Betting is closed — the race has started!",
                    ephemeral=True,
                )
                return

            result = await Bet.cancel(self._pool, race.id, user_id, horse)

            if not result.success:
                msg = _error_message(result.error)
                await interaction.response.send_message(msg, ephemeral=True)
                return

            await interaction.response.send_message(
                f"Cancelled your bet on **{result.horse_name}**. "
                f"\u00a5{result.amount:,} refunded.\n"
                f"Balance: \u00a5{result.new_balance:,}",
                ephemeral=True,
            )

            # Post cancellation to thread (best-effort)
            await self._post_to_race_thread(
                interaction.guild,
                race.id,
                f"**{interaction.user.display_name}** cancelled their bet on "
                f"**{result.horse_name}**",
            )

            # Update wallet thread (best-effort, after response)
            await self._notify_wallet(interaction.guild_id, result)
            return

        # Validate amount
        if amount < 0:
            await interaction.response.send_message(
                "Amount must be 0 (to cancel) or positive.", ephemeral=True
            )
            return

        # Look up horse info for displayed_payout
        horses = await RaceHorseInfo.get_for_race(self._pool, race.id)
        horse_info = next((h for h in horses if h.id == horse), None)
        if horse_info is None:
            await interaction.response.send_message(
                "That horse isn't in this race.", ephemeral=True
            )
            return

        result = await Bet.place(
            self._pool,
            race.id,
            user_id,
            horse,
            amount,
            horse_info.displayed_payout,
        )

        if not result.success:
            msg = _error_message(result.error)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        await interaction.response.send_message(
            f"Bet \u00a5{result.amount:,} on **{result.horse_name}** "
            f"({result.displayed_payout:.1f}:1)\n"
            f"Balance: \u00a5{result.new_balance:,}",
            ephemeral=True,
        )

        # Post bet to thread (best-effort)
        await self._post_to_race_thread(
            interaction.guild,
            race.id,
            f"**{interaction.user.display_name}** bet "
            f"\u00a5{result.amount:,} on **{result.horse_name}**",
        )

        # Update wallet thread (best-effort, after response)
        await self._notify_wallet(interaction.guild_id, result)

    async def resolve_and_post_payouts(self, race_id: int) -> None:
        """Resolve betting payouts and post results to the race thread.

        Called by the Racing cog when a race finishes.
        """
        try:
            bet_count = await Bet.count(self._pool, race_id)
            if bet_count == 0:
                return

            winner_horse_id = await get_race_winner(self._pool, race_id)
            if winner_horse_id is None:
                return

            odds = await RaceHorseInfo.get_for_race(self._pool, race_id)

            payouts, balance_events = await Bet.resolve_payouts(
                self._pool, race_id, winner_horse_id, odds
            )
            if not payouts:
                return

            message = format_payout_message(payouts)
            if not message:
                return

            # Post to thread
            guild = self.bot.get_guild(self.bot.guild_id)
            if guild is None:
                return
            thread_id = await get_race_thread_id(self._pool, race_id)
            if thread_id is None:
                return
            thread = await fetch_thread(guild, thread_id)
            if thread is None:
                return
            await thread.send(message)
            logger.info("Posted payout results for race #%d", race_id)

            # Update wallet threads for all balance changes
            await self._notify_wallet_events(balance_events)
        except Exception:
            logger.exception("Failed to resolve payouts for race #%d", race_id)

    async def _notify_wallet(
        self,
        guild_id: int | None,
        result: BetResult,
    ) -> None:
        """Notify the wallet inventory thread of a balance change (best-effort)."""
        if result.balance_event is None or guild_id is None:
            return
        await self._notify_wallet_events([result.balance_event])

    async def _notify_wallet_events(
        self,
        events: list[BalanceChangedEvent],
    ) -> None:
        """Deliver balance change events through the standard observer pipeline."""
        if not events:
            return
        try:
            observers = build_observers(
                self._pool,
                user_id=0,
                room_id="",
                bot=self.bot,
                guild_id=self.bot.guild_id,
                room_cache=self._room_cache,
            )
            for evt in events:
                for obs in observers:
                    obs.notify(evt)
            await flush_all(observers)
        except Exception:
            logger.exception("Failed to update wallet thread for betting events")

    async def _post_to_race_thread(
        self,
        guild: discord.Guild,
        race_id: int,
        message: str,
    ) -> None:
        """Post a message to the race thread (best-effort)."""
        try:
            thread_id = await get_race_thread_id(self._pool, race_id)
            if thread_id is None:
                return
            thread = await fetch_thread(guild, thread_id)
            if thread is None:
                return
            await thread.send(message)
        except Exception:
            logger.exception("Failed to post bet message to race #%d thread", race_id)


def _error_message(error: BetError | None) -> str:
    """Map a BetError to a user-facing message."""
    match error:
        case BetError.RACE_NOT_ACCEPTING_BETS:
            return "Betting is closed, the race has started!"
        case BetError.HORSE_NOT_IN_RACE:
            return "That horse isn't in this race."
        case BetError.INSUFFICIENT_FUNDS:
            return "You don't have enough yen."
        case BetError.AMOUNT_TOO_LOW:
            return f"Minimum bet is \u00a5{MIN_BET:,}."
        case BetError.NO_BET_TO_CANCEL:
            return "You don't have a bet on that horse to cancel."
        case BetError.NO_CURRENCY_ACCOUNT:
            return "You don't have a currency account. Try looking at your wallet."
        case None:
            return "Something went wrong."
