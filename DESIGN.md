# DESIGN.md

Technical design documentation for MUDD.

## Valkey Schema

Valkey is the source of truth for user locations. Discord channel permissions are derived from Valkey state during:
- Bot startup (syncs all users)
- Movement commands
- User join/leave events

| Key | Type | Value | Example |
|-----|------|-------|---------|
| `user:{user_id}:location` | String | Discord channel ID | `user:123456789:location` → `"987654321"` |

