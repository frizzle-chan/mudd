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

**RoomChannelCache** (`mudd/observers/discord.py`): Shared cache mapping room names to Discord channel IDs. Created in `main.py`, passed to cogs. Rebuilt by Sync cog after channel creation. Always use `RoomChannelCache` for room→channel lookups — never linearly scan `guild.text_channels` by name.

**Observer pattern in models**: `User` and `EntityInstance` support observers via `_observers` field and `with_observers()` method. Mutation methods (e.g., `move_to()`) emit events to attached observers. Always flush observers after the response is sent. Other models (`Zone`, `Room`, `SpawningPool`) pass observers as function parameters to `sync_all()` instead.

**Observer design rules**:
- Keep observers to the `Observer` protocol (`notify` + `flush`). No side-channel methods (e.g., `queue_xp()`); route everything through `notify()` with signal/event types.
- Cross-observer communication happens via `flush()` return values (events to broadcast) or callbacks — never by having Scene reach into observer internals.
- Flush methods should swap-and-clear input queues at the start (re-entrancy safe). Output accumulators read after flush are exempt from swap pattern.
- New reconcilers that touch Discord belong as sub-reconcilers of `DiscordReconciler` (like `PermissionReconciler`, `InventoryReconciler`). Don't wire standalone reconcilers with special-case code.

**Event separation**: Game logic events (e.g., `UserMovedEvent`) and infrastructure events (e.g., `UserLocationSyncEvent`) are separate. Game events trigger gameplay observers (focus clearing). Infrastructure events trigger Discord reconciliation (permission sync).

**Adding new events**: Update `mudd/events/types.py` (add dataclass, update `GameEvent` union), `mudd/events/__init__.py` (import and export), and the observer that handles the event (e.g., `DiscordReconciler`). Prefer model class methods for database logic over inline SQL in observers.

**Model classmethod naming**: Use Rails-style CRUD names: `get` / `get_by_*` (read), `create` (insert), `get_or_create` / `create_or_update` (upsert), `update_*` (field mutation), `clear_*` (nullify fields), `delete` / `delete_by_*` (remove). Avoid `ensure_*`, `set_*`, or `upsert` as method names. Methods named `get` must be pure reads (return `| None`); if they upsert, rename to `get_or_create`.

**Model return types**: Model `get`/`create` methods must return typed dataclass instances, never raw `dict`. Use attribute access, not key indexing.

**Database concurrency**: Use `SELECT ... FOR UPDATE` inside a transaction for read-then-write mutations on the same row. See `User.credit_from_house()` for the pattern.

**Connection passing in transactions**: When a method holds a `FOR UPDATE` lock inside a transaction, any helper it calls that touches FK-related rows **must** receive the transaction `conn`, not `self._pool`. Using the pool acquires a separate connection, and FK checks (`FOR KEY SHARE`) will deadlock against the `FOR UPDATE` held by the original connection. Type helper parameters as `asyncpg.Pool | asyncpg.Connection` to accept either.

**Batch operations**: Avoid loops that issue one query per iteration (N+1). Use `unnest()` array unpacking or multi-row `INSERT ... VALUES` for bulk operations.

**Type safety at boundaries**: Validate and convert `str` inputs to rich types (e.g., `Skill` enum) at the entry point (e.g., `EffectsCollector`), then propagate the typed value through the entire pipeline. Never pass raw strings through internal layers when an enum or dataclass exists.

**Default room**: Use `Room.get_default(pool)` to find the default spawn room. Do not inline `SELECT ... WHERE is_default = TRUE` queries.

**MUD concept**: Channel topics = room descriptions. Movement hides/shows channels via Discord permissions.

**Currency symbol**: The in-game currency symbol is `¤` (U+00A4). Use it in player-facing strings (e.g., `¤500`) instead of writing "coins" or "gold".

**Design docs**: See `DESIGN.md` for PostgreSQL schema and data persistence details. **Always update DESIGN.md when modifying the database schema.**

**Entity resolution**: When querying entity fields that support prototype inheritance (like `on_close`, `contents_visible`, etc.), use the `resolve_entity()` SQL function instead of joining directly to the `entities` table. Direct joins return NULL for inherited values, while `resolve_entity()` follows the prototype chain and applies defaults.

**Entity display names**: When formatting entity names in user-facing text (memos, Discord messages, notifications), wrap with `ViewEntity(entity)` from `mudd/views.py`. Use `.name` for bold+emoji (`**Treasure Chest 🔵**`) or `.display_name` for emoji only. Never use `entity.name` directly in player-visible strings.

**Discord permission gotchas**:
- Thread creation permissions (`create_public_threads`, `create_private_threads`, `send_messages_in_threads`) are independent of `send_messages`. Deny each one explicitly for read-only channels.
- The bot cannot edit the server owner's nickname. Check `member.id == guild.owner_id` before calling `member.edit(nick=...)` to avoid error spam.
- Discord channel names only allow `[a-z0-9-_]` and silently strip everything else. Use `normalize_channel_name()` from `mudd/utils/discord.py` when computing channel/forum names from usernames to avoid rename loops during sync.
- `guild.get_thread()` is a **local cache-only** lookup — forum threads not recently interacted with are often absent. Use the `_fetch_thread()` helper in `mudd/observers/inventory.py` (cache first, then `guild.fetch_channel()` API fallback) or the equivalent pattern in `mudd/cogs/racing.py`.
- `channel.set_permissions()` always issues a PUT even if the overwrite already matches. Check `channel.overwrites_for(member)` (local cache, no API call) before calling `set_permissions()` in sync loops to avoid 429 rate limits.

**Docker**: The `.dockerignore` uses an allowlist pattern (starts with `*`, then `!` to include specific paths). **When adding new top-level directories needed at runtime, you must add them to `.dockerignore`.**

**Health endpoint** (`mudd/health.py`): The bot serves `GET /healthz` on `HEALTH_PORT` (default 8080). It returns 200 only when all four probes pass — `discord` (gateway connected and heartbeating), `guild` (whitelisted guild in cache), `database` (pool answers a query), and `world` (initial sync finished *and* rooms exist in the database) — otherwise 503 with a JSON body naming the failing probe. It backs the container `HEALTHCHECK` and the CI boot smoke test.

- Probes must never raise; they return a failing `HealthCheck` instead. An exception here would take down the endpoint that is supposed to diagnose the problem.
- Prefer probing real state over trusting a flag. `world` re-queries `Room.count()` rather than only checking `first_sync_completed`, because sync can report success having loaded nothing.
- `HealthState` lives on `MuddBot` and is updated by the Sync cog. It holds only what cannot be probed from outside; everything else is checked live per request.

**Boot smoke test** (`smoke` job in `.github/workflows/docker.yaml`): Builds the `production` target, boots it against a real Postgres and the real Discord gateway, and polls `/healthz` until every probe is green. This catches what unit tests cannot — a bad dependency bump, a runtime file excluded by `.dockerignore`, a migration that fails on boot, or a sync that dies before the world loads.

- Requires the `SMOKE_DISCORD_TOKEN` and `SMOKE_GUILD_ID` repository secrets. **These must be a throwaway bot and an empty guild** — booting runs the full Sync cog, which creates channels, roles, and scheduled events, and syncs slash commands. The job skips itself with a warning when the secrets are absent (fork PRs).
- The job is serialized via a `concurrency` group; concurrent boots would race each other creating the same channels.

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
- No local imports inside method bodies -- always use top-level imports. Break import cycles with protocols in `mudd/models/interfaces.py` (for model-level protocols)
- Remove empty `TYPE_CHECKING` blocks
- Use `typing.cast()` when you've validated a value but the type checker can't infer it
- Use `@overload` for functions with return types that depend on literal argument values

**Vulture whitelist**: For TYPE_CHECKING imports that vulture flags as unused (circular import cases), add to `vulture_whitelist.py`: `from module import Type` then `_ = Type`.

**Return values**: Prefer dataclasses over tuples when returning more than 2 values. Tuples are acceptable for simple pairs (e.g., `(value, error)`) but become unwieldy with 3+ elements. Named fields improve readability and make refactoring safer.

**Modern Python syntax** (requires Python >=3.13):
- Use PEP 695 type parameters (`def f[T]()`) instead of `TypeVar`
- Use `type` alias statements (`type Foo = Bar | Baz`) instead of bare assignments for type aliases
- Use `StrEnum` instead of `(str, Enum)` for string-backed enums
- Use `@dataclass(slots=True)` on frozen/simple dataclasses (not on model dataclasses with `_observers` or `async_cached_property`)
- Use `Self` return type for methods that return their own class (e.g., `with_observers()`)
- Use `@override` on methods that override a base class method

**Idempotent formatting**: Functions that format strings for repeated application (e.g., nickname suffixes, display labels) must strip previous formatting before applying. Assume the input may already contain the old format.

**Colocate data with its type**: When an enum has associated data (emoji, display name, multiplier), store it as a property on the enum using `match` (no wildcard — forces handling new members). Don't use separate dicts that can go out of sync.

## PR Reviews

PR reviews are written to `review.md` (gitignored). When working with reviews:

- **Check for existing review**: Read `review.md` at the start of a session to see pending issues
- **Write reviews**: Use `/pr-review-toolkit:review-pr` to generate comprehensive reviews, then write results to `review.md`
- **Delete when processed**: Remove `review.md` after all issues are addressed or the PR is merged

## Testing

See `tests/CLAUDE.md` for detailed testing guidelines.

**Quick reference**:
```bash
pytest                           # Run all tests (integration + colocated unit tests)
pytest tests/integration/        # Run only integration tests
pytest mudd/                     # Run only colocated unit tests
```

**Unit test convention**: Pure unit tests live alongside source files with the `_unit_test.py` suffix (e.g., `mudd/utils/text_unit_test.py` tests `mudd/utils/text.py`). No `unittest.mock` in unit tests — if it needs mocks, write an integration test instead.

**Image regression tests**: Visual regression tests use the `_image_test.py` suffix and `pytest-regressions[image]`. Baselines are checked-in PNGs in a sibling directory. Regenerate with `pytest <test_file> --regen-all`.

**Test helpers must mirror production**: When test helpers (e.g., `move()`, `interact()`) construct observers or flush pipelines, they must use the same observer list and `flush_all()` path as production cogs. Divergence masks integration bugs.

## Devcontainer Setup

If you encounter permission issues pushing to GitHub, run:

```bash
just devcontainer
```

This authenticates the GitHub CLI using the token in `.github-token.txt`.
