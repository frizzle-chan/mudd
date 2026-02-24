"""Unit tests for shop cog autocomplete helper logic."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from mudd.cogs.shop import format_buy_choices, format_sell_choices
from mudd.models.entity import EntityInstance, ResolvedEntity
from mudd.models.shop import StockItem, sale_price
from mudd.utils.text import Rarity


def _stock_item(
    *,
    entity_id: str = "sword",
    name: str = "Sword",
    rarity: Rarity = Rarity.COMMON,
    instance_id: str | None = None,
) -> StockItem:
    """Build a StockItem for testing."""
    return StockItem(
        entity_instance_id=UUID(instance_id or "00000000-0000-0000-0000-000000000001"),
        entity_id=entity_id,
        name=name,
        rarity=rarity,
        tags=(),
        stocked_at=datetime(2024, 1, 1),
    )


class TestFormatBuyChoices:
    def test_empty_stock_returns_empty(self) -> None:
        assert format_buy_choices([], speech_level=1) == []

    def test_single_item(self) -> None:
        stock = [_stock_item()]
        choices = format_buy_choices(stock, speech_level=1)
        assert len(choices) == 1
        label, value = choices[0]
        assert "Sword" in label
        assert "\u00a4100" in label
        assert value == "00000000-0000-0000-0000-000000000001"

    def test_duplicate_items_grouped(self) -> None:
        stock = [
            _stock_item(instance_id="00000000-0000-0000-0000-000000000001"),
            _stock_item(instance_id="00000000-0000-0000-0000-000000000002"),
            _stock_item(instance_id="00000000-0000-0000-0000-000000000003"),
        ]
        choices = format_buy_choices(stock, speech_level=1)
        # Should group into one entry
        assert len(choices) == 1
        label, value = choices[0]
        assert "Sword" in label
        # Value should be the first instance's ID
        assert value == "00000000-0000-0000-0000-000000000001"

    def test_different_items_separate(self) -> None:
        stock = [
            _stock_item(
                entity_id="sword",
                name="Sword",
                instance_id="00000000-0000-0000-0000-000000000001",
            ),
            _stock_item(
                entity_id="shield",
                name="Shield",
                instance_id="00000000-0000-0000-0000-000000000002",
            ),
        ]
        choices = format_buy_choices(stock, speech_level=1)
        assert len(choices) == 2
        labels = [label for label, _ in choices]
        assert any("Sword" in name for name in labels)
        assert any("Shield" in name for name in labels)

    def test_speech_level_affects_price(self) -> None:
        stock = [_stock_item(rarity=Rarity.UNCOMMON)]
        choices_low = format_buy_choices(stock, speech_level=1)
        choices_high = format_buy_choices(stock, speech_level=99)
        # Higher speech level should give a lower price
        label_low, _ = choices_low[0]
        label_high, _ = choices_high[0]
        assert label_low != label_high

    def test_price_formatting_with_commas(self) -> None:
        stock = [_stock_item(rarity=Rarity.RARE)]
        choices = format_buy_choices(stock, speech_level=1)
        label, _ = choices[0]
        # rare base price is 5000 → "¤5,000"
        assert "\u00a45,000" in label

    def test_rarity_emoji_included(self) -> None:
        stock = [_stock_item(rarity=Rarity.RARE)]
        choices = format_buy_choices(stock, speech_level=1)
        label, _ = choices[0]
        # Blue circle emoji for rare
        assert "\U0001f535" in label


def _inventory_item(
    *,
    entity_id: str = "sword",
    name: str = "Sword",
    rarity: Rarity = Rarity.COMMON,
    instance_id: str | None = None,
    owner_id: int = 1,
) -> EntityInstance:
    """Build an EntityInstance for sell-choice testing."""
    iid = UUID(instance_id or "00000000-0000-0000-0000-000000000001")
    entity = ResolvedEntity(
        id=entity_id,
        name=name,
        description_short=None,
        description_long=None,
        on_look=None,
        on_touch=None,
        on_attack=None,
        on_use=None,
        on_take=None,
        on_open=None,
        on_close=None,
        on_drop=None,
        on_fish=None,
        contents_visible=False,
        rarity=rarity,
    )
    return EntityInstance(
        instance_id=iid,
        entity=entity,
        room_id=None,
        owner_id=owner_id,
    )


class TestFormatSellChoices:
    def test_empty_inventory_returns_empty(self) -> None:
        assert (
            format_sell_choices(
                [],
                speech_level=1,
                sell_spread=0.5,
                preferred_tag=None,
                tags_map={},
                stock_counts={},
            )
            == []
        )

    def test_single_tradeable_item(self) -> None:
        inv = [_inventory_item()]
        choices = format_sell_choices(
            inv,
            speech_level=1,
            sell_spread=0.5,
            preferred_tag=None,
            tags_map={},
            stock_counts={},
        )
        assert len(choices) == 1
        label, value = choices[0]
        assert "Sword" in label
        price = sale_price(Rarity.COMMON, 0, 1, 0.5, False)
        assert f"\u00a4{price:,}" in label
        assert value == "00000000-0000-0000-0000-000000000001"

    def test_non_tradeable_none_filtered(self) -> None:
        inv = [_inventory_item(rarity=Rarity.NONE)]
        choices = format_sell_choices(
            inv,
            speech_level=1,
            sell_spread=0.5,
            preferred_tag=None,
            tags_map={},
            stock_counts={},
        )
        assert choices == []

    def test_non_tradeable_quest_filtered(self) -> None:
        inv = [_inventory_item(rarity=Rarity.QUEST)]
        choices = format_sell_choices(
            inv,
            speech_level=1,
            sell_spread=0.5,
            preferred_tag=None,
            tags_map={},
            stock_counts={},
        )
        assert choices == []

    def test_speech_level_affects_price(self) -> None:
        inv = [_inventory_item(rarity=Rarity.UNCOMMON)]
        choices_low = format_sell_choices(
            inv,
            speech_level=1,
            sell_spread=0.5,
            preferred_tag=None,
            tags_map={},
            stock_counts={},
        )
        choices_high = format_sell_choices(
            inv,
            speech_level=99,
            sell_spread=0.5,
            preferred_tag=None,
            tags_map={},
            stock_counts={},
        )
        label_low, _ = choices_low[0]
        label_high, _ = choices_high[0]
        # Higher speech gives better sale price
        assert label_low != label_high

    def test_stock_count_affects_price(self) -> None:
        inv = [_inventory_item(rarity=Rarity.RARE)]
        choices_low_stock = format_sell_choices(
            inv,
            speech_level=1,
            sell_spread=0.5,
            preferred_tag=None,
            tags_map={},
            stock_counts={},
        )
        choices_high_stock = format_sell_choices(
            inv,
            speech_level=1,
            sell_spread=0.5,
            preferred_tag=None,
            tags_map={},
            stock_counts={"sword": 20},
        )
        label_low, _ = choices_low_stock[0]
        label_high, _ = choices_high_stock[0]
        # More stock in shop means lower sale price
        assert label_low != label_high

    def test_each_item_unique_entry(self) -> None:
        """Unlike buy, sell doesn't group by entity_id."""
        inv = [
            _inventory_item(
                entity_id="sword", instance_id="00000000-0000-0000-0000-000000000001"
            ),
            _inventory_item(
                entity_id="sword", instance_id="00000000-0000-0000-0000-000000000002"
            ),
        ]
        choices = format_sell_choices(
            inv,
            speech_level=1,
            sell_spread=0.5,
            preferred_tag=None,
            tags_map={},
            stock_counts={},
        )
        assert len(choices) == 2

    def test_rarity_emoji_included(self) -> None:
        inv = [_inventory_item(rarity=Rarity.RARE)]
        choices = format_sell_choices(
            inv,
            speech_level=1,
            sell_spread=0.5,
            preferred_tag=None,
            tags_map={},
            stock_counts={},
        )
        label, _ = choices[0]
        assert Rarity.RARE.emoji in label
