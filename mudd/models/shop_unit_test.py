"""Unit tests for shop pricing logic."""

import pytest

from mudd.models.shop import (
    RARITY_BASE_PRICES,
    base_price,
    dynamic_price,
    purchase_price,
    sale_price,
    supply_adjustment,
)
from mudd.utils.text import Rarity


class TestBasePrice:
    """Tests for base_price()."""

    @pytest.mark.parametrize(
        ("rarity", "expected"),
        [
            ("none", 0),
            ("common", 100),
            ("uncommon", 1_000),
            ("rare", 5_000),
            ("epic", 25_000),
            ("legendary", 100_000),
            ("mythic", 500_000),
            ("quest", 0),
        ],
    )
    def test_returns_correct_value(self, rarity: Rarity, expected: int):
        assert base_price(rarity) == expected

    def test_all_rarities_covered(self):
        """Every Rarity literal has a base price entry."""
        rarities: list[Rarity] = [
            "none",
            "common",
            "uncommon",
            "rare",
            "epic",
            "legendary",
            "mythic",
            "quest",
        ]
        for r in rarities:
            assert r in RARITY_BASE_PRICES


class TestSupplyAdjustment:
    """Tests for supply_adjustment()."""

    def test_single_item_baseline(self):
        assert supply_adjustment(1) == pytest.approx(1.0)

    def test_decreases_with_count(self):
        prev = supply_adjustment(1)
        for count in [2, 5, 10, 20]:
            current = supply_adjustment(count)
            assert current < prev
            prev = current

    def test_zero_count_treated_as_one(self):
        """stock_count=0 should clamp to same as count=1."""
        assert supply_adjustment(0) == pytest.approx(1.0)

    def test_known_values(self):
        assert supply_adjustment(5) == pytest.approx(1.0 / 1.4)
        assert supply_adjustment(10) == pytest.approx(1.0 / 1.9)
        assert supply_adjustment(20) == pytest.approx(1.0 / 2.9)


class TestDynamicPrice:
    """Tests for dynamic_price()."""

    def test_single_common(self):
        assert dynamic_price("common", 1) == 100

    def test_supply_reduces_price(self):
        assert dynamic_price("rare", 10) < dynamic_price("rare", 1)

    def test_non_tradeable_always_zero(self):
        assert dynamic_price("none", 1) == 0
        assert dynamic_price("quest", 5) == 0

    def test_truncates_to_int(self):
        result = dynamic_price("common", 5)
        assert isinstance(result, int)


class TestPurchasePrice:
    """Tests for purchase_price()."""

    def test_no_discount_at_level_1(self):
        assert purchase_price("common", 1, 1) == dynamic_price("common", 1)

    def test_max_discount_at_level_99(self):
        base = dynamic_price("rare", 1)
        price = purchase_price("rare", 1, 99)
        # 15% discount
        assert price == int(base * 0.85)

    def test_mid_level_discount(self):
        base = dynamic_price("uncommon", 1)
        price = purchase_price("uncommon", 1, 50)
        discount = 0.15 * 49 / 98
        assert price == int(base * (1.0 - discount))

    def test_non_tradeable_stays_zero(self):
        assert purchase_price("none", 1, 99) == 0
        assert purchase_price("quest", 1, 50) == 0


class TestSalePrice:
    """Tests for sale_price()."""

    def test_basic_sale_spread(self):
        """Sale price applies sell_spread to dynamic price."""
        dp = dynamic_price("common", 1)
        result = sale_price("common", 1, 1, 0.5, has_preferred_tag=False)
        assert result == int(dp * 0.5)

    def test_speech_bonus_at_level_99(self):
        dp = dynamic_price("rare", 1)
        result = sale_price("rare", 1, 99, 0.5, has_preferred_tag=False)
        # 25% bonus on top of 0.5 spread
        assert result == int(dp * 0.5 * 1.25)

    def test_preferred_tag_multiplier(self):
        dp = dynamic_price("uncommon", 1)
        without = sale_price("uncommon", 1, 1, 0.5, has_preferred_tag=False)
        with_tag = sale_price("uncommon", 1, 1, 0.5, has_preferred_tag=True)
        assert with_tag == int(dp * 0.5 * 1.5)
        assert with_tag > without

    def test_floor_enforced(self):
        """Sale price never drops below 25% of base price."""
        # Very low spread that would push below floor
        result = sale_price("rare", 20, 1, 0.1, has_preferred_tag=False)
        floor = int(base_price("rare") * 0.25)
        assert result >= floor

    def test_floor_with_non_tradeable(self):
        """Non-tradeable items have 0 base so floor is 0."""
        assert sale_price("none", 1, 99, 0.5, has_preferred_tag=True) == 0
        assert sale_price("quest", 1, 99, 0.5, has_preferred_tag=True) == 0

    def test_combined_bonuses(self):
        """Speech bonus and preferred tag stack."""
        dp = dynamic_price("epic", 1)
        result = sale_price("epic", 1, 99, 0.5, has_preferred_tag=True)
        expected = int(dp * 0.5 * 1.25 * 1.5)
        assert result == expected
