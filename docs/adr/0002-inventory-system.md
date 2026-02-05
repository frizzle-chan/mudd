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

In the context of **tracking item ownership**, facing **the need to know whether an entity instance is in a room or in a player's inventory**, we decided to **use a mutual exclusivity constraint on location fields**, to achieve **clear location semantics where an instance is always in exactly one place**, accepting **nullable columns with a CHECK constraint for validation**.

An instance is always in exactly one location: either a room or a player's inventory, never both, never neither.

### Pickup Behavior

> **Note:** This section is superseded by ADR 0004. Pickup behavior is now controlled by effect functions called from `on_take` handlers.

**Current behavior:**
- Items call a pickup effect function in their handler to be picked up
- Quest items are cloned on pickup (original stays in room)
- Static decorations don't call the pickup effect and cannot be taken

### Discord Representation

In the context of **displaying player inventories in Discord**, facing **the need for visual representation that maintains fog-of-war (players only see their own items)**, we decided to **use per-user forum channels with item threads**, to achieve **private viewing and thread-based item examination**, accepting **one forum channel per user and thread ID tracking in the database**.

Key design points:
- A dedicated category is created and hidden from everyone by default
- Each user gets their own forum channel for inventory
- Each inventory item becomes a thread in the user's forum
- Only the item owner can view their forum channel

### Permission Model

In the context of **inventory forum access control**, facing **the need to enforce fog-of-war while allowing item examination**, we decided to **grant users limited permissions on their forum only**, to achieve **private inventory viewing with the ability to interact in item threads**, accepting **that users cannot create threads manually (only the bot manages threads)**.

Users can view their forum and read/send messages in item threads, but cannot create new threads or post in the forum root.

### Discord Thread Tracking

In the context of **managing inventory item threads**, facing **the need to update or delete threads when items change**, we decided to **store thread IDs on entity instances**, to achieve **direct mapping between database instances and Discord threads**, accepting **nullable columns for instances not yet synced to Discord**.

The database tracks the relationship between inventory forums, users, and item threads to enable efficient sync and cleanup operations.

### Sync Recovery for Duplicate Forums

In the context of **database resets or data loss**, facing **the scenario where Discord channels persist but the database loses track of them**, we decided to **search Discord by expected forum name before creating new forums**, to achieve **automatic recovery of existing forums and prevention of duplicates**, accepting **a small performance cost during sync**.

Recovery behavior:
- Before creating a forum, search for existing forums matching the expected name
- If found, keep the oldest forum, delete any duplicates
- Update the database to track the recovered forum

### Forum Name Encoding

In the context of **inventory forum naming**, facing **Discord normalizing channel names to lowercase (which can break uniqueness schemes)**, we decided to **use an encoding scheme that avoids normalization issues**, to achieve **unique forum names that Discord won't mangle**, accepting **names that are not human-readable**.

### Thread Pruning

In the context of **maintaining inventory thread consistency**, facing **orphan threads that don't correspond to actual inventory items**, we decided to **prune orphan threads during sync**, to achieve **clean inventory forums without stale threads**, accepting **automatic deletion of threads not tracked in the database**.

Orphan threads can result from:
- Database reset while Discord threads persist
- Manual thread creation by users (if permissions somehow allow)
- Failed item deletions that removed database record but not Discord thread

## Consequences

### Positive

- Clear location semantics with database-enforced constraints
- Cascade delete: user deletion automatically cleans up their inventory
- Per-user forum channels maintain fog-of-war for inventories
- Thread-based items enable detailed examination and future interaction
- Permission sync repairs drifted Discord state automatically
- Sync recovery prevents duplicate forums after database reset
- Thread pruning keeps inventory forums clean of stale threads

### Negative

- Nullable location columns complicate queries (must filter for room-based or inventory-based lookups)
- One forum channel per user increases Discord resource usage
- Thread ID tracking requires database updates on item creation/deletion
- Thread pruning deletes threads not tracked in database (no recovery for manually created threads)

### Future Considerations

- Inventory capacity limits
- Item stacking for identical entities
- Trading between players
- Scripting for complex take handlers
- Item examination via thread interactions
- Inventory forum cleanup for inactive users
