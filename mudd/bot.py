from pathlib import Path

from discord.ext import commands

from mudd.database import close_pool


class MuddBot(commands.Bot):
    """MUDD Discord bot with world file configuration."""

    def __init__(self, world_file: Path, **kwargs):
        super().__init__(**kwargs)
        self.world_file = world_file

    async def close(self):
        await close_pool()
        await super().close()
