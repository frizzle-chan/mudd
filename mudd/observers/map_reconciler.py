"""Map reconciler for Discord state.

Updates the map thread (room description text + map image) when a user moves.
"""

from __future__ import annotations

import logging
from io import BytesIO

import asyncpg
import discord

from mudd.events.types import GameEvent, UserMovedEvent
from mudd.map.rendering import generate_map_image
from mudd.models.entity import EntityInstance
from mudd.models.room import Room
from mudd.models.user import User
from mudd.utils.discord import fetch_thread

logger = logging.getLogger(__name__)


class MapReconciler:
    """Reconciles map thread content when a user moves rooms.

    Handles:
    - UserMovedEvent: Updates map thread description text and image
    """

    def __init__(
        self,
        bot: discord.Client,
        pool: asyncpg.Pool,
        guild_id: int,
    ) -> None:
        self.bot = bot
        self.pool = pool
        self._guild_id = guild_id
        self._move_events: list[UserMovedEvent] = []

    def notify(self, event: GameEvent) -> None:
        """Queue movement events for async processing."""
        match event:
            case UserMovedEvent() as evt:
                self._move_events.append(evt)

    async def flush(self) -> None:
        """Process queued movement events."""
        move_events = self._move_events
        self._move_events = []

        guild = self.bot.get_guild(self._guild_id)
        if guild is None:
            return

        # Deduplicate by user_id, keep last event (most recent destination)
        latest_by_user: dict[int, UserMovedEvent] = {}
        for evt in move_events:
            latest_by_user[evt.user_id] = evt

        for evt in latest_by_user.values():
            await self._handle_move(guild, evt)

    async def _handle_move(self, guild: discord.Guild, event: UserMovedEvent) -> None:
        """Update a user's map thread after movement."""
        user = await User.get(self.pool, event.user_id)
        if user is None:
            return

        map_instance = await user.get_map()
        if map_instance is None:
            return

        # Record room visit
        is_new_visit = await User.record_room_visit(
            self.pool, event.user_id, event.to_room
        )

        # Get the map thread's description message
        description_msg_id = await EntityInstance.get_description_msg_id(
            self.pool, map_instance.instance_id
        )
        thread_id = await EntityInstance.get_thread_id(
            self.pool, map_instance.instance_id
        )
        if thread_id is None:
            return

        thread = await fetch_thread(guild, thread_id)
        if thread is None:
            return

        # Update description text to new room description
        room = await Room.get(self.pool, event.to_room)
        if room and description_msg_id:
            try:
                msg = await thread.fetch_message(description_msg_id)
                room_content = f"## {room.name}\n{room.description}"
                if msg.content != room_content:
                    await msg.edit(content=room_content)
            except discord.NotFound:
                logger.warning(
                    f"Map description message {description_msg_id} not found "
                    f"for user {event.user_id}"
                )
            except discord.HTTPException as e:
                logger.error(
                    f"Failed to update map description for user {event.user_id}: {e}"
                )

        # Only regenerate image if new room discovered
        if not is_new_visit:
            return

        visited = await User.get_visited_rooms(self.pool, event.user_id)
        image_bytes = generate_map_image(visited, event.to_room)

        image_msg_id = await User.get_map_image_msg_id(self.pool, event.user_id)
        image_file = discord.File(BytesIO(image_bytes), filename="map.png")

        if image_msg_id:
            try:
                image_msg = await thread.fetch_message(image_msg_id)
                await image_msg.edit(attachments=[image_file])
                return
            except (discord.NotFound, discord.HTTPException):
                logger.debug(
                    f"Could not edit map image message {image_msg_id}, "
                    f"will send new one"
                )

        # Fallback: send new image message
        try:
            new_msg = await thread.send(file=image_file)
            await User.update_map_image_msg_id(self.pool, event.user_id, new_msg.id)
        except discord.HTTPException as e:
            logger.error(f"Failed to send map image for user {event.user_id}: {e}")
