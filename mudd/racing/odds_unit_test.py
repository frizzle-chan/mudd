"""Unit tests for odds calculation."""

from __future__ import annotations

import pytest

from mudd.racing.config import RaceConfig
from mudd.racing.odds import (
    HorseStats,
    base_strength,
    compute_odds,
    performance_modifier,
)


class TestBaseStrength:
    def test_flash_stats(self) -> None:
        # Flash: speed=90, stamina=70, consistency=75, luck=55
        result = base_strength(speed=90, stamina=70, luck=55, consistency=75)
        assert result == pytest.approx(79.0)

    def test_glue_stats(self) -> None:
        # Glue: speed=30, stamina=55, consistency=90, luck=20
        result = base_strength(speed=30, stamina=55, luck=20, consistency=90)
        assert result == pytest.approx(42.5)

    def test_all_equal(self) -> None:
        result = base_strength(speed=50, stamina=50, luck=50, consistency=50)
        assert result == pytest.approx(50.0)


class TestPerformanceModifier:
    def test_no_history_returns_one(self) -> None:
        result = performance_modifier(
            base=79.0, total_base=200.0, recent_wins=0, recent_races=0
        )
        assert result == 1.0

    def test_overperforming(self) -> None:
        # Expected ~40% win rate, actual 80%
        result = performance_modifier(
            base=80.0, total_base=200.0, recent_wins=8, recent_races=10
        )
        assert result > 1.0

    def test_underperforming(self) -> None:
        # Expected ~40% win rate, actual 10%
        result = performance_modifier(
            base=80.0, total_base=200.0, recent_wins=1, recent_races=10
        )
        assert result < 1.0

    def test_exact_expected(self) -> None:
        # Actual matches expected: 50% base, 50% actual
        result = performance_modifier(
            base=100.0, total_base=200.0, recent_wins=5, recent_races=10
        )
        assert result == pytest.approx(1.0)


def _make_horses() -> list[HorseStats]:
    """Create the four test horses matching recfile data."""
    return [
        HorseStats(
            "flash",
            speed=90,
            stamina=70,
            consistency=75,
            luck=55,
            recent_races=0,
            recent_wins=0,
            recent_places=0,
        ),
        HorseStats(
            "thunder",
            speed=65,
            stamina=85,
            consistency=50,
            luck=60,
            recent_races=0,
            recent_wins=0,
            recent_places=0,
        ),
        HorseStats(
            "bones",
            speed=50,
            stamina=40,
            consistency=25,
            luck=90,
            recent_races=0,
            recent_wins=0,
            recent_places=0,
        ),
        HorseStats(
            "glue",
            speed=30,
            stamina=55,
            consistency=90,
            luck=20,
            recent_races=0,
            recent_wins=0,
            recent_places=0,
        ),
    ]


class TestComputeOdds:
    def test_probabilities_sum_to_one(self) -> None:
        odds = compute_odds(_make_horses())
        total = sum(o.true_probability for o in odds)
        assert total == pytest.approx(1.0)

    def test_displayed_payouts_reflect_house_edge(self) -> None:
        config = RaceConfig(house_edge=0.10)
        odds = compute_odds(_make_horses(), config)
        # Implied probability from displayed payouts should sum to > 1.0
        implied = sum(1.0 / o.displayed_payout for o in odds)
        assert implied > 1.0

    def test_star_ratings_relative_to_max(self) -> None:
        odds = compute_odds(_make_horses())
        # Strongest horse should have 5 stars
        strongest = max(odds, key=lambda o: o.dynamic_strength)
        assert strongest.star_rating == 5

        # All ratings between 1 and 5
        for o in odds:
            assert 1 <= o.star_rating <= 5

    def test_flash_has_highest_base_strength(self) -> None:
        odds = compute_odds(_make_horses())
        flash_odds = next(o for o in odds if o.horse_id == "flash")
        for o in odds:
            assert flash_odds.base_strength >= o.base_strength

    def test_no_history_modifier_is_one(self) -> None:
        odds = compute_odds(_make_horses())
        for o in odds:
            assert o.performance_modifier == pytest.approx(1.0)
