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

### Pickup Behavior (Superseded)

> **Note:** The original `spawn_mode` enum has been superseded by `effects.pickup()` in ADR 0004. Pickup behavior is now controlled by whether the `on_take` template calls `effects.pickup()`, with quest items (`rarity=quest`) automatically cloning on pickup.

Original decision (now superseded):

In the context of **item pickup behavior**, facing **the need for different take behaviors (static decorations, one-time pickups, infinite sources)**, we decided to **add a `spawn_mode` enum to `entities`**, to achieve **per-entity configuration of take behavior**, accepting **a non-nullable column that doesn't inherit from prototypes**.

**Current behavior:**
- Items call `effects.pickup()` in their `on_take` handler to be picked up
- Quest items (`rarity=quest`) are cloned on pickup (original stays in room)
- Static decorations don't call `effects.pickup()` and cannot be taken

### Discord Representation

In the context of **displaying player inventories in Discord**, facing **the need for visual representation that maintains fog-of-war (players only see their own items)**, we decided to **use per-user forum channels with item threads**, to achieve **private viewing and thread-based item examination**, accepting **one forum channel per user and thread ID tracking in the database**.

Key implementation details:
- A dedicated "Inventory" category is created and hidden from @everyone
- Each user gets a forum channel named `{braille_user_id}-inventory`
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

### Sync Recovery for Duplicate Forums

In the context of **database resets or data loss**, facing **the scenario where Discord channels persist but DB loses track of them**, we decided to **search Discord by expected forum name before creating new forums**, to achieve **automatic recovery of existing forums and prevention of duplicates**, accepting **a small performance cost during sync to search for existing forums**.

Recovery behavior:
- Before creating a forum, search the Inventory category for forums matching `{braille_user_id}-inventory`
- If found, keep the oldest forum (smallest Discord ID), delete any duplicates
- Update DB to track the recovered forum
- Log "Recovered existing inventory forum" to distinguish from new creations

This mirrors the duplicate detection pattern used in zone/room channel sync (`zone_loader.py`).

### Forum Name Encoding

In the context of **inventory forum naming**, facing **Discord normalizing channel names to lowercase (breaking base62 uniqueness) and alphanumeric names being visually distracting**, we decided to **use Braille patterns (U+2800-U+28FF) for base256 encoding of user IDs**, to achieve **shorter names (8 chars vs 11) that are visually unobtrusive**, accepting **names that are not human-readable**.

Encoding details:
- Each byte of the user ID maps to one Braille pattern character
- 64-bit user IDs encode to 8 characters maximum
- Names look like `⠁⠃⣿⠙⡑⢋⠛⠓-inventory`
- Discord does not normalize Braille characters, avoiding the case-collision issue

Migration from legacy base62:
- Sync detects forums with old base62 names and renames them to Braille
- Both DB-tracked and orphaned legacy forums are migrated
- Migration is logged as "Migrated forum name" with old and new names

### Thread Pruning

In the context of **maintaining inventory thread consistency**, facing **orphan threads that don't correspond to actual inventory items**, we decided to **prune orphan threads during sync**, to achieve **clean inventory forums without stale threads**, accepting **automatic deletion of threads not tracked in the database**.

Orphan threads can result from:
- DB reset while Discord threads persist
- Manual thread creation by users (if permissions somehow allow)
- Failed item deletions that removed DB record but not Discord thread

Pruning behavior:
- During `sync_user_forums()`, query `entity_instances` for valid thread IDs
- Delete any forum threads whose ID is not in the valid set
- Log "Pruned orphan thread" with thread name and ID

## Consequences

### Positive

- Clear location semantics with database-enforced constraints
- Flexible spawn behavior per entity type
- Cascade delete: user deletion automatically cleans up their inventory
- Partial indexes optimize both room and inventory queries
- Per-user forum channels maintain fog-of-war for inventories
- Thread-based items enable detailed examination and future interaction
- Permission sync repairs drifted Discord state automatically
- Sync recovery prevents duplicate forums after DB reset
- Thread pruning keeps inventory forums clean of stale threads

### Negative

- Nullable `room` column complicates queries (must filter `WHERE room IS NOT NULL` for room lookups)
- One forum channel per user increases Discord resource usage
- Thread ID tracking requires database updates on item creation/deletion
- Thread pruning deletes threads not tracked in DB (no recovery for manually created threads)

### Future Considerations

- Inventory capacity limits (not implemented in this schema)
- Item stacking for identical entities
- Trading between players
- Lua scripting for complex take handlers
- Item examination via thread interactions (posting in item threads)
- Inventory forum cleanup for inactive users
