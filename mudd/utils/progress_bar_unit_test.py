"""Unit tests for shaded progress bar generator."""

from __future__ import annotations

from mudd.utils.progress_bar import DEFAULT_SIZE, SHADED, shaded_bar


class TestShadedBar:
    def test_zero_percent(self) -> None:
        bar = shaded_bar(0)
        assert bar == "░" * DEFAULT_SIZE

    def test_hundred_percent(self) -> None:
        bar = shaded_bar(100)
        assert bar == "█" * DEFAULT_SIZE

    def test_always_correct_length(self) -> None:
        for p in range(101):
            assert len(shaded_bar(p)) == DEFAULT_SIZE

    def test_custom_size(self) -> None:
        bar = shaded_bar(50, size=10)
        assert len(bar) == 10

    def test_negative_clamps_to_zero(self) -> None:
        assert shaded_bar(-10) == shaded_bar(0)

    def test_over_100_clamps_to_full(self) -> None:
        assert shaded_bar(150) == shaded_bar(100)

    def test_50_percent_half_filled(self) -> None:
        bar = shaded_bar(50)
        # Exactly 50% should have half full blocks and half empty, no partial
        half = DEFAULT_SIZE // 2
        full_count = bar.count("█")
        empty_count = bar.count("░")
        assert full_count == half
        assert empty_count == half

    def test_small_percent_shows_partial(self) -> None:
        bar = shaded_bar(1)
        # Should not be all empty — at least one partial character
        assert bar != "░" * DEFAULT_SIZE
        # First char should be a partial shade (▒ minimum)
        assert bar[0] in SHADED[1:-1]

    def test_near_full_shows_partial(self) -> None:
        bar = shaded_bar(99)
        # Should not be all full
        assert bar != "█" * DEFAULT_SIZE
        # Last non-full char should be a partial shade
        assert any(c in SHADED[1:-1] for c in bar)

    def test_monotonic_fill(self) -> None:
        """Higher percentages should never have fewer filled chars."""
        prev_weight = -1
        for p in range(101):
            bar = shaded_bar(p)
            # Weight: █=3, ▓=2, ▒=1, ░=0
            weight = sum(SHADED.index(c) for c in bar)
            assert weight >= prev_weight, f"Bar weight decreased at {p}%"
            prev_weight = weight

    def test_uses_all_shade_levels(self) -> None:
        """Across all percentages, every shade character should appear."""
        all_chars: set[str] = set()
        for p in range(101):
            all_chars.update(shaded_bar(p))
        for c in SHADED:
            assert c in all_chars
