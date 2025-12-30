import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from mudd.cogs.look import Look
from mudd.cogs.ping import Ping

load_dotenv()

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def setup_hook():
    await bot.add_cog(Look(bot))
    await bot.add_cog(Ping(bot))


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")


bot.run(os.environ["DISCORD_TOKEN"])
