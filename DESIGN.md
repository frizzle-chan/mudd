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

**Indexes:**
- Primary key on `id`
- Index on `zone_id` for zone-based queries

**Data Source:**
- Rooms are defined in `data/worlds/*.rec` files as `Room` records
- Each room has a Zone field referencing its parent zone
- Room connections are implicit via Discord channel mentions in descriptions (e.g., `#hallway`)
- Synced to database on bot startup; bot creates missing Discord channels
- `IsDefault` field in rec files marks the default spawn room (not stored in DB, used at load time only)

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

### Entity Inheritance

The `resolve_entity(target_id TEXT)` function resolves entity properties by walking up the prototype chain:
- Returns merged properties where child values override parent values
- First non-NULL value wins for each property (except `spawn_mode` which is always from the entity itself)
- Supports up to 10 levels of inheritance depth (prevents infinite loops from circular references)
- Used to materialize the final entity state including inherited properties
- Returns: `id`, `name`, `description_short`, `description_long`, `on_*` handlers, `contents_visible`, `spawn_mode`

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
    ├─ init_visibility_service(default_room)
    │
    ├─ visibility_service.sync_guild()
    │    ├─ Build room cache
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
