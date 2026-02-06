"""Zone and room reconciler for Discord state."""

from __future__ import annotations

import logging

import asyncpg
import discord

from mudd.events import (
    GameEvent,
    OrphanChannelDetectedEvent,
    RoomSyncedEvent,
    ZoneSyncedEvent,
)

logger = logging.getLogger(__name__)


class ZoneRoomReconciler:
    """Reconciles zone categories, room channels, and orphan detection.

    Handles:
    - ZoneSyncedEvent: Creates Discord categories idempotently
    - RoomSyncedEvent: Creates Discord text/voice channels idempotently
    - OrphanChannelDetectedEvent: Reports new orphan channels to console
    """

    def __init__(
        self,
        bot: discord.Client,
        pool: asyncpg.Pool,
        console_channel: str = "console",
        seen_orphans: set[tuple[int, str, str]] | None = None,
    ) -> None:
        self.bot = bot
        self.pool = pool
        self._console_channel = console_channel
        self._zone_events: list[ZoneSyncedEvent] = []
        self._room_events: list[RoomSyncedEvent] = []
        self._orphan_events: list[OrphanChannelDetectedEvent] = []
        # Track zone categories per guild: guild_id -> {zone_id -> category}
        self._zone_categories: dict[int, dict[str, discord.CategoryChannel]] = {}
        # Track seen orphans: (guild_id, channel_name, category_name)
        self._seen_orphans: set[tuple[int, str, str]] = (
            seen_orphans if seen_orphans is not None else set()
        )

    def notify(self, event: GameEvent) -> None:
        """Queue zone/room/orphan events for async processing."""
        match event:
            case ZoneSyncedEvent() as evt:
                self._zone_events.append(evt)
            case RoomSyncedEvent() as evt:
                self._room_events.append(evt)
            case OrphanChannelDetectedEvent() as evt:
                self._orphan_events.append(evt)

    async def flush(self) -> None:
        """Process queued zone, room, and orphan events."""
        zone_events = self._zone_events
        self._zone_events = []
        room_events = self._room_events
        self._room_events = []
        orphan_events = self._orphan_events
        self._orphan_events = []

        if not self.bot.guilds:
            return

        for guild in self.bot.guilds:
            for evt in zone_events:
                await self._ensure_zone_category(guild, evt)

            for evt in room_events:
                await self._ensure_room_channel(guild, evt)

            for evt in orphan_events:
                if evt.guild_id == guild.id:
                    await self._report_orphan(guild, evt)

    async def _ensure_zone_category(
        self, guild: discord.Guild, event: ZoneSyncedEvent
    ) -> discord.CategoryChannel | None:
        """Idempotent: create category for zone if missing."""
        if guild.id not in self._zone_categories:
            self._zone_categories[guild.id] = {}

        if event.zone_id in self._zone_categories[guild.id]:
            return self._zone_categories[guild.id][event.zone_id]

        normalized_name = event.name.lower().replace(" ", "-")

        for category in guild.categories:
            category_normalized = category.name.lower().replace(" ", "-")
            if category_normalized == normalized_name:
                self._zone_categories[guild.id][event.zone_id] = category
                return category

        try:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False)
            }
            category = await guild.create_category(event.name, overwrites=overwrites)
            self._zone_categories[guild.id][event.zone_id] = category
            logger.info(f"Created category '{event.name}' for zone {event.zone_id}")
            return category
        except discord.HTTPException as e:
            logger.error(f"Failed to create category for zone {event.zone_id}: {e}")
            return None

    async def _ensure_room_channel(
        self, guild: discord.Guild, event: RoomSyncedEvent
    ) -> None:
        """Idempotent: create text/voice channels for room if missing."""
        if guild.id not in self._zone_categories:
            self._zone_categories[guild.id] = {}

        category = self._zone_categories[guild.id].get(event.zone_id)
        if category is None:
            logger.warning(
                f"No category for zone {event.zone_id}, skipping room {event.room_id}"
            )
            return

        existing_text = discord.utils.get(guild.text_channels, name=event.room_id)

        if existing_text is None:
            try:
                await category.create_text_channel(
                    event.room_id, topic=event.description
                )
                logger.info(
                    f"Created text channel '{event.room_id}' in {category.name}"
                )
            except discord.HTTPException as e:
                logger.error(f"Failed to create text channel {event.room_id}: {e}")
        else:
            needs_update = (
                existing_text.topic != event.description
                or existing_text.category_id != category.id
            )
            if needs_update:
                try:
                    await existing_text.edit(topic=event.description, category=category)
                    logger.debug(f"Updated text channel '{event.room_id}'")
                except discord.HTTPException as e:
                    logger.error(f"Failed to update text channel {event.room_id}: {e}")

        if event.has_voice:
            existing_voice = discord.utils.get(guild.voice_channels, name=event.room_id)
            if existing_voice is None:
                try:
                    await category.create_voice_channel(event.room_id)
                    logger.info(
                        f"Created voice channel '{event.room_id}' in {category.name}"
                    )
                except discord.HTTPException as e:
                    logger.error(f"Failed to create voice channel {event.room_id}: {e}")
            elif existing_voice.category_id != category.id:
                try:
                    await existing_voice.edit(category=category)
                    logger.debug(
                        f"Moved voice channel '{event.room_id}' to {category.name}"
                    )
                except discord.HTTPException as e:
                    logger.error(f"Failed to move voice channel {event.room_id}: {e}")

    async def _report_orphan(
        self, guild: discord.Guild, event: OrphanChannelDetectedEvent
    ) -> None:
        """Report orphan channel to console if not already seen."""
        key = (event.guild_id, event.channel_name, event.category_name)
        if key in self._seen_orphans:
            return

        self._seen_orphans.add(key)

        console = discord.utils.get(guild.text_channels, name=self._console_channel)
        if console is None:
            logger.warning(
                f"Console channel #{self._console_channel} not found, "
                f"cannot report orphan #{event.channel_name}"
            )
            return

        try:
            await console.send(
                f"**Orphan channel detected**: #{event.channel_name} "
                f"in {event.category_name}\n"
                "Consider deleting this channel or adding it to the world file."
            )
            logger.info(f"Reported orphan channel #{event.channel_name} to console")
        except discord.HTTPException as e:
            logger.error(f"Failed to report orphan to console: {e}")
