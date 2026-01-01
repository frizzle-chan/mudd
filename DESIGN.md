# DESIGN.md

Technical design documentation for MUDD.

## Redis Schema

Redis is used exclusively for persisting user locations (which channel/room each player is in).

### Connection

- **Client**: `redis.asyncio` with connection pooling
- **URL**: `REDIS_URL` env var (default: `redis://localhost:6379`)
- **Decode**: Responses decoded as strings

### Key Patterns

| Key | Type | Value | Example |
|-----|------|-------|---------|
| `user:{user_id}:location` | String | Discord channel ID | `user:123456789:location` → `"987654321"` |

### Operations

| Operation | Method | Usage |
|-----------|--------|-------|
| GET | `client.get(key)` | Retrieve user's current location |
| SET | `client.set(key, value)` | Store user's new location |
| DELETE | `client.delete(key)` | Remove user when they leave server |

### Data Lifecycle

- **No TTL**: Locations persist indefinitely
- **Creation**: User joins server or moves to a room
- **Update**: User moves to a different room
- **Deletion**: User leaves the Discord server

### Source of Truth

Redis is the source of truth for user locations. Discord channel permissions are derived from Redis state during:
- Bot startup (syncs all users)
- Movement commands
- User join/leave events
