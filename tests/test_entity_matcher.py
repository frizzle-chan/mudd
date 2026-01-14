"""Tests for entity name matching."""

from uuid import uuid4

from mudd.services.entity import EntityInstance, ResolvedEntity
from mudd.services.entity_matcher import MatchResult, match_entity_by_prefix


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
        contents_visible=None,
        spawn_mode="none",
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
