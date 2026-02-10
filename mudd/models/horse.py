"""Horse model with database access methods."""

from __future__ import annotations

from dataclasses import dataclass, field

import asyncpg

from mudd.racing.odds import HorseStats


@dataclass(frozen=True)
class Horse:
    """Horse definition for the racing minigame.

    Horses are immutable and represent a raceable horse with fixed stats.
    Rolling-window counters are updated after each race.
    """

    id: str
    name: str
    speed: int
    stamina: int
    consistency: int
    luck: int
    recent_races: int
    recent_wins: int
    recent_places: int
    active: bool
    profile_image: bytes | None
    race_image: bytes | None
    victory_image: bytes | None
    _pool: asyncpg.Pool = field(repr=False, compare=False)

    def to_stats(self) -> HorseStats:
        """Convert to a lightweight HorseStats projection for odds/simulation."""
        return HorseStats(
            horse_id=self.id,
            speed=self.speed,
            stamina=self.stamina,
            consistency=self.consistency,
            luck=self.luck,
            recent_races=self.recent_races,
            recent_wins=self.recent_wins,
            recent_places=self.recent_places,
        )

    @classmethod
    async def get(cls, pool: asyncpg.Pool, horse_id: str) -> Horse | None:
        """Get a horse by ID.

        Args:
            pool: Database connection pool.
            horse_id: Horse identifier.

        Returns:
            Horse instance or None if not found.
        """
        row = await pool.fetchrow(
            """SELECT id, name, speed, stamina, consistency, luck,
                      recent_races, recent_wins, recent_places, active,
                      profile_image, race_image, victory_image
               FROM horses WHERE id = $1""",
            horse_id,
        )
        if row is None:
            return None
        return cls(
            id=row["id"],
            name=row["name"],
            speed=row["speed"],
            stamina=row["stamina"],
            consistency=row["consistency"],
            luck=row["luck"],
            recent_races=row["recent_races"],
            recent_wins=row["recent_wins"],
            recent_places=row["recent_places"],
            active=row["active"],
            profile_image=row["profile_image"],
            race_image=row["race_image"],
            victory_image=row["victory_image"],
            _pool=pool,
        )

    @classmethod
    async def get_all_active(cls, pool: asyncpg.Pool) -> list[Horse]:
        """Get all active horses, ordered by name.

        Args:
            pool: Database connection pool.

        Returns:
            List of active Horse instances.
        """
        rows = await pool.fetch(
            """SELECT id, name, speed, stamina, consistency, luck,
                      recent_races, recent_wins, recent_places, active,
                      profile_image, race_image, victory_image
               FROM horses WHERE active = TRUE ORDER BY name""",
        )
        return [
            cls(
                id=row["id"],
                name=row["name"],
                speed=row["speed"],
                stamina=row["stamina"],
                consistency=row["consistency"],
                luck=row["luck"],
                recent_races=row["recent_races"],
                recent_wins=row["recent_wins"],
                recent_places=row["recent_places"],
                active=row["active"],
                profile_image=row["profile_image"],
                race_image=row["race_image"],
                victory_image=row["victory_image"],
                _pool=pool,
            )
            for row in rows
        ]
