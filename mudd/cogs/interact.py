"""Interact command for entity interactions."""

import logging
from functools import partial

import asyncpg
from discord import Interaction, app_commands
from discord.ext import commands

from mudd.cogs.shared import entity_instance_id_autocomplete, resolve_entity
from mudd.commands2 import get_command
from mudd.matching.verb_matcher import match_verb
from mudd.observers import DiscordReconciler, EffectsObserver
from mudd.scene import Scene

logger = logging.getLogger(__name__)


class Interact(commands.Cog):
    def __init__(self, bot: commands.Bot | None, pool: asyncpg.Pool) -> None:
        self.bot = bot
        self._pool = pool

    async def target_autocomplete(
        self, interaction: Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return await entity_instance_id_autocomplete(self._pool, interaction, current)

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

        # 2. Build scene with observers
        effects = EffectsObserver()
        scene = await Scene.from_interaction(self._pool, interaction)
        if self.bot is not None:
            reconciler = DiscordReconciler(self.bot, self._pool)
            scene = scene.with_observers(effects, reconciler)
        else:
            scene = scene.with_observers(effects)

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

        # 6. Flush observers
        await scene.flush_observers()
