from __future__ import annotations

from pathlib import Path
from typing import override

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands

from mudd.database import close_pool
from mudd.health import HealthServer, HealthState


class MuddBot(commands.Bot):
    """MUDD Discord bot with world file configuration."""

    def __init__(self, world_file: Path, *, guild_id: int, **kwargs):
        super().__init__(tree_cls=MuddCommandTree, **kwargs)
        self.world_file = world_file
        self.guild_id = guild_id
        # Startup progress reported by /healthz; updated by the Sync cog.
        self.health = HealthState()
        self._health_server: HealthServer | None = None

    async def start_health_server(self, pool: asyncpg.Pool) -> None:
        """Start the /healthz endpoint. Called once from setup_hook.

        Started before the gateway connects so probes get a descriptive 503
        during startup instead of a connection refused.
        """
        server = HealthServer.from_env(self, pool)
        await server.start()
        self._health_server = server

    async def close(self):
        if self._health_server is not None:
            await self._health_server.close()
            self._health_server = None
        await close_pool()
        await super().close()


class MuddCommandTree(app_commands.CommandTree[MuddBot]):
    """Command tree that blocks interactions from non-whitelisted guilds."""

    @override
    async def interaction_check(self, interaction: discord.Interaction, /) -> bool:
        return interaction.guild_id == self.client.guild_id
