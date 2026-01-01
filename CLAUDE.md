# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MUDD is a Discord-based MUD (multi-user dungeon) where Discord channels represent physical rooms. Players use slash commands (`/look`, `/move`) to navigate, and channel visibility is controlled via Discord permissions to create "fog of war" - players only see the channel they're currently in.

## Commands

```bash
# Install dependencies
uv sync --locked

# Run all checks (lint + format + types)
just

# Individual checks
just lint      # ruff check
just format    # ruff format
just types     # ty check

# Run the bot (requires .env with DISCORD_TOKEN, MUDD_WORLD_CATEGORY_ID, MUDD_DEFAULT_CHANNEL_ID)
python main.py
```

Pre-commit hooks (lefthook) auto-run ruff and ty on staged files.

## Architecture

**Entry point**: `main.py` - Async bot setup using `discord.py`, syncs slash commands on ready.

**Cog system**: Commands live in `mudd/cogs/`. Each cog:
- Inherits from `commands.Cog`
- Defines slash commands via `@app_commands.command`
- Gets loaded in `main.py`

**MUD concept**: Channel topics = room descriptions. Movement hides/shows channels via Discord permissions.

**Design docs**: See `DESIGN.md` for Redis schema and data persistence details. **Always update DESIGN.md when modifying the Redis schema.**

## Dependencies

- `discord.py` - Discord bot library
- `python-dotenv` - Environment variable loading
- `redis` - Redis client for location persistence
- `ruff` - Linting and formatting
- `ty` - Type checking (Astral)
- `uv` - Package management
