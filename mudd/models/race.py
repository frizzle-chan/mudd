"""Race model — status enum and data-access objects for active races."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import asyncpg


class RaceStatus(StrEnum):
    """PostgreSQL race_status enum."""

    OPEN = "open"
    LOCKED = "locked"
    ANNOUNCING = "announcing"
    RUNNING = "running"
    FINISHED = "finished"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ActiveRace:
    """Lightweight projection of an active race."""

    id: int
    status: RaceStatus

    def is_announcing(self) -> bool:
        return self.status == RaceStatus.ANNOUNCING

    @classmethod
    async def get(cls, pool: asyncpg.Pool) -> ActiveRace | None:
        """Return the active race (ANNOUNCING or RUNNING), if any."""
        row = await pool.fetchrow(
            "SELECT id, status FROM races"
            " WHERE status IN ('announcing', 'running')"
            " ORDER BY id DESC LIMIT 1"
        )
        if row is None:
            return None
        return cls(id=row["id"], status=RaceStatus(row["status"]))


@dataclass(frozen=True, slots=True)
class RaceHorseInfo:
    """Horse info for betting display (from odds_snapshot)."""

    id: str
    name: str
    displayed_payout: float

    @classmethod
    async def get_for_race(
        cls, pool: asyncpg.Pool, race_id: int
    ) -> list[RaceHorseInfo]:
        """Get horses in a race with display names and odds from odds_snapshot."""
        rows = await pool.fetch(
            """
            SELECT e.value->>'horse_id' AS horse_id,
                   h.name,
                   (e.value->>'displayed_payout')::float AS displayed_payout
            FROM races r,
                 jsonb_array_elements(r.odds_snapshot) AS e(value)
            JOIN horses h ON h.id = e.value->>'horse_id'
            WHERE r.id = $1
            ORDER BY h.name
            """,
            race_id,
        )
        return [
            cls(
                id=row["horse_id"],
                name=row["name"],
                displayed_payout=row["displayed_payout"],
            )
            for row in rows
        ]
