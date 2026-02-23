"""Shop model with pricing logic and database access methods."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

import asyncpg

from mudd.models.entity import EntityInstance, ResolvedEntity
from mudd.models.zone import SyncStats
from mudd.utils.text import Rarity

if TYPE_CHECKING:
    from mudd.loaders.zone_loader import ShopData

logger = logging.getLogger(__name__)

# Rarity base prices benchmarked against existing currency bundles.
# "none" and "quest" items are non-tradeable (price 0).
RARITY_BASE_PRICES: dict[Rarity, int] = {
    "none": 0,
    "common": 100,
    "uncommon": 1_000,
    "rare": 5_000,
    "epic": 25_000,
    "legendary": 100_000,
    "mythic": 500_000,
    "quest": 0,
}


def base_price(rarity: Rarity) -> int:
    """Return the base price for a rarity tier."""
    return RARITY_BASE_PRICES[rarity]


def supply_adjustment(stock_count: int) -> float:
    """Hyperbolic decay based on duplicate count in the shop.

    count 1: 1.0x (baseline)
    count 5: ~0.71x
    count 10: ~0.53x
    count 20: ~0.34x
    """
    return 1.0 / (1.0 + 0.1 * max(0, stock_count - 1))


def dynamic_price(rarity: Rarity, stock_count: int) -> int:
    """Base price adjusted by supply. Truncated to int."""
    return int(base_price(rarity) * supply_adjustment(stock_count))


def purchase_price(rarity: Rarity, stock_count: int, speech_level: int) -> int:
    """Price a player pays to buy an item.

    Speech discount: 0% at level 1, 15% at level 99.
    """
    price = dynamic_price(rarity, stock_count)
    discount = 0.15 * (speech_level - 1) / 98
    return int(price * (1.0 - discount))


def sale_price(
    rarity: Rarity,
    stock_count: int,
    speech_level: int,
    sell_spread: float,
    has_preferred_tag: bool,
) -> int:
    """Price a player receives when selling an item to a shop.

    Speech bonus: 0% at level 1, 25% at level 99.
    Preferred tag multiplier: 1.5x when item has the shop's preferred_tag.
    Floor: never below 25% of base price.
    """
    price = dynamic_price(rarity, stock_count)
    bonus = 0.25 * (speech_level - 1) / 98
    result = price * sell_spread * (1.0 + bonus)
    if has_preferred_tag:
        result *= 1.5
    floor = base_price(rarity) * 0.25
    return int(max(result, floor))


@dataclass(frozen=True)
class Shop:
    """A merchant shop that players can buy from and sell to."""

    id: str
    name: str
    preferred_tag: str | None
    sell_spread: float
    restock_tag: str | None
    restock_interval_minutes: int
    last_restock_at: datetime | None
    _pool: asyncpg.Pool | None = field(repr=False, compare=False, default=None)

    @classmethod
    def _from_row(
        cls, row: asyncpg.Record, *, pool: asyncpg.Pool | None = None
    ) -> Shop:
        """Construct Shop from asyncpg.Record."""
        return cls(
            id=row["id"],
            name=row["name"],
            preferred_tag=row["preferred_tag"],
            sell_spread=row["sell_spread"],
            restock_tag=row["restock_tag"],
            restock_interval_minutes=row["restock_interval_minutes"],
            last_restock_at=row["last_restock_at"],
            _pool=pool,
        )

    @property
    def effective_restock_tag(self) -> str | None:
        """Restock tag with fallback to preferred_tag."""
        return self.restock_tag or self.preferred_tag

    def can_restock(self, now: datetime) -> bool:
        """Check if shop is due for a restock (interval elapsed, has tag)."""
        if not self.effective_restock_tag:
            return False
        if self.last_restock_at is None:
            return True
        elapsed = (now - self.last_restock_at).total_seconds() / 60
        return elapsed >= self.restock_interval_minutes

    @classmethod
    async def get_all_due_for_restock(
        cls, pool: asyncpg.Pool, now: datetime
    ) -> list[Shop]:
        """Fetch all shops that are due for restocking.

        Args:
            pool: Database connection pool
            now: Current UTC timestamp

        Returns:
            List of Shop instances ready to restock
        """
        rows = await pool.fetch(
            """
            SELECT * FROM shops
            WHERE COALESCE(restock_tag, preferred_tag) IS NOT NULL
              AND (last_restock_at IS NULL
                   OR last_restock_at
                      + make_interval(mins => restock_interval_minutes) <= $1)
            """,
            now,
        )
        return [cls._from_row(r, pool=pool) for r in rows]

    async def try_restock(self, now: datetime) -> EntityInstance | None:
        """Attempt to restock one item. Returns instance or None."""
        if self._pool is None:
            return None

        if not self.can_restock(now):
            return None

        tag = self.effective_restock_tag
        assert tag is not None  # guaranteed by can_restock

        entity = await ResolvedEntity.get_weighted_random_by_tag(self._pool, tag)
        if entity is None:
            return None

        instance = await EntityInstance.create(self._pool, entity.id)
        if instance is None:
            return None

        await Shop.add_to_stock(self._pool, self.id, instance.instance_id)

        await self._pool.execute(
            "UPDATE shops SET last_restock_at = $1 WHERE id = $2",
            now,
            self.id,
        )

        return instance

    @classmethod
    async def get(cls, pool: asyncpg.Pool, shop_id: str) -> Shop | None:
        """Fetch a shop by ID.

        Args:
            pool: Database connection pool
            shop_id: The shop ID to look up

        Returns:
            Shop instance, or None if not found
        """
        row = await pool.fetchrow("SELECT * FROM shops WHERE id = $1", shop_id)
        if row is None:
            return None
        return cls._from_row(row)

    @classmethod
    async def sync_all(cls, pool: asyncpg.Pool, shops: list[ShopData]) -> SyncStats:
        """Bulk sync shops from rec file data.

        Preserves last_restock_at timestamps for existing shops.

        Args:
            pool: Database connection pool
            shops: List of ShopData from rec files

        Returns:
            SyncStats with synced and deleted counts
        """
        deleted = 0

        if not shops:
            async with pool.acquire() as conn:
                result = await conn.execute("DELETE FROM shops")
                if result.startswith("DELETE "):
                    deleted = int(result.split()[1])
            return SyncStats(synced=0, deleted=deleted)

        shop_ids = [s.id for s in shops]

        async with pool.acquire() as conn, conn.transaction():
            # Delete shops not in current files
            result = await conn.execute(
                "DELETE FROM shops WHERE id != ALL($1::text[])",
                shop_ids,
            )
            if result.startswith("DELETE "):
                deleted = int(result.split()[1])

            # Upsert shops (preserve last_restock_at)
            await conn.executemany(
                """INSERT INTO shops (
                    id, name, preferred_tag, sell_spread,
                    restock_tag, restock_interval_minutes
                ) VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (id) DO UPDATE SET
                    name = $2,
                    preferred_tag = $3,
                    sell_spread = $4,
                    restock_tag = $5,
                    restock_interval_minutes = $6
                """,
                [
                    (
                        s.id,
                        s.name,
                        s.preferred_tag,
                        s.sell_spread,
                        s.restock_tag,
                        s.restock_interval_minutes,
                    )
                    for s in shops
                ],
            )

        logger.info(f"Synced {len(shops)} shops")
        return SyncStats(synced=len(shops), deleted=deleted)

    @classmethod
    async def get_stock(cls, pool: asyncpg.Pool, shop_id: str) -> list[StockItem]:
        """Fetch all stock items for a shop with resolved entity data.

        Args:
            pool: Database connection pool
            shop_id: The shop to query stock for

        Returns:
            List of StockItem ordered by stocked_at
        """
        rows = await pool.fetch(
            """
            SELECT ss.entity_instance_id, ss.stocked_at,
                   ei.entity_id,
                   r.name, r.rarity,
                   ARRAY(
                       SELECT tag FROM entity_tags WHERE entity_id = ei.entity_id
                   ) AS tags
            FROM shop_stock ss
            JOIN entity_instances ei ON ei.id = ss.entity_instance_id
            CROSS JOIN LATERAL resolve_entity(ei.entity_id) r
            WHERE ss.shop_id = $1
            ORDER BY ss.stocked_at
            """,
            shop_id,
        )
        return [StockItem._from_row(row) for row in rows]

    @classmethod
    async def add_to_stock(
        cls, pool: asyncpg.Pool, shop_id: str, entity_instance_id: UUID
    ) -> None:
        """Add an entity instance to a shop's stock.

        Args:
            pool: Database connection pool
            shop_id: The shop to add stock to
            entity_instance_id: The entity instance to stock
        """
        await pool.execute(
            "INSERT INTO shop_stock (shop_id, entity_instance_id) VALUES ($1, $2)",
            shop_id,
            entity_instance_id,
        )

    @classmethod
    async def remove_from_stock(
        cls, pool: asyncpg.Pool, entity_instance_id: UUID
    ) -> None:
        """Remove an entity instance from shop stock.

        Args:
            pool: Database connection pool
            entity_instance_id: The entity instance to remove
        """
        await pool.execute(
            "DELETE FROM shop_stock WHERE entity_instance_id = $1",
            entity_instance_id,
        )


async def get_tags_for_entities(
    pool: asyncpg.Pool, entity_ids: list[str]
) -> dict[str, set[str]]:
    """Batch-fetch tags for multiple entity IDs.

    Args:
        pool: Database connection pool
        entity_ids: Entity definition IDs to look up

    Returns:
        Mapping of entity_id to set of tags (missing IDs have empty sets)
    """
    if not entity_ids:
        return {}
    rows = await pool.fetch(
        "SELECT entity_id, tag FROM entity_tags WHERE entity_id = ANY($1::text[])",
        entity_ids,
    )
    result: dict[str, set[str]] = {}
    for row in rows:
        result.setdefault(row["entity_id"], set()).add(row["tag"])
    return result


@dataclass(frozen=True, slots=True)
class StockItem:
    """An entity instance stocked in a shop."""

    entity_instance_id: UUID
    entity_id: str
    name: str
    rarity: Rarity
    tags: tuple[str, ...]
    stocked_at: datetime

    @classmethod
    def _from_row(cls, row: asyncpg.Record) -> StockItem:
        """Construct StockItem from asyncpg.Record."""
        return cls(
            entity_instance_id=row["entity_instance_id"],
            entity_id=row["entity_id"],
            name=row["name"],
            rarity=row["rarity"],
            tags=tuple(row["tags"]),
            stocked_at=row["stocked_at"],
        )


@dataclass(frozen=True, slots=True)
class TradingSession:
    """An active trading session between a user and a shop."""

    user_id: int
    shop_id: str
    thread_id: int
    created_at: datetime

    @classmethod
    def _from_row(cls, row: asyncpg.Record) -> TradingSession:
        """Construct TradingSession from asyncpg.Record."""
        return cls(
            user_id=row["user_id"],
            shop_id=row["shop_id"],
            thread_id=row["thread_id"],
            created_at=row["created_at"],
        )

    @classmethod
    async def get(cls, pool: asyncpg.Pool, user_id: int) -> TradingSession | None:
        """Fetch the active trading session for a user.

        Args:
            pool: Database connection pool
            user_id: The user to look up

        Returns:
            TradingSession instance, or None if no active session
        """
        row = await pool.fetchrow(
            "SELECT * FROM user_trading_sessions WHERE user_id = $1",
            user_id,
        )
        if row is None:
            return None
        return cls._from_row(row)

    @classmethod
    async def create(
        cls,
        pool: asyncpg.Pool,
        user_id: int,
        shop_id: str,
        thread_id: int,
    ) -> TradingSession:
        """Create a new trading session.

        Callers must end any existing session first.

        Args:
            pool: Database connection pool
            user_id: The user starting the session
            shop_id: The shop being traded with
            thread_id: Discord thread for this session

        Returns:
            The newly created TradingSession
        """
        row = await pool.fetchrow(
            """
            INSERT INTO user_trading_sessions (user_id, shop_id, thread_id)
            VALUES ($1, $2, $3)
            RETURNING *
            """,
            user_id,
            shop_id,
            thread_id,
        )
        assert row is not None
        return cls._from_row(row)

    @classmethod
    async def delete(cls, pool: asyncpg.Pool, user_id: int) -> TradingSession | None:
        """Delete the active trading session for a user.

        Returns the deleted session so callers can emit
        TradingSessionEndedEvent with the thread_id. No-op if no
        session exists.

        Args:
            pool: Database connection pool
            user_id: The user whose session to end

        Returns:
            The deleted TradingSession, or None if no session existed
        """
        row = await pool.fetchrow(
            "DELETE FROM user_trading_sessions WHERE user_id = $1 RETURNING *",
            user_id,
        )
        if row is None:
            return None
        return cls._from_row(row)
