"""Interact command for entity interactions."""

from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING

import asyncpg
import discord
from discord import Interaction, app_commands
from discord.ext import commands

from mudd.cogs.autocomplete_cache import AutocompleteCacheInvalidator
from mudd.cogs.shared import entity_instance_id_autocomplete, resolve_entity
from mudd.commands import get_command
from mudd.matching.verb_matcher import match_verb
from mudd.observers import EffectsObserver
from mudd.scene import Scene

if TYPE_CHECKING:
    from mudd.cogs.autocomplete_cache import AutocompleteCache

logger = logging.getLogger(__name__)


class Interact(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot | None,
        pool: asyncpg.Pool,
        autocomplete_cache: AutocompleteCache | None = None,
    ) -> None:
        self.bot = bot
        self._pool = pool
        self._autocomplete_cache = autocomplete_cache

    async def target_autocomplete(
        self, interaction: Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return await entity_instance_id_autocomplete(
            self._pool, interaction, current, self._autocomplete_cache
        )

    @app_commands.command(name="interact", description="Interact with things")
    @app_commands.describe(
        action="Action to perform (e.g., smash, touch, take)",
        target="Thing to interact with",
    )
    @app_commands.rename(target="with")
    @app_commands.autocomplete(target=target_autocomplete)
    async def interact(self, interaction: Interaction, target: str, action: str):
        # 1. Match verb to action type
        action_type = await match_verb(self._pool, action)
        if action_type is None:
            await interaction.response.send_message(
                "You can't do that.", ephemeral=True
            )
            return

        # 2. Build scene with observers (including cache invalidator)
        scene = await Scene.build(self._pool, interaction, self.bot)
        invalidator = AutocompleteCacheInvalidator.from_cache(
            self._autocomplete_cache, self._pool, scene.user.current_room
        )
        if invalidator:
            scene = scene.with_observers(invalidator)

        # 3. Resolve target entity
        entity = await resolve_entity(
            self._pool,
            scene,
            target,
            lambda _: partial(interaction.response.send_message, ephemeral=True),
        )

        if not entity or not await scene.contains(entity):
            await interaction.response.send_message(
                "You don't see that here.", ephemeral=True
            )
            return

        # 4. Execute command
        command = get_command(action_type)
        result = await scene.execute(command, entity)

        # 5. Send response
        await interaction.response.send_message(
            result.output or "Nothing happens.", ephemeral=True
        )

        # 6. Send broadcasts to channel
        effects = scene.get_observer(EffectsObserver)
        channel = interaction.channel
        if effects and isinstance(channel, discord.abc.Messageable):
            for message in effects.broadcasts:
                try:
                    await channel.send(message)
                except Exception:
                    logger.exception("Failed to send broadcast")

        # 7. Flush observers
        await scene.flush_observers()
