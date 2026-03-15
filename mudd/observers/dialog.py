"""Dialog reconciler for NPC dialog thread lifecycle."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

import asyncpg
import discord

from mudd.events.types import (
    DialogSessionEndedEvent,
    DialogStartedEvent,
    GameEvent,
)
from mudd.loaders.dialog_loader import DialogOption, get_dialog
from mudd.models.dialog import DialogSession
from mudd.models.shop import TradingSession
from mudd.utils.discord import fetch_thread

if TYPE_CHECKING:
    from mudd.observers.discord import RoomChannelCache

logger = logging.getLogger(__name__)


class DialogView(discord.ui.View):
    """Button view for dialog choices.

    Each button's custom_id encodes the dialog ID and target node,
    allowing stateless navigation: ``dialog:{dialog_id}:{node_id}``.
    """

    def __init__(self, dialog_id: str, options: Sequence[DialogOption]) -> None:
        super().__init__(timeout=None)  # Persistent view
        for option in options:
            # Condition evaluation not yet implemented — all options
            # shown as enabled. When added, options with hidden=False
            # should show a disabled button with hint text.
            button = discord.ui.Button(
                label=option.label,
                custom_id=f"dialog:{dialog_id}:{option.next}",
                style=discord.ButtonStyle.primary,
            )
            self.add_item(button)


class DialogReconciler:
    """Reconciles Discord state for dialog sessions.

    Handles:
    - DialogStartedEvent: Ends any existing session, creates thread, posts root node
    - DialogSessionEndedEvent: Deletes thread

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
        self._started_events: list[DialogStartedEvent] = []
        self._ended_events: list[DialogSessionEndedEvent] = []

    def notify(self, event: GameEvent) -> None:
        """Queue dialog session events for processing."""
        match event:
            case DialogStartedEvent() as evt:
                self._started_events.append(evt)
            case DialogSessionEndedEvent() as evt:
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
                    "Failed to handle dialog session start for user %d dialog %s",
                    evt.user_id,
                    evt.dialog_id,
                )

    async def _delete_thread(self, guild: discord.Guild, thread_id: int) -> None:
        """Best-effort delete a dialog thread."""
        thread = await fetch_thread(guild, thread_id)
        if thread is None:
            return
        try:
            await thread.delete()
            logger.info("Deleted dialog thread %d", thread_id)
        except discord.HTTPException as e:
            logger.warning("Failed to delete dialog thread %d: %s", thread_id, e)

    async def _handle_session_started(
        self, guild: discord.Guild, evt: DialogStartedEvent
    ) -> None:
        """Handle a new dialog session: clean up old threads, create new one."""
        # 1. Delete any existing dialog/trading sessions (independent)
        old_dialog, old_trade = await asyncio.gather(
            DialogSession.delete(self._pool, evt.user_id),
            TradingSession.delete(self._pool, evt.user_id),
        )
        if old_dialog is not None:
            await self._delete_thread(guild, old_dialog.thread_id)
        if old_trade is not None:
            await self._delete_thread(guild, old_trade.thread_id)

        # 3. Look up room channel
        if self._room_cache is None:
            logger.warning("No room_cache available for dialog reconciler")
            return

        channel_id = self._room_cache.get_channel_for_room(evt.room_id)
        if channel_id is None:
            logger.warning(
                "No channel found for room %s during dialog session start",
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

        # 4. Load dialog tree
        tree = get_dialog(evt.dialog_id)
        if tree is None:
            logger.warning("Dialog tree %s not found", evt.dialog_id)
            return

        root_id = evt.root or tree.root
        root_node = tree.nodes.get(root_id)
        if root_node is None:
            logger.warning(
                "Root node %s not found in dialog %s", root_id, evt.dialog_id
            )
            return

        # 5. Resolve display name
        member = guild.get_member(evt.user_id)
        mention = member.mention if member else f"<@{evt.user_id}>"

        # 6. Create private thread (only the dialog player can see it)
        thread = await channel.create_thread(
            name=f"Dialog: {evt.dialog_id}",
            type=discord.ChannelType.private_thread,
            invitable=False,
        )

        # 7. Build dialog view with buttons for root node options
        view = DialogView(evt.dialog_id, root_node.options)

        # 8. Post root node text with view to thread, mentioning the user.
        # Node text is sent as-is — Jinja2 rendering with effects context
        # will be added when condition evaluation is implemented.
        await thread.send(f"{mention}\n{root_node.text}", view=view)

        # 9. Create DB session
        await DialogSession.create(self._pool, evt.user_id, evt.dialog_id, thread.id)
        logger.info(
            "Created dialog session for user %d with dialog %s (thread %d)",
            evt.user_id,
            evt.dialog_id,
            thread.id,
        )
