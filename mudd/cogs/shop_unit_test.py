"""Unit tests for shop cog autocomplete helper logic."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from mudd.cogs.shop import format_buy_choices
from mudd.models.shop import StockItem
from mudd.utils.text import Rarity


def _stock_item(
    *,
    entity_id: str = "sword",
    name: str = "Sword",
    rarity: Rarity = "common",
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
        assert "x3" in label
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
        stock = [_stock_item(rarity="uncommon")]
        choices_low = format_buy_choices(stock, speech_level=1)
        choices_high = format_buy_choices(stock, speech_level=99)
        # Higher speech level should give a lower price
        label_low, _ = choices_low[0]
        label_high, _ = choices_high[0]
        assert label_low != label_high

    def test_price_formatting_with_commas(self) -> None:
        stock = [_stock_item(rarity="rare")]
        choices = format_buy_choices(stock, speech_level=1)
        label, _ = choices[0]
        # rare base price is 5000 → "¤5,000"
        assert "\u00a45,000" in label

    def test_rarity_emoji_included(self) -> None:
        stock = [_stock_item(rarity="rare")]
        choices = format_buy_choices(stock, speech_level=1)
        label, _ = choices[0]
        # Blue circle emoji for rare
        assert "\U0001f535" in label
