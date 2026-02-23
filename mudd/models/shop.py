"""Shop model with pricing logic and database access methods."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

import asyncpg

from mudd.utils.text import Rarity

if TYPE_CHECKING:
    from mudd.models.entity import EntityInstance

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
    def _from_row(cls, row: asyncpg.Record) -> Shop:
        """Construct Shop from asyncpg.Record."""
        return cls(
            id=row["id"],
            name=row["name"],
            preferred_tag=row["preferred_tag"],
            sell_spread=row["sell_spread"],
            restock_tag=row["restock_tag"],
            restock_interval_minutes=row["restock_interval_minutes"],
            last_restock_at=row["last_restock_at"],
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
        return [
            cls(
                id=r["id"],
                name=r["name"],
                preferred_tag=r["preferred_tag"],
                sell_spread=r["sell_spread"],
                restock_tag=r["restock_tag"],
                restock_interval_minutes=r["restock_interval_minutes"],
                last_restock_at=r["last_restock_at"],
                _pool=pool,
            )
            for r in rows
        ]

    async def try_restock(self, now: datetime) -> EntityInstance | None:
        """Attempt to restock one item. Returns instance or None."""
        from mudd.models.entity import EntityInstance, ResolvedEntity

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
