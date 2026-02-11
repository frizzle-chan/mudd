from __future__ import annotations

from pathlib import Path
from typing import override

import discord
from discord import app_commands
from discord.ext import commands

from mudd.database import close_pool


class MuddBot(commands.Bot):
    """MUDD Discord bot with world file configuration."""

    def __init__(self, world_file: Path, *, guild_id: int, **kwargs):
        super().__init__(tree_cls=MuddCommandTree, **kwargs)
        self.world_file = world_file
        self.guild_id = guild_id

    async def close(self):
        await close_pool()
        await super().close()


class MuddCommandTree(app_commands.CommandTree[MuddBot]):
    """Command tree that blocks interactions from non-whitelisted guilds."""

    @override
    async def interaction_check(self, interaction: discord.Interaction, /) -> bool:
        return interaction.guild_id == self.client.guild_id
