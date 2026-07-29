# MUDD: Multi User Dungeon (Discord)

[![codecov](https://codecov.io/github/frizzle-chan/mudd/graph/badge.svg?token=JM8BYHR8I4)](https://codecov.io/github/frizzle-chan/mudd)

## Commands

- `/ping` - Check bot latency
- `/look` - View the current room's description and entities
- `/look at:<entity>` - Examine a specific entity in the room
- `/move <destination>` - Move to another room (exits listed in current room's topic)
- `/interact with:<entity> action:<verb>` - Interact with an entity (e.g., smash, touch, take)
- `/pay to:<player> amount:<number>` - Give currency to another player in the same room

## Health checks

The bot serves `GET /healthz` on port 8080 (override with `HEALTH_PORT`). It
returns 200 once the Discord gateway is connected, the whitelisted guild is
reachable, the database answers, and the initial world sync has loaded rooms —
otherwise 503 with a JSON body naming the failing check:

```console
$ curl -s localhost:8080/healthz | jq
{
  "status": "ok",
  "commit": "9f2c1ab...",
  "checks": {
    "discord":  { "ok": true, "detail": "connected as mudd#0001, heartbeat 42ms" },
    "guild":    { "ok": true, "detail": "The Mansion (123456789)" },
    "database": { "ok": true, "detail": "connection pool responsive" },
    "world":    { "ok": true, "detail": "78 rooms loaded" }
  }
}
```

The container image wires this to its `HEALTHCHECK`, and CI boots the built
image against a real Postgres and Discord guild to confirm it comes up healthy
before the image is considered good. See `CLAUDE.md` for the required
`SMOKE_DISCORD_TOKEN` / `SMOKE_GUILD_ID` secrets.
