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
| `name` | TEXT | Display name for the entity |
| `prototype_id` | TEXT (FK) | Reference to parent entity for prototypical inheritance |
| `description_short` | TEXT | Brief description with {name} template support |
| `description_long` | TEXT | Detailed description with {name} template support |
| `on_look` | TEXT | Handler response for look action (NULL = inherit from prototype) |
| `on_touch` | TEXT | Handler response for touch action (NULL = inherit from prototype) |
| `on_attack` | TEXT | Handler response for attack action (NULL = inherit from prototype) |
| `on_use` | TEXT | Handler response for use action (NULL = inherit from prototype) |
| `on_take` | TEXT | Handler response for take action (NULL = inherit from prototype) |
| `container_id` | TEXT (FK) | Reference to containing entity |
| `contents_visible` | BOOLEAN | Whether child entities are visible (NULL = inherit, TRUE = show in room, FALSE = show when examined) |

**Constraints:**
- Self-reference prevention: `id != prototype_id`
- Self-containment prevention: `id != container_id`

**Indexes:**
- Primary key on `id`
- GIN index on `name` using pg_trgm for fuzzy matching
- Index on `prototype_id` for inheritance queries

### Entity Instances Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Auto-generated unique instance identifier |
| `entity_id` | TEXT (FK) | Reference to entity definition |
| `room` | TEXT | Logical room name where instance exists |
| `created_at` | TIMESTAMPTZ | Instance creation timestamp |

**Indexes:**
- Primary key on `id`
- Index on `room` for room-based queries

### Entity Inheritance

The `resolve_entity(target_id TEXT)` function resolves entity properties by walking up the prototype chain:
- Returns merged properties where child values override parent values
- First non-NULL value wins for each property
- Supports up to 10 levels of inheritance depth
- Used to materialize the final entity state including inherited properties

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
