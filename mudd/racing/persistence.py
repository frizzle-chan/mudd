"""Database operations for race lifecycle.

Async functions for persisting races and maintaining rolling counters.
"""

from __future__ import annotations

import json

import asyncpg

from mudd.racing.odds import HorseOdds
from mudd.racing.simulation import RaceResult


async def create_race(
    pool: asyncpg.Pool,
    result: RaceResult,
    odds: list[HorseOdds],
) -> int:
    """Persist a completed race and its results.

    Single transaction: inserts the race row with JSONB columns, then
    batch-inserts race_results using unnest().

    Returns:
        The new race ID.
    """
    horses_json = json.dumps(result.horse_ids)
    snapshots_json = json.dumps(result.snapshots)
    events_json = json.dumps(
        [
            {
                "tick": e.tick,
                "horse_index": e.horse_index,
                "type": str(e.burst_type),
            }
            for e in result.events
        ]
    )
    finishing_order_json = json.dumps(result.finishing_order)
    odds_json = json.dumps(
        [
            {
                "horse_id": o.horse_id,
                "displayed_payout": o.displayed_payout,
                "true_probability": o.true_probability,
                "star_rating": o.star_rating,
            }
            for o in odds
        ]
    )

    async with pool.acquire() as conn, conn.transaction():
        race_id: int = await conn.fetchval(
            """INSERT INTO races
                   (status, horses, snapshots, events, finishing_order,
                    odds_snapshot, started_at, finished_at)
               VALUES ('finished', $1::jsonb, $2::jsonb, $3::jsonb, $4::jsonb,
                       $5::jsonb, NOW(), NOW())
               RETURNING id""",
            horses_json,
            snapshots_json,
            events_json,
            finishing_order_json,
            odds_json,
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
