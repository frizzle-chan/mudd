"""Unit tests for format_shop_overview()."""

from __future__ import annotations

from datetime import UTC, datetime

from mudd.models.shop import Shop, StockItem, purchase_price
from mudd.observers.shop import format_shop_overview
from mudd.utils.text import Rarity

# Shared timestamp for stock items
_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _make_stock(
    entity_id: str,
    name: str,
    rarity: Rarity = Rarity.COMMON,
    tags: tuple[str, ...] = (),
    stocked_at: datetime = _NOW,
) -> StockItem:
    """Build a StockItem for testing."""
    from uuid import uuid4

    return StockItem(
        entity_instance_id=uuid4(),
        entity_id=entity_id,
        name=name,
        rarity=rarity,
        tags=tags,
        stocked_at=stocked_at,
    )


def _make_shop(
    shop_id: str = "test-shop",
    name: str = "Test Shop",
    preferred_tag: str | None = None,
    sell_spread: float = 0.5,
) -> Shop:
    """Build a Shop for testing."""
    return Shop(
        id=shop_id,
        name=name,
        preferred_tag=preferred_tag,
        sell_spread=sell_spread,
        restock_tag=None,
        restock_interval_minutes=60,
        last_restock_at=None,
    )


class TestFormatShopOverview:
    def test_empty_stock(self):
        shop = _make_shop(name="Empty Shop")
        result = format_shop_overview(shop, [], speech_level=1)
        assert "# Empty Shop" in result
        assert "The shelves are empty." in result
        assert "Use `/sell` to sell items." in result

    def test_single_item(self):
        shop = _make_shop(name="General Store")
        stock = [_make_stock("sword", "Iron Sword", rarity=Rarity.COMMON)]
        result = format_shop_overview(shop, stock, speech_level=1)

        assert "# General Store" in result
        assert "**For Sale:**" in result
        emoji = Rarity.COMMON.emoji
        price = purchase_price(Rarity.COMMON, 1, 1)
        assert f"- Iron Sword {emoji} -- \u00a4{price:,}" in result
        assert "Use `/buy` to purchase or `/sell` to sell items." in result

    def test_grouped_duplicates(self):
        shop = _make_shop(name="Fish Market")
        stock = [
            _make_stock("goldfish", "Goldfish", rarity=Rarity.COMMON),
            _make_stock("goldfish", "Goldfish", rarity=Rarity.COMMON),
            _make_stock("goldfish", "Goldfish", rarity=Rarity.COMMON),
        ]
        result = format_shop_overview(shop, stock, speech_level=1)

        emoji = Rarity.COMMON.emoji
        price = purchase_price(Rarity.COMMON, 3, 1)
        assert f"- Goldfish {emoji} x3 -- \u00a4{price:,}" in result

    def test_multiple_items_different_rarity(self):
        shop = _make_shop(name="Mixed Shop")
        stock = [
            _make_stock("common_item", "Common Item", rarity=Rarity.COMMON),
            _make_stock("rare_item", "Rare Item", rarity=Rarity.RARE),
        ]
        result = format_shop_overview(shop, stock, speech_level=1)

        assert "Common Item" in result
        assert "Rare Item" in result
        assert Rarity.COMMON.emoji in result
        assert Rarity.RARE.emoji in result

    def test_preferred_tag_display(self):
        shop = _make_shop(name="Fish Market", preferred_tag="fish")
        stock = [
            _make_stock("goldfish", "Goldfish", rarity=Rarity.COMMON, tags=("fish",)),
            _make_stock("sword", "Sword", rarity=Rarity.COMMON, tags=("weapon",)),
        ]
        result = format_shop_overview(shop, stock, speech_level=1)

        assert "*Specializes in **fish** items*" in result
        # Fish item should have star emoji
        lines = result.split("\n")
        goldfish_line = next(line for line in lines if "Goldfish" in line)
        sword_line = next(line for line in lines if "Sword" in line)
        assert "\u2b50" in goldfish_line
        assert "\u2b50" not in sword_line

    def test_speech_level_affects_prices(self):
        shop = _make_shop()
        stock = [_make_stock("item", "Item", rarity=Rarity.RARE)]

        result_low = format_shop_overview(shop, stock, speech_level=1)
        result_high = format_shop_overview(shop, stock, speech_level=99)

        # Extract prices from output
        price_low = purchase_price(Rarity.RARE, 1, 1)
        price_high = purchase_price(Rarity.RARE, 1, 99)
        assert f"\u00a4{price_low:,}" in result_low
        assert f"\u00a4{price_high:,}" in result_high
        assert price_high < price_low

    def test_no_preferred_tag_header(self):
        shop = _make_shop(preferred_tag=None)
        stock = [_make_stock("item", "Item")]
        result = format_shop_overview(shop, stock, speech_level=1)

        assert "Specializes" not in result
