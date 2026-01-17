"""Tests for entity name matching."""

from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from mudd.services.entity import EntityInstance, ResolvedEntity
from mudd.services.entity_matcher import (
    MatchResult,
    get_focus_aware_autocomplete_entities,
    match_entity_by_prefix,
)


def make_entity(
    entity_id: str,
    name: str,
    description_short: str | None = None,
) -> ResolvedEntity:
    """Helper to create ResolvedEntity for tests."""
    return ResolvedEntity(
        id=entity_id,
        name=name,
        description_short=description_short,
        description_long=None,
        on_look=None,
        on_touch=None,
        on_attack=None,
        on_use=None,
        on_take=None,
        on_open=None,
        on_close=None,
        contents_visible=None,
        spawn_mode="none",
        focus_mode="none",
    )


def make_instance(entity: ResolvedEntity, room: str = "test-room") -> EntityInstance:
    """Helper to create EntityInstance for tests."""
    return EntityInstance(
        instance_id=uuid4(),
        entity=entity,
        room=room,
        owner_id=None,
    )


class TestMatchEntityByPrefix:
    """Test entity prefix matching."""

    def test_exact_match_returns_single_result(self):
        """Exact name match returns one result."""
        table = make_entity("table", "Wooden Table")
        entities = [make_instance(table)]

        result = match_entity_by_prefix("Wooden Table", entities)

        assert result.is_unique()
        assert result.matches[0].instance.entity.name == "Wooden Table"
        assert result.matches[0].match_quality == 0  # Exact match

    def test_word_prefix_matches_any_word(self):
        """Word prefix matches if any word starts with query."""
        table = make_entity("table", "Wooden Table")
        entities = [make_instance(table)]

        # "tab" matches "Table"
        result = match_entity_by_prefix("tab", entities)
        assert result.is_unique()
        assert result.matches[0].instance.entity.name == "Wooden Table"

        # "wood" matches "Wooden"
        result = match_entity_by_prefix("wood", entities)
        assert result.is_unique()
        assert result.matches[0].instance.entity.name == "Wooden Table"

    def test_case_insensitive_matching(self):
        """Matching is case-insensitive."""
        table = make_entity("table", "Wooden Table")
        entities = [make_instance(table)]

        result = match_entity_by_prefix("WOOD", entities)
        assert result.is_unique()

        result = match_entity_by_prefix("TaBlE", entities)
        assert result.is_unique()

    def test_no_match_returns_empty(self):
        """No matching entities returns empty result."""
        table = make_entity("table", "Wooden Table")
        entities = [make_instance(table)]

        result = match_entity_by_prefix("xyz", entities)
        assert result.is_empty()
        assert len(result.matches) == 0

    def test_multiple_matches_returns_ambiguous(self):
        """Multiple matching entities returns ambiguous result."""
        vase = make_entity("vase", "Flower Vase")
        pot = make_entity("pot", "Flower Pot")
        entities = [make_instance(vase), make_instance(pot)]

        result = match_entity_by_prefix("flower", entities)

        assert result.is_ambiguous()
        assert len(result.matches) == 2
        names = {m.instance.entity.name for m in result.matches}
        assert names == {"Flower Vase", "Flower Pot"}

    def test_empty_query_returns_empty(self):
        """Empty query string returns no matches."""
        table = make_entity("table", "Wooden Table")
        entities = [make_instance(table)]

        result = match_entity_by_prefix("", entities)
        assert result.is_empty()

    def test_whitespace_query_returns_empty(self):
        """Whitespace-only query returns no matches."""
        table = make_entity("table", "Wooden Table")
        entities = [make_instance(table)]

        result = match_entity_by_prefix("   ", entities)
        assert result.is_empty()

    def test_empty_entities_returns_empty(self):
        """Empty entity list returns no matches."""
        result = match_entity_by_prefix("table", [])
        assert result.is_empty()

    def test_partial_word_does_not_match(self):
        """Non-prefix partial match does not match."""
        table = make_entity("table", "Wooden Table")
        entities = [make_instance(table)]

        # "able" is in "Table" but not at the start of "Table"
        result = match_entity_by_prefix("able", entities)
        assert result.is_empty()

    def test_exact_match_has_higher_quality(self):
        """Exact matches have better quality than prefix matches."""
        table = make_entity("table", "Table")
        tablecloth = make_entity("tablecloth", "Tablecloth")
        entities = [make_instance(table), make_instance(tablecloth)]

        result = match_entity_by_prefix("Table", entities)

        # Both match, but exact match should be first
        assert result.is_ambiguous()
        assert result.matches[0].match_quality == 0  # Exact
        assert result.matches[1].match_quality == 1  # Prefix


class TestMatchResult:
    """Test MatchResult helper methods."""

    def test_is_unique_with_one_match(self):
        """is_unique returns True for single match."""
        table = make_entity("table", "Table")
        result = MatchResult(
            matches=[
                type(
                    "Match", (), {"instance": make_instance(table), "match_quality": 0}
                )()
            ]
        )
        assert result.is_unique()

    def test_is_unique_with_multiple_matches(self):
        """is_unique returns False for multiple matches."""
        from mudd.services.entity_matcher import EntityMatch

        table = make_entity("table", "Table")
        chair = make_entity("chair", "Chair")
        result = MatchResult(
            matches=[
                EntityMatch(instance=make_instance(table), match_quality=0),
                EntityMatch(instance=make_instance(chair), match_quality=0),
            ]
        )
        assert not result.is_unique()

    def test_is_ambiguous_with_multiple_matches(self):
        """is_ambiguous returns True for multiple matches."""
        from mudd.services.entity_matcher import EntityMatch

        table = make_entity("table", "Table")
        chair = make_entity("chair", "Chair")
        result = MatchResult(
            matches=[
                EntityMatch(instance=make_instance(table), match_quality=0),
                EntityMatch(instance=make_instance(chair), match_quality=0),
            ]
        )
        assert result.is_ambiguous()

    def test_is_empty_with_no_matches(self):
        """is_empty returns True for empty matches."""
        result = MatchResult(matches=[])
        assert result.is_empty()


@dataclass(frozen=True)
class MockFocusContext:
    """Mock FocusContext for testing."""

    user_id: int
    room: str
    entity_id: str
    entity_name: str
    focus_mode: str
    updated_at: datetime


@pytest.mark.asyncio
class TestGetFocusAwareAutocompleteEntities:
    """Test focus-aware autocomplete."""

    async def test_no_focus_returns_visible_entities(self):
        """Without focus, returns visible entities without prefix."""
        table = make_entity("table", "Wooden Table")
        table_instance = make_instance(table, "foyer")

        entity_service = MagicMock()
        entity_service.get_top_level_room_entities = AsyncMock(
            return_value=[table_instance]
        )
        entity_service.get_container_contents = AsyncMock(return_value=[])

        focus_service = MagicMock()
        focus_service.get_focus = AsyncMock(return_value=None)

        result = await get_focus_aware_autocomplete_entities(
            entity_service, focus_service, user_id=123, room="foyer"
        )

        assert len(result) == 1
        assert result[0].display_name == "Wooden Table"
        assert result[0].is_focused is False

    async def test_focus_shows_hidden_container_contents(self):
        """Focus on contents_visible=False container shows contents in autocomplete."""
        # Container with contents_visible=False
        chest = make_entity("chest", "Wooden Chest")
        chest_instance = make_instance(chest, "library")

        # Item inside the chest (normally hidden)
        record = make_entity("record", "Machine Girl - WLFGRL")
        record_instance = make_instance(record, "library")

        # Entity service returns chest as top-level, record as container content
        entity_service = MagicMock()
        entity_service.get_top_level_room_entities = AsyncMock(
            return_value=[chest_instance]
        )
        entity_service.get_container_contents = AsyncMock(
            return_value=[record_instance]
        )

        # User has focus on the chest
        focus = MockFocusContext(
            user_id=123,
            room="library",
            entity_id="chest",
            entity_name="Wooden Chest",
            focus_mode="container",
            updated_at=datetime.now(UTC),
        )
        focus_service = MagicMock()
        focus_service.get_focus = AsyncMock(return_value=focus)

        result = await get_focus_aware_autocomplete_entities(
            entity_service, focus_service, user_id=123, room="library"
        )

        # Should have record (focused) first, then chest (room item)
        assert len(result) == 2

        # Focused item has prefix and comes first
        assert result[0].display_name == "[Wooden Chest] Machine Girl - WLFGRL"
        assert result[0].is_focused is True

        # Room item (the chest itself) comes second without prefix
        assert result[1].display_name == "Wooden Chest"
        assert result[1].is_focused is False

    async def test_focus_excludes_focused_contents_from_room_items(self):
        """Focused contents don't appear twice (once in focused, once in room)."""
        # Open shelf with contents_visible=True
        shelf = ResolvedEntity(
            id="shelf",
            name="Bookshelf",
            description_short=None,
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            on_open=None,
            on_close=None,
            contents_visible=True,
            spawn_mode="none",
            focus_mode="container",
        )
        shelf_instance = make_instance(shelf, "library")

        # Book visible on shelf (contents_visible=True means it's in visible list)
        book = make_entity("book", "Ancient Tome")
        book_instance = make_instance(book, "library")

        # Entity service returns shelf as top-level, book as its content
        entity_service = MagicMock()
        entity_service.get_top_level_room_entities = AsyncMock(
            return_value=[shelf_instance]
        )
        # get_container_contents is called twice:
        # 1. By get_autocomplete_entities for shelf (contents_visible=True)
        # 2. By get_focus_aware_autocomplete_entities for focused container
        entity_service.get_container_contents = AsyncMock(return_value=[book_instance])

        # User has focus on the shelf
        focus = MockFocusContext(
            user_id=123,
            room="library",
            entity_id="shelf",
            entity_name="Bookshelf",
            focus_mode="container",
            updated_at=datetime.now(UTC),
        )
        focus_service = MagicMock()
        focus_service.get_focus = AsyncMock(return_value=focus)

        result = await get_focus_aware_autocomplete_entities(
            entity_service, focus_service, user_id=123, room="library"
        )

        # Book should only appear once (as focused item)
        display_names = [r.display_name for r in result]
        assert display_names.count("[Bookshelf] Ancient Tome") == 1
        assert "Ancient Tome" not in display_names  # Not in room items
