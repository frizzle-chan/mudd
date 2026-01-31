"""Look command for viewing surroundings and examining entities."""

from rapidfuzz import fuzz

from mudd.models.scene import Scene

import logging
from uuid import UUID

import asyncpg
from discord import Interaction, app_commands
from discord.ext import commands

from mudd.models import EntityInstance, User

logger = logging.getLogger(__name__)


class Look(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot | None,
        pool: asyncpg.Pool,
    ) -> None:
        self.bot = bot
        self._pool = pool

    async def entity_instance_id_autocomplete(
        self, interaction: Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete callback for at parameter.

        Suggests entity names from the current room, excluding entities
        inside containers with contents_visible=False. When a user has an
        active focus (open container), shows only the focused contents with
        a "[Close {container}] Room" escape option at the top.

        In inventory threads, only shows the thread's item (no Room option).
        """
        return [
            app_commands.Choice(name=e.entity.name, value=str(e.instance_id))
            for e in await self.autocomplete_entities(interaction, current)
        ][:25]  # Discord limits to 25 options

    async def autocomplete_entities(
        self, interaction: Interaction, current: str
    ) -> list[EntityInstance]:
        """Autocomplete entities the user can see."""
        scene = await Scene.from_interaction(self._pool, interaction)
        if current.startswith("i."):
            # Inventory item lookup
            candidates = await scene.user.get_inventory()
            current = current[2:]
        else:
            # Room entity lookup
            candidates = await scene.room.get_visible_entities()

        if current == "":
            return candidates

        current = current.lower()

        return [
            e
            for e in candidates
            if fuzz.partial_ratio(current, e.entity.name.lower()) >= 75
        ]

    @app_commands.command(name="look", description="View surroundings or examine item")
    @app_commands.describe(entity_instance_query="Thing to examine")
    @app_commands.autocomplete(entity_instance_query=entity_instance_id_autocomplete)
    @app_commands.rename(entity_instance_query="at")
    async def look(self, interaction: Interaction, entity_instance_query: str) -> None:
        """Look at room or specific entity."""
        # discord interaction to scene
        # build a scene from the interaction that includes the user, entiteis, type etc
        # if it's a UUID, query directly. if it's a str, use autocomplete to resolve to uuid
        try:
            entity_instance_id = UUID(entity_instance_query)
            entity_instance = await EntityInstance.get(self._pool, entity_instance_id)
        except ValueError:
            options = await self.autocomplete_entities(
                interaction, entity_instance_query
            )
            if len(options) == 0:
                entity_instance = None
            elif len(options) > 1:
                await interaction.response.send_message(
                    "Multiple things match that description. Please be more specific.",
                    ephemeral=True,
                )
                return
            else:
                entity_instance = options[0]

        scene = await Scene.from_interaction(self._pool, interaction)
        if not entity_instance or not scene.contains(entity_instance):
            await interaction.response.send_message(
                "You don't see that here.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            entity_instance.entity.description_long, ephemeral=True
        )
