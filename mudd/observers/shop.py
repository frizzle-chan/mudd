"""Shop reconciler for trading thread lifecycle."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import asyncpg
import discord

from mudd.events.types import (
    GameEvent,
    TradingSessionEndedEvent,
    TradingSessionStartedEvent,
)
from mudd.models.dialog import DialogSession
from mudd.models.shop import Shop, TradingSession, group_stock, purchase_price
from mudd.models.skills import UserSkill
from mudd.utils.discord import fetch_thread

if TYPE_CHECKING:
    from mudd.models.shop import StockItem
    from mudd.observers.discord import RoomChannelCache

logger = logging.getLogger(__name__)


def format_shop_overview(shop: Shop, stock: list[StockItem], speech_level: int) -> str:
    """Format the shop stock listing for a trading thread.

    Groups duplicate items by entity_id, shows rarity emoji
    and purchase_price adjusted for Speech level.

    Args:
        shop: The shop being browsed
        stock: Stock items in the shop
        speech_level: Player's Speech skill level

    Returns:
        Formatted markdown string for the shop overview
    """
    lines: list[str] = []
    lines.append(f"# {shop.name}")

    if shop.preferred_tag:
        lines.append(f"*Specializes in **{shop.preferred_tag}** items*")

    lines.append("")

    if not stock:
        lines.append("The shelves are empty.")
        lines.append("")
        lines.append("Use `/sell` to sell items.")
        return "\n".join(lines)

    lines.append("**For Sale:**")
    for item, count in group_stock(stock):
        price = purchase_price(item.rarity, count, speech_level)
        price_str = f"\u00a4{price:,}"

        emoji = item.rarity.emoji
        display = f"{item.name} {emoji}" if emoji else item.name
        line = f"- {count} **{display}** | {price_str}/ea"
        lines.append(line)

    lines.append("")
    lines.append("Use `/buy` to purchase or `/sell` to sell items.")
    return "\n".join(lines)


async def refresh_shop_overview(
    guild: discord.Guild,
    pool: asyncpg.Pool,
    session: TradingSession,
    speech_level: int,
) -> None:
    """Edit the shop overview message in-place to reflect current stock.

    Best-effort: logs warnings on failure rather than raising.

    Args:
        guild: Discord guild
        pool: Database connection pool
        session: Active trading session
        speech_level: Player's Speech skill level for price display
    """
    shop = await Shop.get(pool, session.shop_id)
    if shop is None:
        logger.warning("refresh_shop_overview: shop %s not found", session.shop_id)
        return

    stock = await Shop.get_stock(pool, session.shop_id)
    overview = format_shop_overview(shop, stock, speech_level)

    thread = await fetch_thread(guild, session.thread_id)
    if thread is None:
        logger.warning("refresh_shop_overview: thread %d not found", session.thread_id)
        return

    try:
        msg = await thread.fetch_message(session.overview_message_id)
        await msg.edit(content=overview)
    except discord.HTTPException as e:
        logger.warning(
            "refresh_shop_overview: failed to edit message %d: %s",
            session.overview_message_id,
            e,
        )


class ShopReconciler:
    """Reconciles Discord state for trading sessions.

    Handles:
    - TradingSessionStartedEvent: Ends any existing session (deletes
      old thread + DB row), creates new broadcast + thread + DB session
    - TradingSessionEndedEvent: Deletes thread

    Sub-reconciler of DiscordReconciler.
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
        self._room_cache = room_cache
        self._started_events: list[TradingSessionStartedEvent] = []
        self._ended_events: list[TradingSessionEndedEvent] = []

    def notify(self, event: GameEvent) -> None:
        """Queue trading session events for processing."""
        match event:
            case TradingSessionStartedEvent() as evt:
                self._started_events.append(evt)
            case TradingSessionEndedEvent() as evt:
                self._ended_events.append(evt)

    async def flush(self) -> None:
        """Process queued events. Swap-and-clear for re-entrancy safety."""
        started = self._started_events
        self._started_events = []
        ended = self._ended_events
        self._ended_events = []

        guild = self._bot.get_guild(self._guild_id)
        if guild is None:
            return

        # Process ended events first (delete threads)
        for evt in ended:
            await self._delete_thread(guild, evt.thread_id)

        # Process started events
        for evt in started:
            try:
                await self._handle_session_started(guild, evt)
            except Exception:
                logger.exception(
                    "Failed to handle trading session start for user %d shop %s",
                    evt.user_id,
                    evt.shop_id,
                )

    async def _delete_thread(self, guild: discord.Guild, thread_id: int) -> None:
        """Best-effort delete a trading thread."""
        thread = await fetch_thread(guild, thread_id)
        if thread is None:
            return
        try:
            await thread.delete()
            logger.info("Deleted trading thread %d", thread_id)
        except discord.HTTPException as e:
            logger.warning("Failed to delete trading thread %d: %s", thread_id, e)

    async def _handle_session_started(
        self, guild: discord.Guild, evt: TradingSessionStartedEvent
    ) -> None:
        """Handle a new trading session: clean up old threads, create new one."""
        # 1. Delete any existing trading/dialog sessions (independent)
        old_session, old_dialog = await asyncio.gather(
            TradingSession.delete(self._pool, evt.user_id),
            DialogSession.delete(self._pool, evt.user_id),
        )
        if old_session is not None:
            await self._delete_thread(guild, old_session.thread_id)
        if old_dialog is not None:
            await self._delete_thread(guild, old_dialog.thread_id)

        # 3. Look up room channel
        if self._room_cache is None:
            logger.warning("No room_cache available for shop reconciler")
            return

        channel_id = self._room_cache.get_channel_for_room(evt.room_id)
        if channel_id is None:
            logger.warning(
                "No channel found for room %s during shop session start",
                evt.room_id,
            )
            return

        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            logger.warning(
                "Channel %d for room %s is not a text channel",
                channel_id,
                evt.room_id,
            )
            return

        # 4. Fetch shop + stock + user's Speech level
        shop = await Shop.get(self._pool, evt.shop_id)
        if shop is None:
            logger.warning("Shop %s not found", evt.shop_id)
            return

        stock = await Shop.get_stock(self._pool, evt.shop_id)

        user_skill = await UserSkill.get(self._pool, evt.user_id, "speech")
        speech_level = user_skill.level if user_skill else 1

        # 5. Resolve display name
        member = guild.get_member(evt.user_id)
        display_name = member.display_name if member else str(evt.user_id)

        # 6. Send broadcast message to room channel
        await channel.send(f"**{display_name}** begins trading at **{shop.name}**.")

        # 7. Create private thread (only the trading player can see it)
        thread = await channel.create_thread(
            name=shop.name,
            type=discord.ChannelType.private_thread,
            invitable=False,
        )

        # 8. Post shop overview in thread, @mentioning the user
        overview = format_shop_overview(shop, stock, speech_level)
        mention = member.mention if member else f"<@{evt.user_id}>"
        overview_msg = await thread.send(f"{mention}\n{overview}")

        # 9. Create DB session with the new thread_id and overview message ID
        await TradingSession.create(
            self._pool, evt.user_id, evt.shop_id, thread.id, overview_msg.id
        )
        logger.info(
            "Created trading session for user %d at shop %s (thread %d)",
            evt.user_id,
            evt.shop_id,
            thread.id,
        )
