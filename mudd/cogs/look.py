"""Look command for viewing surroundings and examining entities."""

from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING

import asyncpg
from discord import Interaction, app_commands
from discord.ext import commands

from mudd.cogs.shared import entity_instance_id_autocomplete, resolve_entity
from mudd.commands import LookCommand
from mudd.observers import EffectsObserver
from mudd.scene import Scene

if TYPE_CHECKING:
    from mudd.cogs.autocomplete_cache import AutocompleteCache

logger = logging.getLogger(__name__)


class Look(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot | None,
        pool: asyncpg.Pool,
        autocomplete_cache: AutocompleteCache | None = None,
    ) -> None:
        self.bot = bot
        self._pool = pool
        self._autocomplete_cache = autocomplete_cache

    async def entity_instance_id_autocomplete(
        self, interaction: Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete for entity instance IDs the user can see."""
        return await entity_instance_id_autocomplete(
            self._pool, interaction, current, self._autocomplete_cache
        )

    @app_commands.command(name="look", description="View surroundings or examine item")
    @app_commands.describe(entity_instance_query="Thing to examine")
    @app_commands.autocomplete(entity_instance_query=entity_instance_id_autocomplete)
    @app_commands.rename(entity_instance_query="at")
    async def look(self, interaction: Interaction, entity_instance_query: str) -> None:
        """Look at room or specific entity."""
        # Build a scene from the interaction that includes the user, entities, etc.
        # If it's a UUID, query directly. Otherwise, use autocomplete to resolve.

        # Build scene with effects observer + cache invalidator
        effects = EffectsObserver()
        scene = await Scene.from_interaction(self._pool, interaction)
        if self._autocomplete_cache is not None:
            invalidator = self._autocomplete_cache.create_invalidator(
                self._pool, scene.user.current_room
            )
            scene = scene.with_observers(effects, invalidator)
        else:
            scene = scene.with_observers(effects)

        entity_instance = await resolve_entity(
            self._pool,
            scene,
            entity_instance_query,
            lambda _: partial(interaction.response.send_message, ephemeral=True),
        )

        if not entity_instance or not await scene.contains(entity_instance):
            await interaction.response.send_message(
                "You don't see that here.", ephemeral=True
            )
            return

        result = await scene.execute(LookCommand(), entity_instance)

        await interaction.response.send_message(
            result.output or "You see nothing special.", ephemeral=True
        )

        # Flush all observers (Discord thread creation, etc.)
        await scene.flush_observers()
