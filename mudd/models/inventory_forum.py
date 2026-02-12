"""UserInventoryForum model for the user_inventory_forums table."""

from __future__ import annotations

import asyncpg


class UserInventoryForum:
    """Lightweight model for the user_inventory_forums table.

    Provides classmethods for CRUD operations on forum/category mappings.
    """

    @classmethod
    async def get_forum_id(cls, pool: asyncpg.Pool, user_id: int) -> int | None:
        """Get the forum channel ID for a user's inventory forum.

        Args:
            pool: Database connection pool
            user_id: Discord user ID

        Returns:
            Forum channel ID, or None if no forum exists
        """
        row = await pool.fetchrow(
            "SELECT forum_id FROM user_inventory_forums WHERE user_id = $1",
            user_id,
        )
        return row["forum_id"] if row else None

    @classmethod
    async def delete_by_user(cls, pool: asyncpg.Pool, user_id: int) -> None:
        """Delete the inventory forum record for a user.

        Args:
            pool: Database connection pool
            user_id: Discord user ID
        """
        await pool.execute(
            "DELETE FROM user_inventory_forums WHERE user_id = $1",
            user_id,
        )

    @classmethod
    async def get_all_forum_ids(cls, pool: asyncpg.Pool) -> set[int]:
        """Get all tracked inventory forum IDs.

        Args:
            pool: Database connection pool

        Returns:
            Set of forum channel IDs
        """
        rows = await pool.fetch("SELECT forum_id FROM user_inventory_forums")
        return {row["forum_id"] for row in rows}

    @classmethod
    async def create_or_update(
        cls,
        pool: asyncpg.Pool,
        user_id: int,
        forum_id: int,
        category_id: int,
    ) -> None:
        """Insert or update the inventory forum record for a user.

        Args:
            pool: Database connection pool
            user_id: Discord user ID
            forum_id: Discord forum channel ID
            category_id: Discord category channel ID
        """
        await pool.execute(
            """
            INSERT INTO user_inventory_forums (user_id, forum_id, category_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE SET forum_id = $2, category_id = $3
            """,
            user_id,
            forum_id,
            category_id,
        )
