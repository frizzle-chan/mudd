"""Unit tests for race simulation."""

from __future__ import annotations

from random import Random

import pytest

from mudd.racing.config import RaceConfig
from mudd.racing.odds import HorseStats
from mudd.racing.simulation import BurstType, simulate_race


def _make_horses() -> list[HorseStats]:
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


class TestDeterminism:
    def test_same_seed_same_result(self) -> None:
        horses = _make_horses()
        r1 = simulate_race(horses, rng=Random(42))
        r2 = simulate_race(horses, rng=Random(42))
        assert r1.snapshots == r2.snapshots
        assert r1.finishing_order == r2.finishing_order
        assert r1.events == r2.events

    def test_different_seeds_differ(self) -> None:
        horses = _make_horses()
        r1 = simulate_race(horses, rng=Random(42))
        r2 = simulate_race(horses, rng=Random(99))
        # Extremely unlikely to be identical
        assert r1.finishing_order != r2.finishing_order or r1.snapshots != r2.snapshots


class TestSnapshotProperties:
    def test_winner_finishes_at_one(self) -> None:
        result = simulate_race(_make_horses(), rng=Random(42))
        final = result.snapshots[-1]
        assert max(final) == pytest.approx(1.0)

    def test_first_snapshot_all_zeros(self) -> None:
        result = simulate_race(_make_horses(), rng=Random(42))
        assert result.snapshots[0] == [0.0, 0.0, 0.0, 0.0]

    def test_positions_non_decreasing(self) -> None:
        result = simulate_race(_make_horses(), rng=Random(42))
        n = len(_make_horses())
        for i in range(n):
            for t in range(len(result.snapshots) - 1):
                assert result.snapshots[t + 1][i] >= result.snapshots[t][i]

    def test_snapshot_count(self) -> None:
        config = RaceConfig(num_ticks=60)
        result = simulate_race(_make_horses(), rng=Random(42), config=config)
        assert len(result.snapshots) == 61  # 0 through 60 inclusive


class TestFinishingOrder:
    def test_is_permutation(self) -> None:
        result = simulate_race(_make_horses(), rng=Random(42))
        assert sorted(result.finishing_order) == list(range(len(_make_horses())))

    def test_winner_is_first(self) -> None:
        result = simulate_race(_make_horses(), rng=Random(42))
        final = result.snapshots[-1]
        winner_idx = result.finishing_order[0]
        assert final[winner_idx] == max(final)


class TestBurstEvents:
    def test_valid_tick_range(self) -> None:
        config = RaceConfig(num_ticks=60)
        result = simulate_race(_make_horses(), rng=Random(42), config=config)
        for event in result.events:
            assert 1 <= event.tick <= config.num_ticks

    def test_valid_horse_index(self) -> None:
        horses = _make_horses()
        result = simulate_race(horses, rng=Random(42))
        for event in result.events:
            assert 0 <= event.horse_index < len(horses)

    def test_valid_burst_types(self) -> None:
        result = simulate_race(_make_horses(), rng=Random(42))
        for event in result.events:
            assert event.burst_type in (BurstType.SURGE, BurstType.STUMBLE)

    def test_horse_ids_match(self) -> None:
        horses = _make_horses()
        result = simulate_race(horses, rng=Random(42))
        assert result.horse_ids == [h.horse_id for h in horses]


class TestProgressFloor:
    def test_no_stalling_with_weak_horse(self) -> None:
        """A horse with terrible stats still makes forward progress every tick.

        The progress floor is applied after rubber-banding, so even a weak horse
        behind the pack makes visible forward movement every tick.
        """
        config = RaceConfig()
        weak = [
            HorseStats(
                "slug",
                speed=1,
                stamina=1,
                consistency=1,
                luck=1,
                recent_races=0,
                recent_wins=0,
                recent_places=0,
            ),
            # Need at least one other horse for a valid race
            HorseStats(
                "rival",
                speed=90,
                stamina=90,
                consistency=90,
                luck=90,
                recent_races=0,
                recent_wins=0,
                recent_places=0,
            ),
        ]
        # Try multiple seeds — at least one would trigger stalling without a floor
        for seed in range(20):
            result = simulate_race(weak, rng=Random(seed), config=config)
            # Check the weak horse (index 0) never has consecutive identical positions
            for t in range(len(result.snapshots) - 2):
                pos_now = result.snapshots[t + 1][0]
                pos_next = result.snapshots[t + 2][0]
                assert pos_next > pos_now, (
                    f"seed={seed}: horse stalled at tick {t + 2} (position {pos_now})"
                )

    def test_floor_zero_allows_stalling(self) -> None:
        """With floor=0.0, rubber-banding can erase progress and cause stalling."""
        config = RaceConfig(progress_floor=0.0)
        weak = [
            HorseStats(
                "slug",
                speed=1,
                stamina=1,
                consistency=1,
                luck=1,
                recent_races=0,
                recent_wins=0,
                recent_places=0,
            ),
            HorseStats(
                "rival",
                speed=90,
                stamina=90,
                consistency=90,
                luck=90,
                recent_races=0,
                recent_wins=0,
                recent_places=0,
            ),
        ]
        # At least one seed out of 50 should produce a stall with floor=0
        found_stall = False
        for seed in range(50):
            result = simulate_race(weak, rng=Random(seed), config=config)
            for t in range(len(result.snapshots) - 2):
                if result.snapshots[t + 2][0] == result.snapshots[t + 1][0]:
                    found_stall = True
                    break
            if found_stall:
                break
        assert found_stall, "Expected at least one stall with floor=0.0"
