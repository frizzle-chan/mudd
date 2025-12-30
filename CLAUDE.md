# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MUDD is a Discord-based MUD (multi-user dungeon) where Discord channels represent physical rooms. Players use slash commands (`/look`, `/move`) to navigate, and channel visibility is controlled via Discord permissions to create "fog of war" - players only see the channel they're currently in.

## Architecture

**Entry point**: `main.py` - Async bot setup using `discord.py`, syncs slash commands on ready.

**Cog system**: Commands live in `mudd/cogs/`. Each cog:
- Inherits from `commands.Cog`
- Defines slash commands via `@app_commands.command`
- Gets loaded in `main.py`

Current cogs:
- `ping.py` - `/ping` returns latency
- `look.py` - `/look` returns channel topic (room description)

**MUD concept**: Channel topics = room descriptions. Movement will hide/show channels via Discord permissions.

## Dependencies

- `discord.py` - Discord bot library
- `python-dotenv` - Environment variable loading
- `ruff` - Linting and formatting
- `ty` - Type checking (Astral)
- `uv` - Package management
