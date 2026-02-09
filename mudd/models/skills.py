"""Skills model with database access methods."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import asyncpg

from mudd.skills.registry import Skill
from mudd.skills.xp import MAX_XP, level_for_xp

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class XPResult:
    """Result of an XP grant operation."""

    skill: Skill
    old_level: int
    new_level: int
    old_xp: int
    new_xp: int

    @property
    def leveled_up(self) -> bool:
        """Whether the user gained at least one level."""
        return self.new_level > self.old_level

    @property
    def levels_gained(self) -> int:
        """Number of levels gained from this XP grant."""
        return self.new_level - self.old_level


@dataclass(frozen=True, slots=True)
class UserSkill:
    """A user's progress in a single skill."""

    user_id: int
    skill: str
    xp: int
    level: int

    @classmethod
    async def get_all(cls, pool: asyncpg.Pool, user_id: int) -> list[UserSkill]:
        """Get all skills for a user.

        Args:
            pool: Database connection pool
            user_id: Discord user ID

        Returns:
            List of UserSkill instances for all registered skills
        """
        rows = await pool.fetch(
            """SELECT user_id, skill, xp, level
               FROM user_skills
               WHERE user_id = $1
               ORDER BY skill""",
            user_id,
        )
        return [
            cls(
                user_id=row["user_id"],
                skill=row["skill"],
                xp=row["xp"],
                level=row["level"],
            )
            for row in rows
        ]

    @classmethod
    async def get(
        cls, pool: asyncpg.Pool, user_id: int, skill: str
    ) -> UserSkill | None:
        """Get a single skill for a user.

        Args:
            pool: Database connection pool
            user_id: Discord user ID
            skill: Skill name

        Returns:
            UserSkill instance, or None if not found
        """
        row = await pool.fetchrow(
            """SELECT user_id, skill, xp, level
               FROM user_skills
               WHERE user_id = $1 AND skill = $2""",
            user_id,
            skill,
        )
        if row is None:
            return None
        return cls(
            user_id=row["user_id"],
            skill=row["skill"],
            xp=row["xp"],
            level=row["level"],
        )

    @classmethod
    async def grant_xp(
        cls, pool: asyncpg.Pool, user_id: int, skill: str, amount: int
    ) -> XPResult:
        """Grant XP to a user's skill, updating level atomically.

        Clamps total XP to MAX_XP. Recalculates level from the new XP value.

        Args:
            pool: Database connection pool
            user_id: Discord user ID
            skill: Skill name
            amount: Amount of XP to grant (must be positive)

        Returns:
            XPResult with before/after state
        """
        if amount <= 0:
            raise ValueError(f"XP amount must be positive, got {amount}")

        async with pool.acquire() as conn, conn.transaction():
            # Lock the row to prevent concurrent read-then-write races
            row = await conn.fetchrow(
                """SELECT xp, level FROM user_skills
                   WHERE user_id = $1 AND skill = $2
                   FOR UPDATE""",
                user_id,
                skill,
            )
            assert row is not None  # Skill rows created at user creation time

            old_xp = int(row["xp"])
            old_level = int(row["level"])
            new_xp = min(old_xp + amount, MAX_XP)
            new_level = level_for_xp(new_xp)

            await conn.execute(
                """UPDATE user_skills
                   SET xp = $3, level = $4
                   WHERE user_id = $1 AND skill = $2""",
                user_id,
                skill,
                new_xp,
                new_level,
            )

        logger.info(
            "Granted %d XP to user %d skill %s: %d->%d XP, level %d->%d",
            amount,
            user_id,
            skill,
            old_xp,
            new_xp,
            old_level,
            new_level,
        )

        return XPResult(
            skill=Skill(skill),
            old_level=old_level,
            new_level=new_level,
            old_xp=old_xp,
            new_xp=new_xp,
        )

    @classmethod
    async def create_defaults(cls, pool: asyncpg.Pool, user_id: int) -> None:
        """Insert missing skill rows at level 1 for all registered skills.

        Args:
            pool: Database connection pool
            user_id: Discord user ID
        """
        skill_names = [str(s) for s in Skill]
        await pool.execute(
            """INSERT INTO user_skills (user_id, skill, xp, level)
               SELECT $1, unnest($2::text[]), 0, 1
               ON CONFLICT (user_id, skill) DO NOTHING""",
            user_id,
            skill_names,
        )
