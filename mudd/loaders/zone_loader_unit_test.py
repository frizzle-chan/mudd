"""Unit tests for shop parsing in zone_loader."""

import pytest

from mudd.loaders.zone_loader import ShopData, _parse_shop_row


class TestParseShopRow:
    """Tests for _parse_shop_row()."""

    def test_valid_with_all_fields(self):
        row = {
            "Id": "fish-market",
            "Name": "Fish Market",
            "PreferredTag": "pond_fish",
            "SellSpread": "0.6",
            "RestockTag": "pond_fish",
            "RestockIntervalMinutes": "720",
        }
        result = _parse_shop_row(row)
        assert result == ShopData(
            id="fish-market",
            name="Fish Market",
            preferred_tag="pond_fish",
            sell_spread=0.6,
            restock_tag="pond_fish",
            restock_interval_minutes=720,
        )

    def test_defaults(self):
        row = {"Id": "general-store", "Name": "General Store"}
        result = _parse_shop_row(row)
        assert result.id == "general-store"
        assert result.name == "General Store"
        assert result.preferred_tag is None
        assert result.sell_spread == 0.5
        assert result.restock_tag is None
        assert result.restock_interval_minutes == 1440

    def test_empty_optional_fields_become_none(self):
        row = {
            "Id": "test-shop",
            "Name": "Test",
            "PreferredTag": "",
            "RestockTag": "",
        }
        result = _parse_shop_row(row)
        assert result.preferred_tag is None
        assert result.restock_tag is None

    def test_invalid_sell_spread(self):
        row = {"Id": "bad-shop", "Name": "Bad", "SellSpread": "not_a_number"}
        with pytest.raises(ValueError, match="invalid SellSpread"):
            _parse_shop_row(row)

    def test_invalid_restock_interval(self):
        row = {
            "Id": "bad-shop",
            "Name": "Bad",
            "RestockIntervalMinutes": "abc",
        }
        with pytest.raises(ValueError, match="invalid RestockIntervalMinutes"):
            _parse_shop_row(row)


class TestShopData:
    """Tests for ShopData dataclass."""

    def test_construction(self):
        shop = ShopData(id="test", name="Test Shop")
        assert shop.id == "test"
        assert shop.name == "Test Shop"
        assert shop.preferred_tag is None
        assert shop.sell_spread == 0.5
        assert shop.restock_tag is None
        assert shop.restock_interval_minutes == 1440

    def test_equality(self):
        a = ShopData(id="x", name="X", sell_spread=0.3)
        b = ShopData(id="x", name="X", sell_spread=0.3)
        assert a == b
