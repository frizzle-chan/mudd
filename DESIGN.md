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
| `current_location` | TEXT | Logical room name (e.g., "tavern") |
| `created_at` | TIMESTAMPTZ | When the record was created |
| `updated_at` | TIMESTAMPTZ | When the record was last modified |

**Indexes:**
- Primary key on `id`
- Index on `current_location` for room-based queries

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
| `description_short` | TEXT | Brief description with {name} template support |
| `description_long` | TEXT | Detailed description with {name} template support |
| `on_look` | TEXT | Handler response for look action (NULL = inherit from prototype) |
| `on_touch` | TEXT | Handler response for touch action (NULL = inherit from prototype) |
| `on_attack` | TEXT | Handler response for attack action (NULL = inherit from prototype) |
| `on_use` | TEXT | Handler response for use action (NULL = inherit from prototype) |
| `on_take` | TEXT | Handler response for take action (NULL = inherit from prototype) |
| `container_id` | TEXT (FK to entities.id) | Reference to containing entity |
| `contents_visible` | BOOLEAN | Whether child entities are visible (NULL = inherit from prototype, TRUE = show in room, FALSE = show when examined) |
| `spawn_mode` | spawn_mode NOT NULL | Take behavior: `none` (can't take), `move` (one-time pickup), `clone` (infinite copies) |

**Constraints:**
- Self-reference prevention: `id != prototype_id`
- Self-containment prevention: `id != container_id`

**Spawn Mode Enum:**
- `none`: Static decoration, cannot be taken (default)
- `move`: One-time pickup, instance moves from room to inventory
- `clone`: Infinite source, each take creates a new instance in inventory

**Indexes:**
- Primary key on `id`
- GIN index on `name` using pg_trgm for fuzzy matching
- Index on `prototype_id` for inheritance queries

### Entity Instances Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Auto-generated unique instance identifier |
| `entity_id` | TEXT NOT NULL (FK to entities.id) | Reference to entity definition |
| `room` | TEXT | Logical room name (NULL when in inventory) |
| `owner_id` | BIGINT (FK to users.id) | Player who owns this instance (NULL when in room) |
| `created_at` | TIMESTAMPTZ NOT NULL | Instance creation timestamp |

**Constraints:**
- Mutual exclusivity: `(room IS NOT NULL AND owner_id IS NULL) OR (room IS NULL AND owner_id IS NOT NULL)`
- Foreign key cascade: Deleting a user cascades to their inventory items

**Indexes:**
- Primary key on `id`
- Partial index on `room` (WHERE room IS NOT NULL) for room-based queries
- Partial index on `owner_id` (WHERE owner_id IS NOT NULL) for inventory queries

### Verbs Table

| Column | Type | Description |
|--------|------|-------------|
| `verb` | TEXT (PK) | The verb word (e.g., 'smash', 'look') |
| `action` | verb_action NOT NULL | The action handler type to invoke |

**Verb Action Enum:** `on_look`, `on_touch`, `on_attack`, `on_use`, `on_take`

**Indexes:**
- Primary key on `verb`
- GIN index on `verb` using pg_trgm for fuzzy matching (typo tolerance)

**Data Source:**
- Verbs are loaded from `data/verbs/*.txt` files on bot startup
- Each file contains one verb per line, mapped to the action matching the filename
- Full sync on startup: verbs not in files are removed from the database

### Rooms Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT (PK) | Logical room name, matches Discord channel name |
| `name` | TEXT NOT NULL | Display name for the room |
| `description` | TEXT NOT NULL | Room description (can be synced to Discord channel topic) |

**Data Source:**
- Rooms are defined in `data/worlds/<world>/*.rec` files
- Each room file contains a `Room` record and its entities
- Room connections are implicit via Discord channel mentions in descriptions (e.g., `#hallway`)

### Entity Inheritance

The `resolve_entity(target_id TEXT)` function resolves entity properties by walking up the prototype chain:
- Returns merged properties where child values override parent values
- First non-NULL value wins for each property (except `spawn_mode` which is always from the entity itself)
- Supports up to 10 levels of inheritance depth (prevents infinite loops from circular references)
- Used to materialize the final entity state including inherited properties
- Returns: `id`, `name`, `description_short`, `description_long`, `on_*` handlers, `contents_visible`, `spawn_mode`

## Room Abstraction

User locations are stored as logical room names (e.g., "tavern", "office") rather than Discord channel IDs. This provides:
- Readable database values
- Portability across Discord servers
- Alignment with entity system design

**Room name resolution:**
- At startup, build an in-memory cache mapping room names to channel IDs
- Room names are derived from Discord channel names in the world category
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

The `sync_guild()` method ensures Discord channel permissions match database state. It runs:
- **On startup**: Once per guild via the `Sync` cog's first task iteration, followed by `mark_startup_complete()`
- **Periodically**: Every 15 minutes via the `Sync` cog's background task
- **Future**: Can be triggered by Discord events (channel changes, role updates, etc.)

Commands wait for `wait_for_startup()` before executing to ensure the initial sync completes first.
