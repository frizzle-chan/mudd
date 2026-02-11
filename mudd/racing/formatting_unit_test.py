"""Unit tests for racing text formatting."""

from __future__ import annotations

from mudd.racing.formatting import format_form, format_results, format_star_rating
from mudd.racing.odds import HorseOdds


class TestFormatForm:
    def test_empty_returns_dash(self) -> None:
        assert format_form([]) == "—"

    def test_win(self) -> None:
        assert format_form([1]) == "W"

    def test_place_second(self) -> None:
        assert format_form([2]) == "P"

    def test_place_third(self) -> None:
        assert format_form([3]) == "P"

    def test_loss(self) -> None:
        assert format_form([4]) == "L"

    def test_mixed_results(self) -> None:
        # Newest first: [1, 3, 4, 2, 1]
        # Reversed for display (oldest left): 1-2-4-3-1 → W-P-L-P-W
        result = format_form([1, 3, 4, 2, 1])
        assert result == "W-P-L-P-W"

    def test_truncates_to_count(self) -> None:
        results = [1, 2, 3, 4, 1, 2, 3]
        result = format_form(results, count=3)
        # Takes first 3 newest: [1, 2, 3], reversed: [3, 2, 1] → P-P-W
        assert result == "P-P-W"

    def test_most_recent_on_right(self) -> None:
        # [1, 4] → newest=1 should be rightmost
        result = format_form([1, 4])
        assert result == "L-W"


class TestFormatStarRating:
    def test_five_stars(self) -> None:
        assert format_star_rating(5) == "★★★★★"

    def test_one_star(self) -> None:
        assert format_star_rating(1) == "★☆☆☆☆"

    def test_three_stars(self) -> None:
        assert format_star_rating(3) == "★★★☆☆"

    def test_zero_stars(self) -> None:
        assert format_star_rating(0) == "☆☆☆☆☆"


class TestFormatResults:
    def test_correct_order_and_labels(self) -> None:
        odds = [
            HorseOdds("a", 80, 1.0, 80, 0.4, 2.2, 5),
            HorseOdds("b", 60, 1.0, 60, 0.3, 3.0, 4),
            HorseOdds("c", 40, 1.0, 40, 0.2, 4.5, 3),
            HorseOdds("d", 20, 1.0, 20, 0.1, 9.0, 1),
        ]
        names = ["Alpha", "Beta", "Charlie", "Delta"]
        finishing_order = [1, 0, 2, 3]
        result = format_results(finishing_order, names, odds)
        lines = result.split("\n")
        assert "1st" in lines[0]
        assert "Beta" in lines[0]
        assert "2nd" in lines[1]
        assert "Alpha" in lines[1]
        assert "3rd" in lines[2]
        assert "Charlie" in lines[2]
        assert "4th" in lines[3]
        assert "Delta" in lines[3]
