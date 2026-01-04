# DESIGN.md

Technical design documentation for MUDD.

## Redis Schema

Redis is the source of truth for user locations. Discord channel permissions are derived from Redis state during:
- Bot startup (syncs all users)
- Movement commands
- User join/leave events

| Key | Type | Value | Example |
|-----|------|-------|---------|
| `user:{user_id}:location` | String | Discord channel ID | `user:123456789:location` → `"987654321"` |

## PostgreSQL Schema

PostgreSQL stores the static entity system data for interactable objects in rooms.

### entity_models

Stores entity definitions with resolved prototype inheritance.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | TEXT | PRIMARY KEY | Entity ID (e.g., "vase", "table") |
| `model` | JSONB | NOT NULL | Entity properties including all resolved fields from prototype chain |
| `created_at` | TIMESTAMP | DEFAULT NOW() | When the entity model was created |
| `updated_at` | TIMESTAMP | DEFAULT NOW() | When the entity model was last updated |

### entity_instances

Stores entity placements in rooms using the flyweight pattern.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | SERIAL | PRIMARY KEY | Auto-incrementing instance ID |
| `model_id` | TEXT | NOT NULL, REFERENCES entity_models(id) | Reference to entity model |
| `room_name` | TEXT | NOT NULL | Logical room name (e.g., "tavern", "foyer") |
| `params` | JSONB | NULL | Instance-specific parameters (optional overrides) |
| `created_at` | TIMESTAMP | DEFAULT NOW() | When the instance was placed |
| `updated_at` | TIMESTAMP | DEFAULT NOW() | When the instance was last updated |

### Indexes

- `idx_entity_instances_room` on `entity_instances(room_name)` - Fast lookups of all entities in a room
- `idx_entity_instances_model` on `entity_instances(model_id)` - Fast lookups by entity type

