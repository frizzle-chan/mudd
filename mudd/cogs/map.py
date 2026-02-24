"""Map command for MUDD."""

from __future__ import annotations

from io import BytesIO

import asyncpg
import discord
from discord import Interaction, app_commands
from discord.ext import commands

from mudd.map.rendering import generate_map_image
from mudd.models.user import User


class Map(commands.Cog):
    """View your discovered map."""

    def __init__(self, bot: commands.Bot | None, pool: asyncpg.Pool) -> None:
        self.bot = bot
        self._pool = pool

    @app_commands.command(name="map", description="View your discovered map")
    async def map(self, interaction: Interaction):
        visited = await User.get_visited_rooms(self._pool, interaction.user.id)
        image_bytes = generate_map_image(visited)

        file = discord.File(BytesIO(image_bytes), filename="map.png")
        await interaction.response.send_message(file=file, ephemeral=True)
