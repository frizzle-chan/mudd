"""Unit tests for overflow-aware category resolution."""

from __future__ import annotations

from mudd.utils.categories import (
    CATEGORY_CHANNEL_CAP,
    CategorySlot,
    category_index,
    matches_category,
    next_category_name,
    select_category,
)


def slot(name: str, count: int, id_: int = 0) -> CategorySlot:
    return CategorySlot(id=id_ or (hash(name) & 0xFFFF), name=name, channel_count=count)


class TestCategoryIndex:
    def test_base_name_is_index_one(self) -> None:
        assert category_index("Inventory", "Inventory") == 1

    def test_numbered_overflow(self) -> None:
        assert category_index("Inventory 2", "Inventory") == 2
        assert category_index("Inventory 17", "Inventory") == 17

    def test_index_one_suffix_is_not_a_match(self) -> None:
        # We never create "Inventory 1"; treating it as a match would make
        # next_category_name ambiguous with the bare base name.
        assert category_index("Inventory 1", "Inventory") == 0

    def test_index_zero_suffix_is_not_a_match(self) -> None:
        assert category_index("Inventory 0", "Inventory") == 0

    def test_unrelated_names(self) -> None:
        assert category_index("Skills", "Inventory") == 0
        assert category_index("Inventory Archive", "Inventory") == 0
        assert category_index("Old Inventory", "Inventory") == 0
        assert category_index("Inventory2", "Inventory") == 0

    def test_is_case_sensitive(self) -> None:
        assert category_index("inventory", "Inventory") == 0

    def test_matches_category_agrees_with_index(self) -> None:
        assert matches_category("Inventory 3", "Inventory") is True
        assert matches_category("Inventory Archive", "Inventory") is False


class TestSelectCategory:
    def test_empty_input(self) -> None:
        assert select_category([], "Inventory") is None

    def test_returns_the_only_category_with_room(self) -> None:
        chosen = select_category([slot("Inventory", 3)], "Inventory")
        assert chosen is not None
        assert chosen.name == "Inventory"

    def test_prefers_lowest_index_with_room(self) -> None:
        slots = [
            slot("Inventory 3", 0),
            slot("Inventory", CATEGORY_CHANNEL_CAP),
            slot("Inventory 2", 10),
        ]
        chosen = select_category(slots, "Inventory")
        assert chosen is not None
        assert chosen.name == "Inventory 2"

    def test_ordering_ignores_list_order(self) -> None:
        slots = [slot("Inventory 2", 0), slot("Inventory", 0)]
        chosen = select_category(slots, "Inventory")
        assert chosen is not None
        assert chosen.name == "Inventory"

    def test_all_full_returns_none(self) -> None:
        slots = [
            slot("Inventory", CATEGORY_CHANNEL_CAP),
            slot("Inventory 2", CATEGORY_CHANNEL_CAP),
        ]
        assert select_category(slots, "Inventory") is None

    def test_cap_is_exclusive(self) -> None:
        under = [slot("Inventory", CATEGORY_CHANNEL_CAP - 1)]
        at_cap = [slot("Inventory", CATEGORY_CHANNEL_CAP)]
        assert select_category(under, "Inventory") is not None
        assert select_category(at_cap, "Inventory") is None

    def test_ignores_non_matching_categories(self) -> None:
        slots = [slot("Skills", 0), slot("General", 0)]
        assert select_category(slots, "Inventory") is None

    def test_non_contiguous_indices(self) -> None:
        slots = [
            slot("Inventory", CATEGORY_CHANNEL_CAP),
            slot("Inventory 5", 4),
        ]
        chosen = select_category(slots, "Inventory")
        assert chosen is not None
        assert chosen.name == "Inventory 5"


class TestNextCategoryName:
    def test_no_categories_yields_base(self) -> None:
        assert next_category_name([], "Inventory") == "Inventory"

    def test_only_unrelated_categories_yields_base(self) -> None:
        assert next_category_name([slot("Skills", 0)], "Inventory") == "Inventory"

    def test_base_only_yields_two(self) -> None:
        slots = [slot("Inventory", 50)]
        assert next_category_name(slots, "Inventory") == "Inventory 2"

    def test_uses_max_index(self) -> None:
        slots = [
            slot("Inventory", 50),
            slot("Inventory 2", 50),
            slot("Inventory 3", 50),
        ]
        assert next_category_name(slots, "Inventory") == "Inventory 4"

    def test_non_contiguous_indices_do_not_backfill(self) -> None:
        slots = [slot("Inventory", 50), slot("Inventory 7", 50)]
        assert next_category_name(slots, "Inventory") == "Inventory 8"

    def test_base_missing_but_overflow_present(self) -> None:
        slots = [slot("Inventory 2", 50)]
        assert next_category_name(slots, "Inventory") == "Inventory 3"
