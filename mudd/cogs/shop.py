"""Shop cog — /buy slash command for purchasing items from merchants."""

from __future__ import annotations

import logging
from collections import Counter
from typing import TYPE_CHECKING
from uuid import UUID

import asyncpg
from discord import Interaction, app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from mudd.bot import MuddBot

from mudd.events import BalanceChangedEvent
from mudd.events.types import GrantXPSignal
from mudd.models.currency import (
    HOUSE_ACCOUNT_ID,
    AccountMissing,
    InsufficientFunds,
    transfer_currency,
)
from mudd.models.entity import EntityInstance
from mudd.models.shop import Shop as ShopModel
from mudd.models.shop import StockItem, TradingSession, purchase_price
from mudd.models.skills import UserSkill
from mudd.models.user import User
from mudd.observers import (
    RoomChannelCache,
    build_observers,
    flush_all,
    post_flush_all,
)
from mudd.skills.registry import Skill
from mudd.utils.discord import fetch_thread
from mudd.utils.text import RARITY_EMOJI

logger = logging.getLogger(__name__)

# XP granted per trade, matches SPEECH_XP_PER_MESSAGE in speech.py
SPEECH_XP_PER_TRADE = 15


def format_buy_choices(
    stock: list[StockItem], speech_level: int
) -> list[tuple[str, str]]:
    """Group stock items and format as autocomplete choices.

    Returns a list of (display_label, entity_instance_id_str) tuples,
    one per unique entity_id, ordered by first occurrence.

    Args:
        stock: Stock items from the shop
        speech_level: Player's Speech skill level for price calculation

    Returns:
        List of (label, value) tuples for autocomplete choices
    """
    counts: Counter[str] = Counter()
    first_seen: dict[str, StockItem] = {}
    for item in stock:
        counts[item.entity_id] += 1
        if item.entity_id not in first_seen:
            first_seen[item.entity_id] = item

    choices: list[tuple[str, str]] = []
    for entity_id, item in first_seen.items():
        count = counts[entity_id]
        emoji = RARITY_EMOJI.get(item.rarity, "")
        price = purchase_price(item.rarity, count, speech_level)
        qty = f" x{count}" if count > 1 else ""
        label = f"{item.name}{emoji}{qty} - \u00a4{price:,}"
        choices.append((label, str(item.entity_instance_id)))
    return choices


class Shop(commands.Cog):
    """Shop commands for buying items from merchants."""

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

    async def buy_autocomplete(
        self, interaction: Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete callback for item selection."""
        user_id = interaction.user.id

        session = await TradingSession.get(self._pool, user_id)
        if session is None:
            return []

        stock = await ShopModel.get_stock(self._pool, session.shop_id)
        if not stock:
            return [app_commands.Choice(name="Nothing for sale", value="invalid")]

        user_skill = await UserSkill.get(self._pool, user_id, "speech")
        speech_level = user_skill.level if user_skill else 1

        choices = format_buy_choices(stock, speech_level)

        current_lower = current.lower()
        if current:
            choices = [
                (label, value)
                for label, value in choices
                if current_lower in label.lower()
            ]

        return [
            app_commands.Choice(name=label, value=value)
            for label, value in choices[:25]
        ]

    @app_commands.command(
        name="buy",
        description="Buy an item from the current shop",
    )
    @app_commands.describe(item="Item to purchase")
    @app_commands.autocomplete(item=buy_autocomplete)
    async def buy(self, interaction: Interaction, item: str) -> None:
        """Purchase an item from a shop."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command must be used in a server.", ephemeral=True
            )
            return

        # Handle invalid sentinel from autocomplete
        if item == "invalid":
            await interaction.response.send_message(
                "No valid item selected.", ephemeral=True
            )
            return

        user_id = interaction.user.id

        # Validate active trading session
        session = await TradingSession.get(self._pool, user_id)
        if session is None:
            await interaction.response.send_message(
                "You're not trading with a merchant. "
                "Use `/interact` on a merchant to start.",
                ephemeral=True,
            )
            return

        # Parse UUID from autocomplete value
        try:
            instance_id = UUID(item)
        except ValueError:
            await interaction.response.send_message(
                "Invalid item selection.", ephemeral=True
            )
            return

        # Validate item is in stock
        stock = await ShopModel.get_stock(self._pool, session.shop_id)
        stock_item = next(
            (s for s in stock if s.entity_instance_id == instance_id), None
        )
        if stock_item is None:
            await interaction.response.send_message(
                "That item is no longer in stock.", ephemeral=True
            )
            return

        # Get shop for name in memo
        shop = await ShopModel.get(self._pool, session.shop_id)
        if shop is None:
            await interaction.response.send_message("Shop not found.", ephemeral=True)
            return

        # Calculate price
        entity_id_counts = sum(1 for s in stock if s.entity_id == stock_item.entity_id)
        user_skill = await UserSkill.get(self._pool, user_id, "speech")
        speech_level = user_skill.level if user_skill else 1
        price = purchase_price(stock_item.rarity, entity_id_counts, speech_level)

        if price == 0:
            await interaction.response.send_message(
                "That item is not for sale.", ephemeral=True
            )
            return

        # Transfer currency: player -> house
        memo = f"Buy {stock_item.name} from {shop.name}"
        try:
            async with self._pool.acquire() as conn, conn.transaction():
                outcome = await transfer_currency(
                    conn,
                    from_id=user_id,
                    to_id=HOUSE_ACCOUNT_ID,
                    amount=price,
                    memo=memo,
                )
        except InsufficientFunds as e:
            await interaction.response.send_message(
                f"You can't afford that! "
                f"Cost: \u00a4{price:,}, balance: \u00a4{e.balance:,}.",
                ephemeral=True,
            )
            return
        except AccountMissing:
            await interaction.response.send_message(
                "You don't have a currency account yet.", ephemeral=True
            )
            return

        new_balance = outcome.from_balance

        # Remove from shop stock
        await ShopModel.remove_from_stock(self._pool, instance_id)

        # Get user for move_to_inventory
        user = await User.get(self._pool, user_id)
        if user is None:
            await interaction.response.send_message("User not found.", ephemeral=True)
            return

        # Build observers for inventory sync, XP, wallet update
        observers = build_observers(
            self._pool,
            user_id=user_id,
            room_id=user.current_room,
            bot=self.bot,
            guild_id=interaction.guild_id,
            room_cache=self._room_cache,
        )

        # Move item to player inventory (emits EntityPickedUpEvent)
        entity = await EntityInstance.get(self._pool, instance_id)
        if entity is not None:
            entity = entity.with_observers(*observers)
            await entity.move_to_inventory(user)

        # Grant speech XP
        for obs in observers:
            obs.notify(GrantXPSignal(skill=Skill.SPEECH, amount=SPEECH_XP_PER_TRADE))

        # Notify balance change
        for obs in observers:
            obs.notify(
                BalanceChangedEvent(
                    user_id=user_id,
                    new_balance=new_balance,
                    delta=-price,
                    memo=memo,
                )
            )

        # Send ephemeral confirmation
        emoji = RARITY_EMOJI.get(stock_item.rarity, "")
        name_display = f"{stock_item.name} {emoji}" if emoji else stock_item.name
        await interaction.response.send_message(
            f"Purchased **{name_display}** for \u00a4{price:,}.\n"
            f"Balance: \u00a4{new_balance:,}",
            ephemeral=True,
        )

        # Post to trading thread (best-effort)
        try:
            thread = await fetch_thread(interaction.guild, session.thread_id)
            if thread is not None:
                await thread.send(
                    f"**{interaction.user.display_name}** purchased "
                    f"**{name_display}** for \u00a4{price:,}."
                )
        except Exception:
            logger.exception(
                "Failed to post purchase message to trading thread %d",
                session.thread_id,
            )

        # Flush observers (inventory sync, wallet update, XP grant, level-up)
        await flush_all(observers)
        await post_flush_all(observers)
