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

## Consequences

### Positive

- Clear location semantics with database-enforced constraints
- Flexible spawn behavior per entity type
- Cascade delete: user deletion automatically cleans up their inventory
- Partial indexes optimize both room and inventory queries

### Negative

- Nullable `room` column complicates queries (must filter `WHERE room IS NOT NULL` for room lookups)
- spawn_mode doesn't inherit, requiring explicit configuration on takeable entities

### Future Considerations

- Inventory capacity limits (not implemented in this schema)
- Item stacking for identical entities
- Trading between players
- Lua scripting for complex take handlers
