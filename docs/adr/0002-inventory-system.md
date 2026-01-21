# ADR 0002: Inventory System

## Status

Proposed

## Context

MUDD needs a system for players to pick up and carry items. The existing entity system supports static world objects, but lacks:

- Player ownership of entity instances
- Location tracking for items in inventories vs. rooms
- Configurable behavior when players take items (one-time pickup vs. infinite source)

## Decisions

### Inventory Storage

In the context of **tracking item ownership**, facing **the need to know whether an entity instance is in a room or in a player's inventory**, we decided to **add an `owner_id` column to `entity_instances` with a mutual exclusivity constraint**, to achieve **a single table for all entity instances with clear location semantics**, accepting **nullable columns with a CHECK constraint for validation**.

The constraint ensures: `(room IS NOT NULL AND owner_id IS NULL) OR (room IS NULL AND owner_id IS NOT NULL)`

This means an instance is always in exactly one place: either a room or a player's inventory.

### Spawn Mode

In the context of **item pickup behavior**, facing **the need for different take behaviors (static decorations, one-time pickups, infinite sources)**, we decided to **add a `spawn_mode` enum to `entities`**, to achieve **per-entity configuration of take behavior**, accepting **a non-nullable column that doesn't inherit from prototypes**.

Spawn modes:
- `none`: Static decoration, cannot be taken (default)
- `move`: One-time pickup, instance moves from room to inventory
- `clone`: Infinite source, each take creates a new instance in inventory

### No Inheritance for spawn_mode

In the context of **spawn mode resolution**, facing **whether spawn_mode should inherit from prototypes**, we decided to **always use the entity's own spawn_mode (no inheritance)**, to achieve **explicit and predictable take behavior per entity**, accepting **that child entities must set their own spawn_mode if they want different behavior than the default**.

### Discord Representation

In the context of **displaying player inventories in Discord**, facing **the need for visual representation that maintains fog-of-war (players only see their own items)**, we decided to **use per-user forum channels with item threads**, to achieve **private viewing and thread-based item examination**, accepting **one forum channel per user and thread ID tracking in the database**.

Key implementation details:
- A dedicated "Inventory" category is created and hidden from @everyone
- Each user gets a forum channel named `{base62_user_id}-inventory`
- Each inventory item becomes a thread in the user's forum (thread name is the item name)
- Only the owner can view their forum channel

### Permission Model

In the context of **inventory forum access control**, facing **the need to enforce fog-of-war while allowing item examination**, we decided to **grant users view and send_messages_in_threads permissions on their forum only**, to achieve **private inventory viewing with the ability to interact in item threads**, accepting **that users cannot create threads or post in the forum root (only the bot manages threads)**.

Permission setup:
- Category: @everyone denied view_channel
- User forum: Owner gets view_channel + send_messages_in_threads
- User forum: Owner denied create_public_threads + send_messages (cannot post in forum root)
- Forum sync repairs any drifted permissions during periodic sync

### Discord Thread Tracking

In the context of **managing inventory item threads**, facing **the need to update or delete threads when items change**, we decided to **store `discord_thread_id` on `entity_instances`**, to achieve **direct mapping between database instances and Discord threads**, accepting **nullable column for instances not yet synced to Discord**.

Database additions:
- `user_inventory_forums` table: `user_id` (PK), `forum_id`, `category_id`
- `discord_thread_id` column on `entity_instances` (nullable BIGINT)
- Foreign key from forums to users with cascade delete (user deletion cleans up forum record)

## Consequences

### Positive

- Clear location semantics with database-enforced constraints
- Flexible spawn behavior per entity type
- Cascade delete: user deletion automatically cleans up their inventory
- Partial indexes optimize both room and inventory queries
- Per-user forum channels maintain fog-of-war for inventories
- Thread-based items enable detailed examination and future interaction
- Permission sync repairs drifted Discord state automatically

### Negative

- Nullable `room` column complicates queries (must filter `WHERE room IS NOT NULL` for room lookups)
- spawn_mode doesn't inherit, requiring explicit configuration on takeable entities
- One forum channel per user increases Discord resource usage
- Thread ID tracking requires database updates on item creation/deletion

### Future Considerations

- Inventory capacity limits (not implemented in this schema)
- Item stacking for identical entities
- Trading between players
- Lua scripting for complex take handlers
- Item examination via thread interactions (posting in item threads)
- Inventory forum cleanup for inactive users
