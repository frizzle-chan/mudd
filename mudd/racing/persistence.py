"""Database operations for race lifecycle.

Async functions for persisting races and maintaining rolling counters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

import asyncpg

from mudd.racing.odds import HorseOdds
from mudd.racing.simulation import RaceResult


class MessageType(StrEnum):
    """PostgreSQL race_message_type enum."""

    ANNOUNCEMENT = "announcement"
    THREAD = "thread"
    RACE_START = "race_start"
    POLL = "poll"


class RaceStatus(StrEnum):
    """PostgreSQL race_status enum."""

    OPEN = "open"
    LOCKED = "locked"
    ANNOUNCING = "announcing"
    RUNNING = "running"
    FINISHED = "finished"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class PendingMessage:
    """A race message ready to be posted to Discord."""

    id: int
    race_id: int
    sequence: int
    message_type: MessageType
    content: str | None
    image_data: bytes | None
    image_name: str | None
    channel_id: int | None
    thread_id: int | None
    poll: dict[str, Any] | None


async def create_race(
    pool: asyncpg.Pool,
    result: RaceResult,
    odds: list[HorseOdds],
    *,
    status: RaceStatus = RaceStatus.FINISHED,
    channel_id: int | None = None,
) -> int:
    """Persist a race and its results.

    Args:
        pool: Database connection pool.
        result: Simulation output.
        odds: Odds at race time.
        status: Race status (default 'finished' for backward compat).
        channel_id: Discord channel ID for live races.

    Returns:
        The new race ID.
    """
    horses_data = result.horse_ids
    snapshots_data = result.snapshots
    events_data = [
        {
            "tick": e.tick,
            "horse_index": e.horse_index,
            "type": str(e.burst_type),
        }
        for e in result.events
    ]
    finishing_order_data = result.finishing_order
    odds_data = [
        {
            "horse_id": o.horse_id,
            "displayed_payout": o.displayed_payout,
            "true_probability": o.true_probability,
            "star_rating": o.star_rating,
        }
        for o in odds
    ]

    finished_at = "NOW()" if status == RaceStatus.FINISHED else "NULL"

    async with pool.acquire() as conn, conn.transaction():
        race_id: int = await conn.fetchval(
            f"""INSERT INTO races
                   (status, horses, snapshots, events, finishing_order,
                    odds_snapshot, started_at, finished_at, channel_id)
               VALUES ($1::race_status, $2::jsonb, $3::jsonb, $4::jsonb, $5::jsonb,
                       $6::jsonb, NOW(), {finished_at}, $7)
               RETURNING id""",
            status,
            horses_data,
            snapshots_data,
            events_data,
            finishing_order_data,
            odds_data,
            channel_id,
        )

        # Batch insert race_results using unnest
        horse_ids: list[str] = []
        positions: list[int] = []
        race_ids: list[int] = []
        for rank, horse_index in enumerate(result.finishing_order):
            horse_ids.append(result.horse_ids[horse_index])
            positions.append(rank + 1)
            race_ids.append(race_id)

        await conn.execute(
            """INSERT INTO race_results (race_id, horse_id, position)
               SELECT * FROM unnest($1::int[], $2::text[], $3::int[])""",
            race_ids,
            horse_ids,
            positions,
        )

    return race_id


@dataclass(frozen=True, slots=True)
class RaceMessageInput:
    """Input for a single race message to enqueue."""

    sequence: int
    message_type: MessageType
    content: str | None
    image_data: bytes | None
    image_name: str | None
    post_at: datetime
    poll: dict[str, Any] | None = None


async def create_race_messages(
    pool: asyncpg.Pool,
    race_id: int,
    messages: list[RaceMessageInput],
) -> None:
    """Batch insert pre-computed race messages.

    Uses unnest() for efficient bulk insert.
    """
    race_ids = [race_id] * len(messages)
    sequences = [m.sequence for m in messages]
    types = [m.message_type for m in messages]
    contents = [m.content for m in messages]
    image_datas = [m.image_data for m in messages]
    image_names = [m.image_name for m in messages]
    post_ats = [m.post_at for m in messages]
    polls = [m.poll for m in messages]

    await pool.execute(
        """INSERT INTO race_messages
               (race_id, sequence, message_type, content,
                image_data, image_name, post_at, poll)
           SELECT * FROM unnest(
               $1::int[], $2::int[],
               $3::race_message_type[], $4::text[],
               $5::bytea[], $6::text[], $7::timestamptz[],
               $8::jsonb[]
           )""",
        race_ids,
        sequences,
        types,
        contents,
        image_datas,
        image_names,
        post_ats,
        polls,
    )


async def fetch_pending_messages(pool: asyncpg.Pool) -> list[PendingMessage]:
    """Fetch all race messages due for posting.

    Returns messages ordered by race_id and sequence.
    """
    rows = await pool.fetch(
        """SELECT rm.id, rm.race_id, rm.sequence, rm.message_type,
                  rm.content, rm.image_data, rm.image_name,
                  rm.poll, r.channel_id, r.thread_id
           FROM race_messages rm
           JOIN races r ON rm.race_id = r.id
           WHERE rm.post_at <= NOW()
           ORDER BY rm.race_id, rm.sequence"""
    )
    return [
        PendingMessage(
            id=row["id"],
            race_id=row["race_id"],
            sequence=row["sequence"],
            message_type=row["message_type"],
            content=row["content"],
            image_data=row["image_data"],
            image_name=row["image_name"],
            channel_id=row["channel_id"],
            thread_id=row["thread_id"],
            poll=row["poll"],
        )
        for row in rows
    ]


async def delete_message(pool: asyncpg.Pool, message_id: int) -> None:
    """Delete a race message after successful posting."""
    await pool.execute("DELETE FROM race_messages WHERE id = $1", message_id)


async def set_race_thread(pool: asyncpg.Pool, race_id: int, thread_id: int) -> None:
    """Store the Discord thread ID for a race."""
    await pool.execute(
        "UPDATE races SET thread_id = $1 WHERE id = $2", thread_id, race_id
    )


async def finish_race(pool: asyncpg.Pool, race_id: int) -> None:
    """Mark a race as finished after all messages have been posted."""
    await pool.execute(
        "UPDATE races SET status = 'finished', finished_at = NOW() WHERE id = $1",
        race_id,
    )


async def get_remaining_message_count(pool: asyncpg.Pool, race_id: int) -> int:
    """Get count of remaining unposted messages for a race."""
    count: int = await pool.fetchval(
        "SELECT COUNT(*) FROM race_messages WHERE race_id = $1", race_id
    )
    return count


async def has_active_race(pool: asyncpg.Pool) -> bool:
    """Check if there is an active (non-finished) race."""
    row = await pool.fetchval(
        "SELECT 1 FROM races"
        " WHERE status IN ('open', 'locked', 'announcing', 'running')"
        " LIMIT 1"
    )
    return row is not None


async def update_rolling_counters(pool: asyncpg.Pool, rolling_window: int = 20) -> None:
    """Recompute rolling-window counters for all horses from race_results.

    Uses a single batch UPDATE with a CTE that computes counts from the
    last N race_results per horse. No N+1 queries.
    """
    await pool.execute(
        """
        WITH recent AS (
            SELECT horse_id, position,
                   ROW_NUMBER() OVER (
                       PARTITION BY horse_id ORDER BY created_at DESC
                   ) AS rn
            FROM race_results
        ),
        counts AS (
            SELECT horse_id,
                   COUNT(*)::int AS recent_races,
                   COUNT(*) FILTER (WHERE position = 1)::int AS recent_wins,
                   COUNT(*) FILTER (WHERE position <= 3)::int AS recent_places
            FROM recent
            WHERE rn <= $1
            GROUP BY horse_id
        )
        UPDATE horses h
        SET recent_races = COALESCE(c.recent_races, 0),
            recent_wins  = COALESCE(c.recent_wins, 0),
            recent_places = COALESCE(c.recent_places, 0)
        FROM (
            SELECT h2.id AS horse_id,
                   c2.recent_races, c2.recent_wins, c2.recent_places
            FROM horses h2
            LEFT JOIN counts c2 ON c2.horse_id = h2.id
        ) c
        WHERE h.id = c.horse_id
        """,
        rolling_window,
    )


async def transition_to_running(pool: asyncpg.Pool, race_id: int) -> None:
    """Transition a race from announcing to running."""
    await pool.execute(
        "UPDATE races SET status = 'running', started_at = NOW()"
        " WHERE id = $1 AND status = 'announcing'",
        race_id,
    )


async def set_scheduled_event_id(
    pool: asyncpg.Pool, race_id: int, event_id: int
) -> None:
    """Store the Discord scheduled event ID for a race."""
    await pool.execute(
        "UPDATE races SET scheduled_event_id = $1 WHERE id = $2", event_id, race_id
    )


async def get_scheduled_event_id(pool: asyncpg.Pool, race_id: int) -> int | None:
    """Get the Discord scheduled event ID for a race."""
    return await pool.fetchval(
        "SELECT scheduled_event_id FROM races WHERE id = $1", race_id
    )


async def set_poll_message_id(
    pool: asyncpg.Pool, race_id: int, message_id: int
) -> None:
    """Store the Discord poll message ID for a race."""
    await pool.execute(
        "UPDATE races SET poll_message_id = $1 WHERE id = $2", message_id, race_id
    )


async def get_poll_message_id(pool: asyncpg.Pool, race_id: int) -> int | None:
    """Get the Discord poll message ID for a race."""
    return await pool.fetchval(
        "SELECT poll_message_id FROM races WHERE id = $1", race_id
    )


async def get_race_thread_id(pool: asyncpg.Pool, race_id: int) -> int | None:
    """Get the Discord thread ID for a race."""
    return await pool.fetchval("SELECT thread_id FROM races WHERE id = $1", race_id)


async def get_recent_results(
    pool: asyncpg.Pool, horse_ids: list[str], limit: int = 5
) -> dict[str, list[int]]:
    """Get recent finishing positions for the given horses.

    Returns:
        Mapping of horse_id to list of positions, newest first.
    """
    rows = await pool.fetch(
        """
        SELECT horse_id, position
        FROM (
            SELECT horse_id, position, created_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY horse_id ORDER BY created_at DESC
                   ) AS rn
            FROM race_results
            WHERE horse_id = ANY($1::text[])
        ) sub
        WHERE rn <= $2
        ORDER BY horse_id, created_at DESC
        """,
        horse_ids,
        limit,
    )

    results: dict[str, list[int]] = {hid: [] for hid in horse_ids}
    for row in rows:
        results[row["horse_id"]].append(row["position"])
    return results


async def get_race_winner(pool: asyncpg.Pool, race_id: int) -> str | None:
    """Return the winner horse ID for a finished race, or None."""
    row = await pool.fetchrow(
        "SELECT finishing_order, horses FROM races WHERE id = $1",
        race_id,
    )
    if row is None:
        return None
    finishing_order = row["finishing_order"]
    horse_ids = row["horses"]
    return horse_ids[finishing_order[0]]
