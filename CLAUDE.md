# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MUDD is a Discord-based MUD (multi-user dungeon) where Discord channels represent physical rooms. Players use slash commands (`/look`, `/move`, `/interact`) to navigate and interact with entities, and channel visibility is controlled via Discord permissions to create "fog of war" - players only see the channel they're currently in.

## Production Considerations

This service is running in production with active users. When planning changes:

- **Backwards compatibility**: Ensure API changes (slash commands, command arguments) don't break existing user workflows
- **Database migrations**: Schema changes must include migration scripts that preserve existing data
- **Rollback plan**: Consider how changes can be reverted if issues arise
- **Downtime**: Minimize or eliminate downtime during deployments

## Commands

```bash
# Install dependencies
uv sync --locked

# Run all checks (see justfile for full list)
just

# Individual checks
just lint      # ruff check
just format    # ruff format
just types     # ty check

# Run the bot (requires .env with DISCORD_TOKEN)
just dev
```

When asked to debug the last run, inspect the logs in .tasks/lastrun.log

Pre-commit hooks (lefthook) auto-run ruff and ty on staged files.

**Query dev database**:
```bash
PGPASSWORD=mudd psql -h db -U mudd -d mudd -c "SELECT * FROM table_name"
```

## Architecture

**Entry point**: `main.py` - Async bot setup using `discord.py`, syncs slash commands on ready.

**Cog system**: Commands live in `mudd/cogs/`. Each cog:
- Inherits from `commands.Cog`
- Defines slash commands via `@app_commands.command`
- Gets loaded in `main.py`

**Sync cog** (`mudd/cogs/sync.py`): Owns ALL synchronization:
- First iteration: Zone/room sync, VisibilityService initialization, permission sync
- Every 15 minutes: Full zone/room sync (recreates deleted channels, fixes topics) + permission sync
- Tracks orphan channels and only reports NEW ones to #console

**MUD concept**: Channel topics = room descriptions. Movement hides/shows channels via Discord permissions.

**Design docs**: See `DESIGN.md` for PostgreSQL schema and data persistence details. **Always update DESIGN.md when modifying the database schema.**

**Entity resolution**: When querying entity fields that support prototype inheritance (like `focus_mode`, `on_close`, etc.), use the `resolve_entity()` SQL function instead of joining directly to the `entities` table. Direct joins return NULL for inherited values, while `resolve_entity()` follows the prototype chain and applies defaults.

**Docker**: The `.dockerignore` uses an allowlist pattern (starts with `*`, then `!` to include specific paths). **When adding new top-level directories needed at runtime, you must add them to `.dockerignore`.**

## Dependencies

**Runtime:**
- `discord.py` - Discord bot library
- `python-dotenv` - Environment variable loading
- `asyncpg` - PostgreSQL client for data persistence
- `jinja2` - Template rendering for entity handlers

**Development:**
- `ruff` - Linting and formatting
- `ty` - Type checking (Astral)
- `uv` - Package management
- `lefthook` - Git hooks
- `pytest` / `pytest-asyncio` - Testing
- `squawk-cli` - PostgreSQL migration linting

## Code Style

**Type checking**: Fix root causes of type errors rather than using `# type: ignore`. Common fixes:
- Use `TYPE_CHECKING` imports to properly type cross-module references
- Use `typing.cast()` when you've validated a value but the type checker can't infer it
- Use `@overload` for functions with return types that depend on literal argument values

**Return values**: Prefer dataclasses over tuples when returning more than 2 values. Tuples are acceptable for simple pairs (e.g., `(value, error)`) but become unwieldy with 3+ elements. Named fields improve readability and make refactoring safer.

## PR Reviews

PR reviews are written to `review.md` (gitignored). When working with reviews:

- **Check for existing review**: Read `review.md` at the start of a session to see pending issues
- **Write reviews**: Use `/pr-review-toolkit:review-pr` to generate comprehensive reviews, then write results to `review.md`
- **Delete when processed**: Remove `review.md` after all issues are addressed or the PR is merged

## Testing

See `tests/CLAUDE.md` for detailed testing guidelines.

**Quick reference**:
```bash
pytest tests/                    # Run all tests
pytest tests/integration/        # Run only integration tests
pytest tests/unit/               # Run only unit tests
```

## Devcontainer Setup

If you encounter permission issues pushing to GitHub, run:

```bash
just devcontainer
```

This authenticates the GitHub CLI using the token in `.github-token.txt`.
