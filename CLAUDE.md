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
just format    # ruff format --check (use `ruff format .` to auto-fix)
just types     # ty check
just test      # pytest (use `just testq` for quick/quiet mode)

# Run the bot (requires .env with DISCORD_TOKEN)
./dev
```

When asked to debug the last run, inspect the logs in ./mudd.log

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

### MVC Architecture

The codebase uses an MVC + events architecture:

- **Models** (`mudd/models/`): Domain objects with async factory methods for DB access
  - `User`, `Room`, `Zone`, `EntityInstance`, `EntityDefinition`, `SpawningPool`
  - Models encapsulate queries and business logic
- **Events** (`mudd/events/`): Event types and the observer protocol
  - `EventCollector`, `Observer`, event dataclasses
- **Observers** (`mudd/observers/`): React to events after command execution
  - `EffectsObserver`: Collects in-template effects (pickup, drop, broadcast)
  - `DiscordReconciler`: Syncs Discord state (threads, permissions, channels)
  - `FocusClearingObserver`: Clears user focus on movement events
- **Scene** (`mudd/scene.py`): Ties together user, room, focus, and observers for command execution

**Reference cogs**: `mudd/cogs/look.py`, `mudd/cogs/interact.py`

**Pattern for new commands**:
1. Build a `Scene` from the interaction
2. Attach observers (`EffectsObserver`, `DiscordReconciler`)
3. Resolve target entities via `resolve_entity()`
4. Execute command via `scene.execute(command, entity)`
5. Flush observers via `scene.flush_observers()`

**Sync cog** (`mudd/cogs/sync.py`): Owns ALL synchronization:
- First iteration: Zone/room sync, RoomChannelCache rebuild, permission sync
- Every 15 minutes: Full zone/room sync (recreates deleted channels, fixes topics) + permission sync
- Tracks orphan channels and only reports NEW ones to #console

**RoomChannelCache** (`mudd/observers/discord.py`): Shared cache mapping room names to Discord channel IDs. Created in `main.py`, passed to cogs. Rebuilt by Sync cog after channel creation.

**Observer pattern in models**: Models like `User` and `EntityInstance` support observers via `_observers` field and `with_observers()` method. Mutation methods (e.g., `move_to()`) emit events to attached observers. Always flush observers after the response is sent.

**Event separation**: Game logic events (e.g., `UserMovedEvent`) and infrastructure events (e.g., `UserLocationSyncEvent`) are separate. Game events trigger gameplay observers (focus clearing). Infrastructure events trigger Discord reconciliation (permission sync).

**Adding new events**: Update `mudd/events/types.py` (add dataclass, update `GameEvent` union), `mudd/events/__init__.py` (import and export), and the observer that handles the event (e.g., `DiscordReconciler`). Prefer model class methods for database logic over inline SQL in observers.

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
- Use `from __future__ import annotations` in all files - enables forward references without quotes
- Use `TYPE_CHECKING` imports only for circular import prevention, not forward references
- Remove empty `TYPE_CHECKING` blocks
- Use `typing.cast()` when you've validated a value but the type checker can't infer it
- Use `@overload` for functions with return types that depend on literal argument values

**Vulture whitelist**: For TYPE_CHECKING imports that vulture flags as unused (circular import cases), add to `vulture_whitelist.py`: `from module import Type` then `_ = Type`.

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
