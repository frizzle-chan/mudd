import asyncio
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from mudd.cogs.ping import Ping

load_dotenv()


async def main():
    intents = discord.Intents.default()
    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        await bot.tree.sync()
        print(f"Logged in as {bot.user}")

    await bot.add_cog(Ping(bot))
    await bot.start(os.environ["DISCORD_TOKEN"])


if __name__ == "__main__":
    asyncio.run(main())
