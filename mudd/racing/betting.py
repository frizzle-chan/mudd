"""Betting logic for horse races.

Race projections (ActiveRace, RaceHorseInfo) and formatting utilities
for the horse racing betting system.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import asyncpg

from mudd.racing.persistence import RaceStatus

if TYPE_CHECKING:
    from mudd.models.bet import PayoutRecord

MIN_BET = 5


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
    """Horse info for betting display."""

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


def format_payout_message(payouts: list[PayoutRecord]) -> str:
    """Format betting results for posting to the race thread."""
    if not payouts:
        return ""

    winners = [p for p in payouts if p.payout > 0]
    losers = [p for p in payouts if p.payout == 0]

    lines: list[str] = ["### Betting Results\n"]

    if winners:
        lines.append("Winners:")
        for p in winners:
            lines.append(
                f"💹 <@{p.user_id}> bet ¥{p.amount_bet:,} on "
                f"**{p.horse_name}** and won **¥{p.payout:,}**!"
            )

    if losers:
        lines.append("Losers:")
        for p in losers:
            lines.append(
                f"🔻 <@{p.user_id}> bet ¥{p.amount_bet:,} on "
                f"**{p.horse_name}** and lost."
            )

    return "\n".join(lines)
