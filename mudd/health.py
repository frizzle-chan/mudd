"""HTTP health endpoint for liveness and readiness probes.

The bot has no request/response surface of its own — it holds a gateway
websocket open and reacts to events — so a wedged or half-started bot looks
identical to a healthy one from the outside. This module exposes a single
``GET /healthz`` reporting the four conditions that must *all* hold for the
bot to actually serve players:

- ``discord``: the gateway is connected and heartbeating
- ``guild``: the whitelisted guild is in cache (otherwise sync silently no-ops)
- ``database``: the connection pool answers a trivial query
- ``world``: the initial world sync finished and rooms exist in the database

Returns 200 when every check passes, 503 otherwise, with a JSON body naming
the failing check. Wired to the container ``HEALTHCHECK`` and polled by the
boot smoke test in ``.github/workflows/docker.yaml``.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import asyncpg
from aiohttp import web

from mudd.models import Room
from mudd.version import get_git_commit

if TYPE_CHECKING:
    from mudd.bot import MuddBot

logger = logging.getLogger(__name__)

# Binds all interfaces so the port can be published from a container; the
# endpoint is read-only and exposes no player data.
DEFAULT_HEALTH_HOST = "0.0.0.0"
DEFAULT_HEALTH_PORT = 8080

HEALTHY_STATUS = "ok"
UNHEALTHY_STATUS = "unhealthy"

# Probes back a container healthcheck with a short timeout; a database that
# takes longer than this to answer is already failing for players.
PROBE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class HealthCheck:
    """Outcome of a single readiness probe."""

    name: str
    ok: bool
    detail: str


@dataclass(slots=True)
class HealthState:
    """Startup progress that only the bot itself can observe.

    Owned by `MuddBot` and updated by the Sync cog as the world sync
    succeeds or fails. Everything else in `/healthz` is probed live.
    """

    first_sync_completed: bool = False
    last_sync_error: str | None = None

    def mark_sync_succeeded(self) -> None:
        """Record a completed sync, clearing any previous failure."""
        self.first_sync_completed = True
        self.last_sync_error = None

    def mark_sync_failed(self, error: BaseException) -> None:
        """Record a sync failure so `/healthz` reports the cause."""
        self.last_sync_error = f"{type(error).__name__}: {error}"


def build_payload(checks: Sequence[HealthCheck], commit: str) -> dict[str, Any]:
    """Build the `/healthz` JSON body from probe results."""
    return {
        "status": HEALTHY_STATUS if all(c.ok for c in checks) else UNHEALTHY_STATUS,
        "commit": commit,
        "checks": {c.name: {"ok": c.ok, "detail": c.detail} for c in checks},
    }


def status_code_for(payload: dict[str, Any]) -> int:
    """Map a health payload to its HTTP status code."""
    return 200 if payload["status"] == HEALTHY_STATUS else 503


def probe_discord(bot: MuddBot) -> HealthCheck:
    """Check that the gateway connection is live and heartbeating."""
    if bot.is_closed():
        return HealthCheck("discord", False, "gateway connection is closed")
    if not bot.is_ready():
        return HealthCheck("discord", False, "waiting for gateway READY")
    latency = bot.latency
    if math.isnan(latency):
        return HealthCheck("discord", False, "no gateway heartbeat recorded yet")
    return HealthCheck(
        "discord", True, f"connected as {bot.user}, heartbeat {latency * 1000:.0f}ms"
    )


def probe_guild(bot: MuddBot) -> HealthCheck:
    """Check that the whitelisted guild is reachable.

    Sync skips its Discord half when the guild is missing, so a bot that is
    logged in but not a member of `GUILD_ID` looks fine in the logs while
    doing nothing at all.
    """
    guild = bot.get_guild(bot.guild_id)
    if guild is None:
        return HealthCheck(
            "guild",
            False,
            f"guild {bot.guild_id} unavailable — is the bot a member?",
        )
    return HealthCheck("guild", True, f"{guild.name} ({guild.id})")


async def probe_database(pool: asyncpg.Pool) -> HealthCheck:
    """Check that the connection pool can serve a query."""
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS), pool.acquire() as conn:
            await conn.execute("SELECT 1")
    # A probe reports failure, never raises — an unhandled error here would
    # take down the endpoint that is supposed to diagnose it.
    except Exception as exc:  # noqa: BLE001
        return HealthCheck("database", False, f"{type(exc).__name__}: {exc}")
    return HealthCheck("database", True, "connection pool responsive")


async def probe_world(pool: asyncpg.Pool, state: HealthState) -> HealthCheck:
    """Check that the initial world sync ran and actually loaded rooms."""
    if state.last_sync_error is not None:
        return HealthCheck("world", False, f"sync failed: {state.last_sync_error}")
    if not state.first_sync_completed:
        return HealthCheck("world", False, "initial world sync has not finished")
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            room_count = await Room.count(pool)
    except Exception as exc:  # noqa: BLE001 - see probe_database
        return HealthCheck("world", False, f"{type(exc).__name__}: {exc}")
    if room_count == 0:
        return HealthCheck("world", False, "sync completed but no rooms were loaded")
    return HealthCheck("world", True, f"{room_count} rooms loaded")


class HealthServer:
    """aiohttp server exposing `GET /healthz`."""

    def __init__(
        self, bot: MuddBot, pool: asyncpg.Pool, *, host: str, port: int
    ) -> None:
        self._bot = bot
        self._pool = pool
        self._host = host
        self._port = port
        self._runner: web.AppRunner | None = None

    @classmethod
    def from_env(cls, bot: MuddBot, pool: asyncpg.Pool) -> HealthServer:
        """Build a server from `HEALTH_HOST` / `HEALTH_PORT`."""
        return cls(
            bot,
            pool,
            host=os.environ.get("HEALTH_HOST", DEFAULT_HEALTH_HOST),
            port=int(os.environ.get("HEALTH_PORT", DEFAULT_HEALTH_PORT)),
        )

    async def start(self) -> None:
        """Bind the listener. Safe to call before the gateway connects."""
        app = web.Application()
        app.router.add_get("/healthz", self.handle_healthz)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.TCPSite(runner, self._host, self._port).start()
        self._runner = runner
        logger.info(
            "Health endpoint listening on %s:%d/healthz", self._host, self._port
        )

    async def close(self) -> None:
        """Stop the listener. Idempotent."""
        if self._runner is None:
            return
        runner, self._runner = self._runner, None
        await runner.cleanup()
        logger.info("Health endpoint stopped")

    async def handle_healthz(self, request: web.Request) -> web.Response:
        """Run every probe and report the combined result."""
        del request  # probes read bot/pool state, not the request
        checks = [
            probe_discord(self._bot),
            probe_guild(self._bot),
            await probe_database(self._pool),
            await probe_world(self._pool, self._bot.health),
        ]
        payload = build_payload(checks, get_git_commit())
        return web.json_response(payload, status=status_code_for(payload))
