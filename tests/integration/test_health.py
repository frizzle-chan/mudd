"""Health endpoint tests.

Exercises the real probes and a real aiohttp server against a real database.
Only the Discord gateway is doubled — it is the one dependency a test cannot
drive.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import aiohttp
import asyncpg
import discord
import pytest

from mudd.bot import MuddBot
from mudd.database import run_migrations
from mudd.health import (
    HealthServer,
    HealthState,
    probe_database,
    probe_discord,
    probe_guild,
    probe_world,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


@dataclass(slots=True)
class StubGuild:
    """Test double for discord.Guild."""

    id: int
    name: str


@dataclass
class StubBot:
    """Test double for MuddBot's gateway surface.

    Satisfies the `BotHealthSource` protocol the probes are written against.
    """

    guild_id: int = 4242
    health: HealthState = field(default_factory=HealthState)
    user: object = "mudd#0001"
    ready: bool = False
    closed: bool = False
    heartbeat: float = float("nan")
    guild: StubGuild | None = None

    @property
    def latency(self) -> float:
        return self.heartbeat

    def is_ready(self) -> bool:
        return self.ready

    def is_closed(self) -> bool:
        return self.closed

    def get_guild(self, guild_id: int, /) -> StubGuild | None:
        return self.guild if guild_id == self.guild_id else None


def connected_bot() -> StubBot:
    """A bot double in the fully-healthy gateway state."""
    return StubBot(
        ready=True, heartbeat=0.042, guild=StubGuild(id=4242, name="The Mansion")
    )


def free_port() -> int:
    """Pick an unused localhost port so parallel runs don't collide."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
async def empty_db():
    """A migrated database with no world loaded.

    Covers the case that motivated probing room count instead of trusting
    the sync flag: sync reports success having loaded nothing.
    """
    db_host = os.environ.get("DB_HOST", "db")
    admin_dsn = f"postgresql://mudd:mudd@{db_host}:5432/mudd"
    db_name = f"mudd_health_{uuid4().hex[:8]}"

    admin_conn = await asyncpg.connect(admin_dsn)
    await admin_conn.execute(f"CREATE DATABASE {db_name}")
    await admin_conn.close()

    pool = await asyncpg.create_pool(
        f"postgresql://mudd:mudd@{db_host}:5432/{db_name}", min_size=1, max_size=2
    )
    await run_migrations(pool)

    yield pool

    await pool.close()
    admin_conn = await asyncpg.connect(admin_dsn)
    await admin_conn.execute(f"DROP DATABASE {db_name}")
    await admin_conn.close()


async def get_healthz(port: int) -> tuple[int, dict]:
    """Fetch /healthz over real HTTP."""
    url = f"http://127.0.0.1:{port}/healthz"
    async with aiohttp.ClientSession() as session, session.get(url) as response:
        return response.status, await response.json()


# --- gateway probe ---------------------------------------------------------


async def test_gateway_not_ready_is_unhealthy():
    assert probe_discord(StubBot()).ok is False


async def test_closed_gateway_is_unhealthy():
    bot = connected_bot()
    bot.closed = True

    check = probe_discord(bot)

    assert check.ok is False
    assert "closed" in check.detail


async def test_connected_but_never_heartbeat_is_unhealthy():
    # discord.py reports NaN latency until the first heartbeat lands, which
    # is distinct from "not ready" and would otherwise format as "nanms".
    bot = connected_bot()
    bot.heartbeat = float("nan")

    check = probe_discord(bot)

    assert check.ok is False
    assert "heartbeat" in check.detail


async def test_connected_gateway_is_healthy():
    check = probe_discord(connected_bot())

    assert check.ok is True
    assert "42ms" in check.detail


# --- guild probe -----------------------------------------------------------


async def test_missing_guild_is_unhealthy():
    # Logged in but not a member of GUILD_ID: sync skips its Discord half
    # and the bot does nothing, while the logs look fine.
    check = probe_guild(StubBot(ready=True, heartbeat=0.01, guild=None))

    assert check.ok is False
    assert "4242" in check.detail


async def test_guild_in_cache_is_healthy():
    check = probe_guild(connected_bot())

    assert check.ok is True
    assert "The Mansion" in check.detail


# --- database probe --------------------------------------------------------


async def test_live_pool_is_healthy(test_db):
    assert (await probe_database(test_db)).ok is True


async def test_closed_pool_is_unhealthy():
    db_host = os.environ.get("DB_HOST", "db")
    pool = await asyncpg.create_pool(
        f"postgresql://mudd:mudd@{db_host}:5432/mudd", min_size=1, max_size=2
    )
    await pool.close()

    check = await probe_database(pool)

    assert check.ok is False
    assert "closed" in check.detail.lower()


# --- world probe -----------------------------------------------------------


async def test_world_before_first_sync_is_unhealthy(test_db):
    check = await probe_world(test_db, HealthState())

    assert check.ok is False
    assert "not finished" in check.detail


async def test_world_reports_sync_failure(test_db):
    state = HealthState()
    state.mark_sync_failed(RuntimeError("world file missing"))

    check = await probe_world(test_db, state)

    assert check.ok is False
    assert "world file missing" in check.detail


async def test_world_with_rooms_loaded_is_healthy(test_db):
    state = HealthState()
    state.mark_sync_succeeded()

    check = await probe_world(test_db, state)

    assert check.ok is True
    assert "rooms loaded" in check.detail


async def test_sync_success_with_empty_world_is_unhealthy(empty_db):
    # The regression this endpoint exists to catch: _sync() returns normally
    # when the world file yields no rooms, so the flag alone lies.
    state = HealthState()
    state.mark_sync_succeeded()

    check = await probe_world(empty_db, state)

    assert check.ok is False
    assert "no rooms" in check.detail


# --- server ----------------------------------------------------------------


async def test_server_reports_503_until_every_probe_passes(test_db):
    bot = StubBot()
    port = free_port()
    server = HealthServer(bot, test_db, host="127.0.0.1", port=port)
    await server.start()
    try:
        status, body = await get_healthz(port)
        assert status == 503
        assert body["status"] == "unhealthy"
        # The database is already up, so the body must point at the real cause.
        assert body["checks"]["database"]["ok"] is True
        assert body["checks"]["discord"]["ok"] is False
        assert body["checks"]["world"]["ok"] is False

        bot.ready = True
        bot.heartbeat = 0.042
        bot.guild = StubGuild(id=bot.guild_id, name="The Mansion")
        bot.health.mark_sync_succeeded()

        status, body = await get_healthz(port)
        assert status == 200, body
        assert body["status"] == "ok"
        assert set(body["checks"]) == {"discord", "guild", "database", "world"}
    finally:
        await server.close()


async def test_server_close_is_idempotent_and_releases_the_port(test_db):
    port = free_port()
    server = HealthServer(StubBot(), test_db, host="127.0.0.1", port=port)
    await server.start()

    await server.close()
    await server.close()

    with pytest.raises(aiohttp.ClientConnectorError):
        await get_healthz(port)


async def test_bot_starts_and_stops_its_health_server(test_db, monkeypatch):
    port = free_port()
    monkeypatch.setenv("HEALTH_HOST", "127.0.0.1")
    monkeypatch.setenv("HEALTH_PORT", str(port))
    bot = MuddBot(
        world_file=Path("data/worlds/test_world.rec"),
        guild_id=4242,
        command_prefix=(),
        intents=discord.Intents.default(),
    )

    await bot.start_health_server(test_db)
    status, body = await get_healthz(port)
    assert status == 503
    assert body["checks"]["database"]["ok"] is True

    await bot.close()

    with pytest.raises(aiohttp.ClientConnectorError):
        await get_healthz(port)
