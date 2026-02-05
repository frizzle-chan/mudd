# DESIGN.md

Technical design documentation for MUDD.

## Database Schema

PostgreSQL is the source of truth for user locations. Discord channel permissions are derived from database state during:
- Bot startup (syncs all users)
- Movement commands
- User join/leave events

### Users Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGINT (PK) | Discord user snowflake ID |
| `current_room` | TEXT (FK to rooms.id) | Logical room name (e.g., "foyer") |
| `display_name` | TEXT NOT NULL DEFAULT '' | Cached Discord display name for DB-driven autocomplete |
| `created_at` | TIMESTAMPTZ | When the record was created |
| `updated_at` | TIMESTAMPTZ | When the record was last modified |

**Indexes:**
- Primary key on `id`
- Index on `current_room` for room-based queries

**Constraints:**
- FK to rooms.id with ON DELETE RESTRICT (prevents deleting rooms with users in them)

### Zones Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT (PK) | Zone identifier, matches Discord category name (lowercase, hyphenated) |
| `name` | TEXT NOT NULL | Display name for the zone |
| `description` | TEXT | MUD flavor text for entering the zone |

**Data Source:**
- Zones are defined in `data/worlds/*.rec` files as `Zone` records
- Zone IDs match Discord category names for auto-discovery
- Synced to database on bot startup

### Rooms Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT (PK) | Logical room name, matches Discord channel name |
| `name` | TEXT NOT NULL | Display name for the room |
| `description` | TEXT NOT NULL | Room description (synced to Discord channel topic) |
| `zone_id` | TEXT NOT NULL (FK to zones.id) | Parent zone for this room |
| `has_voice` | BOOLEAN NOT NULL DEFAULT FALSE | Whether to create a paired voice channel |
| `is_default` | BOOLEAN NOT NULL DEFAULT FALSE | Whether this is the default spawn room for new users |

**Indexes:**
- Primary key on `id`
- Index on `zone_id` for zone-based queries
- Partial unique index on `is_default` WHERE `is_default = TRUE` (enforces only one default room)

**Data Source:**
- Rooms are defined in `data/worlds/*.rec` files as `Room` records
- Each room has a Zone field referencing its parent zone
- Room connections are implicit via Discord channel mentions in descriptions (e.g., `#hallway`)
- Synced to database on bot startup; bot creates missing Discord channels
- `IsDefault` field in rec files marks the default spawn room (stored in `is_default` column)

### Schema Migrations Table

| Column | Type | Description |
|--------|------|-------------|
| `version` | INTEGER (PK) | Migration version number |
| `applied_at` | TIMESTAMPTZ | When the migration was applied |
| `filename` | TEXT | Original migration filename |

### Entities Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT (PK) | Unique entity identifier |
| `name` | TEXT NOT NULL | Display name for the entity |
| `prototype_id` | TEXT (FK to entities.id) | Reference to parent entity for prototypical inheritance |
| `description_short` | TEXT | Brief description (Jinja2 template with `{{ name }}` support) |
| `description_long` | TEXT | Detailed description (Jinja2 template with `{{ name }}` support) |
| `on_look` | TEXT | Handler response for look action (NULL = inherit from prototype) |
| `on_touch` | TEXT | Handler response for touch action (NULL = inherit from prototype) |
| `on_attack` | TEXT | Handler response for attack action (NULL = inherit from prototype) |
| `on_use` | TEXT | Handler response for use action (NULL = inherit from prototype) |
| `on_take` | TEXT | Handler response for take action (NULL = inherit from prototype) |
| `on_open` | TEXT | Handler response for open action (NULL = inherit from prototype) |
| `on_close` | TEXT | Handler response for close action (NULL = inherit from prototype) |
| `on_drop` | TEXT | Handler response for drop action (NULL = inherit from prototype) |
| `contents_visible` | BOOLEAN | Whether child entities appear in room descriptions (NULL = inherit, TRUE = auto-list, FALSE = hidden until examined) |
| `rarity` | rarity NOT NULL DEFAULT 'none' | Item rarity affecting name display and pickup behavior |

**Constraints:**
- Self-reference prevention: `id != prototype_id`

**Pickup Behavior:**
- Controlled by `effects.pickup()` in `on_take` templates
- If template calls `pickup()`: item moves to inventory
- If template doesn't call `pickup()`: message shown, item stays

**Focus Behavior:**
- Controlled by `effects.set_focus()` and `effects.clear_focus()` in templates
- Call `effects.set_focus()` in `on_open` or `on_use` to establish focus on the entity
- Call `effects.clear_focus()` in `on_close` to clear focus
- When focused, autocomplete shows only container contents

**Indexes:**
- Primary key on `id`
- GIN index on `name` using pg_trgm for fuzzy matching
- Index on `prototype_id` for inheritance queries

### Entity Instances Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Auto-generated unique instance identifier |
| `entity_id` | TEXT NOT NULL (FK to entities.id) | Reference to entity definition |
| `room` | TEXT (FK to rooms.id) | Logical room name (NULL when in inventory or container) |
| `owner_id` | BIGINT (FK to users.id) | Player who owns this instance (NULL when in room) |
| `discord_thread_id` | BIGINT | Discord thread ID when item is in inventory (NULL when in room) |
| `discord_description_msg_id` | BIGINT | Message ID of the description post in thread (for sync updates) |
| `created_at` | TIMESTAMPTZ NOT NULL | Instance creation timestamp |
| `spawning_pool_id` | TEXT (FK to spawning_pools.id) | Spawning pool that created this instance (NULL for static instances) |
| `player_dropped` | BOOLEAN NOT NULL DEFAULT false | Whether this item was dropped by a player (prevents respawn cleanup) |
| `container_entity_id` | TEXT (FK to entities.id) | Container entity holding this item (NULL when in room or inventory) |
| `is_world_instance` | BOOLEAN NOT NULL DEFAULT false | Marks canonical world instances that should be restored on sync |

**Constraints:**
- Mutual exclusivity: `(room IS NOT NULL AND owner_id IS NULL) OR (room IS NULL AND owner_id IS NOT NULL)`
- Unique constraint on `(entity_id, room)` WHERE `is_world_instance = TRUE` (enables idempotent sync for world instances)
- FK to entities.id with ON DELETE CASCADE (deleting an entity cascades to all its instances)
- FK to users.id with ON DELETE CASCADE (deleting a user cascades to their inventory items)
- FK to rooms.id with ON DELETE CASCADE (deleting a room cascades to entity instances in it)

**Indexes:**
- Primary key on `id`
- Partial unique index on `(entity_id, room)` WHERE `is_world_instance = TRUE` (for idempotent sync of world instances)
- Partial index on `room` (WHERE room IS NOT NULL) for room-based queries
- Partial index on `owner_id` (WHERE owner_id IS NOT NULL) for inventory queries

**Instance Creation:**
- Instances for entities with `Room` field in `.rec` files are created during `sync_entities()`
- Uses `INSERT ON CONFLICT DO NOTHING` for idempotent sync (same entity+room = no-op)
- Inventory instances (owner_id set) are NOT affected by sync - they persist independently

### Entity Tags Table

| Column | Type | Description |
|--------|------|-------------|
| `entity_id` | TEXT NOT NULL (FK to entities.id) | Entity being tagged |
| `tag` | TEXT NOT NULL | Tag value (e.g., "weapon", "key", "treasure") |

**Constraints:**
- PK on `(entity_id, tag)` (unique tag per entity)
- FK to entities(id) with ON DELETE CASCADE

**Purpose:**
- Enables grouping entities by category for spawning pool queries
- Tags are defined in `.rec` files with the `Tag` field (can have multiple Tag lines)
- Used by spawning pools to select random entities matching tag criteria

### Spawning Pools Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT (PK) | Unique spawning pool identifier |
| `room` | TEXT NOT NULL (FK to rooms.id) | Room where spawned items appear |
| `container_id` | TEXT (FK to entities.id) | Optional container to spawn items into |
| `tag_query` | TEXT NOT NULL | Tag expression to match entities (e.g., "weapon", "treasure") |
| `max_count` | INTEGER NOT NULL DEFAULT 1 | Maximum items this pool maintains |
| `respawn_interval_minutes` | INTEGER NOT NULL DEFAULT 30 | Minimum time between spawns |
| `last_spawn_at` | TIMESTAMPTZ | When the pool last spawned an item |
| `no_duplicates` | BOOLEAN NOT NULL DEFAULT FALSE | When TRUE, won't spawn an entity type already spawned by this pool |

**Purpose:**
- Manages automatic item respawning in rooms
- Selects random entities matching `tag_query` when below `max_count`
- Respects `respawn_interval_minutes` between spawns
- Can spawn directly into room or into a container
- With `no_duplicates`, ensures variety by preventing duplicate entity types

**Constraints:**
- FK to rooms(id) with ON DELETE CASCADE
- FK to entities(id) with ON DELETE CASCADE (for container_id)

### User Inventory Forums Table

| Column | Type | Description |
|--------|------|-------------|
| `user_id` | BIGINT (PK, FK to users.id) | Discord user ID |
| `forum_id` | BIGINT NOT NULL | Discord forum channel snowflake |
| `category_id` | BIGINT NOT NULL | Discord category snowflake (for validation) |
| `created_at` | TIMESTAMPTZ NOT NULL | When the forum was created |

**Purpose:**
- Tracks per-user inventory forum channels
- Each user gets a private forum channel named `{braille_user_id}-inventory`
- Items in inventory are represented as threads within the forum
- Only the owner can see their inventory forum

**Constraints:**
- PK on `user_id` (one forum per user)
- FK to users(id) with ON DELETE CASCADE

**Discord Integration:**
- Forums created in a dedicated "Inventory" category with `@everyone` view_channel=False
- Per-user forum permissions grant only the owner view_channel=True
- When items are taken, a thread is created in the user's forum
- When items are dropped, the thread is deleted

**Entity Instances Extension:**
- `discord_thread_id BIGINT` column added to entity_instances
- `discord_description_msg_id BIGINT` stores the first message ID (item description)
- Stores the Discord thread ID when an item is in a user's inventory
- NULL when item is in a room (not in inventory)
- Indexed for quick thread → instance lookups
- Thread first post contains rendered `on_look` description, edited during sync to stay current

### User Focus Table

| Column | Type | Description |
|--------|------|-------------|
| `user_id` | BIGINT (PK, FK to users.id) | Discord user ID |
| `entity_instance_id` | UUID NOT NULL (FK to entity_instances.id) | Focused entity instance (room and entity_id derived via join) |
| `updated_at` | TIMESTAMPTZ NOT NULL | Last interaction timestamp for timeout |

**Purpose:**
- Tracks which container/entity a user has "open" and is currently focusing on
- Enables autocomplete to prioritize contextually relevant entities
- Persists across bot restarts (stored in PostgreSQL, not memory)

**Focus Lifecycle (ADR 0003):**
- Established: When template calls `effects.set_focus()` (typically in `on_open` or `on_use` handlers)
- Cleared: When template calls `effects.clear_focus()` (typically in `on_close` handler), room movement, looking at room, looking at unrelated entity, interacting with unrelated entity, 5-minute timeout
- Preserved: Looking at focused entity or its contents, interacting with focused entity or its contents

**Constraints:**
- PK on `user_id` (one focus per user)
- FK to users(id) with ON DELETE CASCADE
- FK to entity_instances(id) with ON DELETE CASCADE

**Indexes:**
- Primary key on `user_id`
- Index on `updated_at` for timeout queries

### Currency Accounts Table

| Column | Type | Description |
|--------|------|-------------|
| `user_id` | BIGINT (PK) | Discord user ID (0 is house account) |
| `balance` | BIGINT NOT NULL | Current balance in yen (must be >= 0) |
| `wallet_instance_id` | UUID (FK to entity_instances.id) | Player's wallet entity instance |
| `created_at` | TIMESTAMPTZ NOT NULL | When the account was created |

**Purpose:**
- Tracks player currency balances
- Links to wallet entity instance for balance display
- House account (user_id=0) holds system funds for grants and NPC purchases

**Constraints:**
- PK on `user_id`
- CHECK on `balance >= 0` prevents negative balances
- FK to entity_instances(id) with ON DELETE SET NULL

### Currency Transactions Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Auto-generated transaction identifier |
| `memo` | TEXT | Human-readable description |
| `idempotency_key` | TEXT UNIQUE | Optional key for idempotent retries |
| `created_at` | TIMESTAMPTZ NOT NULL | When the transaction was created |

**Purpose:**
- Records all currency movements for audit trail
- Idempotency key prevents duplicate transactions

### Currency Ledger Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Auto-generated entry identifier |
| `transaction_id` | UUID NOT NULL (FK to currency_transactions.id) | Parent transaction |
| `account_id` | BIGINT NOT NULL (FK to currency_accounts.user_id) | Account affected |
| `amount` | BIGINT NOT NULL | Change amount (positive=credit, negative=debit) |
| `created_at` | TIMESTAMPTZ NOT NULL | When the entry was created |

**Purpose:**
- Double-entry ledger for complete audit trail
- Each transaction has two entries: debit (negative) and credit (positive)
- Self-balancing: sum of all entries should be zero

**Indexes:**
- Index on `account_id` for balance history queries
- Index on `transaction_id` for transaction details

### Verbs Table

| Column | Type | Description |
|--------|------|-------------|
| `verb` | TEXT (PK) | The verb word (e.g., 'smash', 'look') |
| `action` | verb_action NOT NULL | The action handler type to invoke |

**Verb Action Enum:** `on_look`, `on_touch`, `on_attack`, `on_use`, `on_take`, `on_open`, `on_close`, `on_drop`

**Indexes:**
- Primary key on `verb`
- GIN index on `verb` using pg_trgm for fuzzy matching (typo tolerance)

**Data Source:**
- Verbs are loaded from `data/verbs/*.txt` files on bot startup
- Each file contains one verb per line, mapped to the action matching the filename
- Full sync on startup: verbs not in files are removed from the database

### Entity Inheritance

The `resolve_entity(target_id TEXT)` function resolves entity properties by walking up the prototype chain:
- Returns merged properties where child values override parent values
- First non-NULL value wins for each property
- Supports up to 10 levels of inheritance depth (prevents infinite loops from circular references)
- Used to materialize the final entity state including inherited properties
- Returns: `id`, `name`, `description_short`, `description_long`, `on_*` handlers (including `on_open`, `on_close`), `contents_visible`, `rarity`

## Sync System

The `Sync` cog owns all synchronization operations. Both startup and periodic syncs execute the same full sync logic.

### Sync Flow

```
Bot Startup
    ↓
setup_hook()
    ├─ init_database() ─────→ PostgreSQL migrations
    ├─ sync_verbs()    ─────→ Load verb word lists
    └─ add_cog(Sync)   ─────→ Start periodic_sync timer

on_ready()
    └─ tree.sync()     ─────→ Register slash commands

periodic_sync() [FIRST ITERATION]
    ├─ sync_zones_and_rooms() ─→ Load .rec files
    │    ├─ Sync to database
    │    ├─ Create Discord categories/channels
    │    ├─ Fix channel topics
    │    └─ Return orphans + default_room
    │
    ├─ visibility_service.sync_guild()
    │    ├─ Build room cache (uses default_room)
    │    └─ Sync user permissions
    │
    └─ mark_startup_complete() ─→ UNBLOCK COMMANDS

periodic_sync() [EVERY 15 MINUTES]
    ├─ sync_zones_and_rooms()
    │    ├─ Recreate deleted channels
    │    ├─ Fix drifted channel topics
    │    └─ Report NEW orphans only
    │
    └─ visibility_service.sync_guild()
         ├─ Rebuild room cache
         └─ Sync user permissions
```

### Key Behaviors

**Channel recreation**: If a Discord channel is deleted, the next sync recreates it from the room definition in `.rec` files.

**Topic drift correction**: If a channel topic is manually changed, the next sync restores it from the room description.

**Orphan tracking**: Orphan channels (in zone categories but not in `.rec` files) are tracked across syncs. Only NEW orphans trigger a warning to `#console`, preventing spam on restart.

**Command blocking**: Commands call `wait_for_startup()` and block until the first sync completes. This ensures the VisibilityService is initialized before any permission operations.

## Zone System

Zones map 1:1 with Discord categories. Each zone groups multiple rooms together.

**Zone discovery:**
- Zones defined in `.rec` files are synced to database on startup and every 15 minutes
- Discord categories are matched by name (lowercase, hyphenated)
- Missing categories are created automatically with fog-of-war permissions

**Room/Channel sync:**
- Missing text channels are created from room definitions
- Channel topics are synced from room descriptions
- Voice channels are created for rooms with `has_voice: yes`
- Deleted channels are recreated on next sync

## Room Abstraction

User locations are stored as logical room names (e.g., "foyer", "office") rather than Discord channel IDs. This provides:
- Readable database values
- Portability across Discord servers
- Alignment with entity system design

**Room name resolution:**
- At startup, build an in-memory cache mapping room names to channel IDs
- Room names are derived from Discord channel names in zone categories
- Only channels that exist in the rooms database are cached
- Channel ID lookups are O(1) via the cache

## Migration System

Migrations are raw SQL files in the `/migrations` directory:
- Named with pattern: `NNN_description.sql` (e.g., `001_users.sql`)
- Applied automatically at bot startup
- Tracked in `schema_migrations` table
- Each migration runs in a transaction

## Connection Management

- Uses `asyncpg` connection pool
- Pool size: 2-10 connections
- Connections are acquired per-query and released automatically
- Pool is closed gracefully on bot shutdown

## Visibility Sync

The `VisibilityService.sync_guild()` method ensures Discord channel permissions match database state:

1. Rebuilds the room name ↔ channel ID cache from database + Discord
2. For each non-bot member:
   - If no location in DB → assign to default room
   - If location invalid (channel deleted) → assign to default room
   - Sync permissions: grant `view_channel` for current room, remove for all others

This runs as part of the unified sync flow described above.

## Scene

The `Scene` class (`mudd/scene.py`) represents the game context for a user's interaction. It encapsulates the user, their location, and attached observers.

### Construction

`Scene.from_interaction(pool, interaction)` builds a Scene from a Discord interaction:
- If in an inventory thread → wraps thread entity as `EntityModal`
- If user has active focus → wraps focused entity as `EntityModal`
- Otherwise → loads the user's current room

### Key Methods

- `with_observers(*observers)` - Returns new Scene with observers attached (immutable)
- `contains(entity)` - Checks if entity is visible (in room or inventory)
- `execute(command, entity)` - Executes command and processes signals
- `flush_observers()` - Runs deferred async operations after response sent

### Data Flow

```
Scene.from_interaction(pool, interaction)
    ├─ Determine location (room, focus, or thread)
    ├─ Load user and room/modal
    └─ Return Scene(user, room, observers)

scene.execute(command, entity)
    ├─ Attach observers to entity
    ├─ Run command.execute() → render template
    ├─ Map signals to mutations:
    │   ├─ has_pickup → entity.move_to_inventory()
    │   ├─ has_drop → entity.drop_to_room()
    │   ├─ has_destroy → entity.destroy()
    │   ├─ has_set_focus → user.set_focus(entity)
    │   └─ has_clear_focus → user.clear_focus()
    └─ Return ActionResult(output)

scene.flush_observers()
    └─ DiscordReconciler creates/deletes inventory threads
```

## Entity Resolution

Entity resolution is handled by utility functions in `mudd/cogs/shared.py`.

### Functions

- `resolve_entity(pool, scene, query, ambiguous_handler)` - Resolves a query string to an EntityInstance
  - Tries UUID parse first
  - Falls back to fuzzy name matching via `autocomplete_entities()`
  - Shows disambiguation message if multiple matches
  - Returns single entity or None

- `autocomplete_entities(scene, current)` - Returns matching entities for Discord autocomplete
  - Filters entities visible in the scene by fuzzy name matching
  - Supports "i." prefix for inventory-only search
  - Returns exact matches first, then partial matches (75% threshold)

- `entity_instance_id_autocomplete(pool, interaction, current)` - Discord autocomplete callback
  - Builds Scene from interaction
  - Returns up to 25 choices

### Focus Handling

Focus state is integrated into Scene construction:
- `EntityModal` wraps a focused container as a pseudo-room
- When focused, `scene.room` returns the modal with container contents
- Autocomplete shows only focused contents until closed

## Commands

Commands (`mudd/commands.py`) implement the command pattern for entity interactions.

### ActionCommand Base

Abstract base class with:
- `get_handler_text(entity)` - Returns the entity field to render (e.g., `on_look`)
- `execute(scene, entity)` - Renders template and returns `ActionResult`

### Concrete Commands

| Command | Handler Field |
|---------|---------------|
| `LookCommand` | `on_look` |
| `TouchCommand` | `on_touch` |
| `AttackCommand` | `on_attack` |
| `UseCommand` | `on_use` |
| `TakeCommand` | `on_take` |
| `DropCommand` | `on_drop` |
| `OpenCommand` | `on_open` |
| `CloseCommand` | `on_close` |

### Factory

`get_command(action: VerbAction)` maps verb actions to command instances.

## Observers and Events

The observer pattern (`mudd/observers/`, `mudd/events/`) handles side effects from template execution.

### Observer Protocol

```python
class Observer(Protocol):
    def notify(self, event: GameEvent) -> None: ...  # Sync, during rendering
    async def flush(self) -> None: ...               # Async, after response sent
```

### EffectsObserver

Collects template events during rendering:
- **Signals**: `has_pickup`, `has_drop`, `has_destroy`, `has_dispense`, `has_set_focus`, `has_clear_focus`
- **Effects**: `broadcasts`, `grants`, `grant_randoms`, `currency_grants`

### DiscordReconciler

Syncs Discord state when entities change:
- `EntityPickedUpEvent` → Creates inventory thread
- `EntityDroppedEvent` → Deletes inventory thread
- `EntityDestroyedEvent` → Deletes inventory thread

### Event Types

**Signals** (control entity state):
- `PickupSignal`, `DropSignal`, `DestroySignal`, `DispenseSignal`, `SetFocusSignal`, `ClearFocusSignal`

**Effects** (template side effects):
- `BroadcastEvent(message)`, `GrantEvent(entity_id)`, `GrantRandomEvent(tag)`, `GrantCurrencyEvent(amount)`

**Model Events** (from entity mutations):
- `EntityPickedUpEvent`, `EntityDroppedEvent`, `EntityDestroyedEvent`

## Template Rendering

Entity action handlers (`on_look`, `on_touch`, `on_attack`, `on_use`, `on_take`, `on_open`, `on_close`) are Jinja2 templates rendered at runtime.

### Template Context

Templates have access to:
- `e`: The resolved entity (ResolvedEntity) with all inherited properties
- `name`: Entity name pre-formatted with Discord italics (`*Name*`)
- `contents`: Pre-formatted bullet list of container contents (for entities with `contents_visible`)
- `user`: User context with `name` (display name) and `mention` (@mention string)
- `effects`: Side effects object for triggering actions beyond the ephemeral response

### Rendering Flow

```
/look at:<entity>
    └─ render_entity_on_look(instance)
        ├─ Build context: {"e": entity, "name": "*Wooden Table*"}
        ├─ Render on_look template
        │   └─ If error: fallback to description_long or description_short
        │       └─ Append "-# (error rendering template)" warning
        └─ Append container contents (if contents_visible)

/interact with:<entity> action:<verb>
    ├─ Match target using word-prefix matching (entity_matcher.py)
    │   ├─ No match → "You don't see '{target}' here."
    │   └─ Multiple matches → "Which one? *Entity1*, *Entity2*"
    ├─ Look up verb in verbs table (verb_matcher.py)
    │   └─ No match → "You can't do that."
    ├─ Get handler text (on_attack, on_touch, etc.) from entity
    │   └─ No handler → "Nothing happens."
    └─ Render handler template
        ├─ Build context: {"e": entity, "name": "*Fancy Vase*"}
        └─ If error: log warning, return fallback message
```

### Error Handling

Template errors (syntax errors, undefined variables) are handled gracefully:
1. Log the error with entity ID
2. Fall back to `description_long` or `description_short`
3. Append `-# (error rendering template)` to the output

### Example Templates

```jinja
{# Base object prototype - renders description #}
{{ e.description_long or e.description_short or "You see nothing special." }}

{# Custom on_look with name reference #}
You examine the {{ name }}. {{ e.description_long }}

{# Conditional template #}
{% if e.description_long %}{{ e.description_long }}{% else %}Nothing special about this {{ name }}.{% endif %}
```

### Template Cache

- Compiled templates are cached in memory by source string
- Cache lives for the bot's lifetime
- No TTL needed (entity definitions are static)

### Side Effects (Scripting)

Templates can trigger side effects that execute after the ephemeral response is sent. Currently supported:

**`effects.pickup()`** - Signals that an item should be picked up (used in `on_take` handlers).

```jinja
{# Pickable item - calls pickup() to move to inventory #}
{{ effects.pickup() }}You pick up the {{ name }}.
```

If `pickup()` is not called in the `on_take` handler, the item stays in the room and only the message is shown. Quest items (`rarity=quest`) clone on pickup - the original stays in the room.

**`effects.drop()`** - Signals that an item should be dropped (used in `on_drop` handlers).

```jinja
{# Droppable item #}
{{ effects.drop() }}You drop the {{ name }}.
```

If `drop()` is not called in the `on_drop` handler, the item stays in inventory.

**`effects.broadcast(message)`** - Sends a public message to the channel after the ephemeral response.

```jinja
{# Record player that announces to the room #}
{{ effects.broadcast("**" ~ user.name ~ "** put on some music.") }}You slide the record onto the turntable. Music fills the room.
```

Result:
- **Ephemeral to user**: "You slide the record onto the turntable. Music fills the room."
- **Public to channel**: "**Frizzle** put on some music."

**`effects.destroy()`** - Signals that this entity instance should be destroyed after the response.

```jinja
{# Smashable vase that destroys itself and grants loot #}
{{ effects.destroy() }}{{ effects.broadcast("**" ~ user.name ~ "** smashes the " ~ name ~ "!") }}You smash the {{ name }}! Shards scatter everywhere.{{ effects.grant_random("loot") }}
```

Result:
- **Ephemeral to user**: "You smash the Flower Vase! Shards scatter everywhere."
- **Public to channel**: "**Frizzle** smashes the *Flower Vase*!"
- Entity instance is deleted from the database
- If paired with a spawning pool, the entity will respawn

**`effects.set_focus()`** - Signals that focus should be set on this entity (used in `on_open` or `on_use` handlers for containers).

```jinja
{# Container that establishes focus when opened #}
{{ effects.set_focus() }}You open the {{ name }}.{% if e.contents %} Inside:{{ e.contents }}{% else %} It's empty.{% endif %}
```

Result:
- User's focus is set to this entity
- Autocomplete now shows only this entity's contents plus "close" option
- Focus persists until `clear_focus()` or room movement

**`effects.clear_focus()`** - Signals that user focus should be cleared (used in `on_close` handlers).

```jinja
{# Container close handler #}
{{ effects.clear_focus() }}You close the {{ name }}.
```

Result:
- User's focus is cleared
- Autocomplete returns to showing room entities

All effect functions return an empty string, allowing inline use without affecting output.

**Implementation:**
- `EffectsCollector` wraps an Observer and provides the template-facing `effects` API
- `ActionCommand.execute()` creates the `ActionContext` and renders the template
- `Scene.execute()` maps signals to entity mutations after rendering
- Entity mutations emit model events to all attached observers
- `scene.flush_observers()` processes deferred Discord operations
