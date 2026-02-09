"""Unit tests for the XP formula module."""

from __future__ import annotations

import pytest

from mudd.skills.xp import MAX_LEVEL, MAX_XP, level_for_xp, xp_for_level


class TestXpForLevel:
    def test_level_1_requires_zero_xp(self) -> None:
        assert xp_for_level(1) == 0

    def test_level_2_requires_83_xp(self) -> None:
        assert xp_for_level(2) == 83

    def test_level_99_approximately_13m(self) -> None:
        xp = xp_for_level(99)
        assert 13_000_000 < xp < 14_000_000

    def test_level_92_is_roughly_halfway_to_99(self) -> None:
        xp_92 = xp_for_level(92)
        xp_99 = xp_for_level(99)
        # Level 92 should be approximately half of level 99's XP
        ratio = xp_92 / xp_99
        assert 0.49 < ratio < 0.51

    def test_monotonically_increasing(self) -> None:
        for level in range(2, MAX_LEVEL + 1):
            assert xp_for_level(level) > xp_for_level(level - 1)

    def test_raises_for_level_0(self) -> None:
        with pytest.raises(ValueError, match="Level must be between 1"):
            xp_for_level(0)

    def test_raises_for_level_100(self) -> None:
        with pytest.raises(ValueError, match="Level must be between 1"):
            xp_for_level(100)

    def test_raises_for_negative_level(self) -> None:
        with pytest.raises(ValueError, match="Level must be between 1"):
            xp_for_level(-1)


class TestLevelForXp:
    def test_zero_xp_is_level_1(self) -> None:
        assert level_for_xp(0) == 1

    def test_82_xp_is_level_1(self) -> None:
        assert level_for_xp(82) == 1

    def test_83_xp_is_level_2(self) -> None:
        assert level_for_xp(83) == 2

    def test_exact_level_boundaries(self) -> None:
        for level in range(1, MAX_LEVEL + 1):
            xp = xp_for_level(level)
            assert level_for_xp(xp) == level

    def test_one_below_boundary(self) -> None:
        for level in range(2, MAX_LEVEL + 1):
            xp = xp_for_level(level) - 1
            assert level_for_xp(xp) == level - 1

    def test_max_xp_is_level_99(self) -> None:
        assert level_for_xp(MAX_XP) == 99

    def test_very_large_xp_is_level_99(self) -> None:
        assert level_for_xp(999_999_999) == 99

    def test_raises_for_negative_xp(self) -> None:
        with pytest.raises(ValueError, match="XP must be non-negative"):
            level_for_xp(-1)


class TestConstants:
    def test_max_level(self) -> None:
        assert MAX_LEVEL == 99

    def test_max_xp(self) -> None:
        assert MAX_XP == 200_000_000
