"""Tests for entity formatting.

Tests:
1. format_entity_name wraps name in Discord italics
2. interpolate_description replaces {name} placeholder
3. interpolate_description handles None template
4. format_entity_with_contents formats entity without contents
5. format_entity_with_contents formats entity with nested contents
6. format_room_entities returns empty string for no entities
7. format_room_entities formats multiple entities
"""

from uuid import uuid4

import pytest

from mudd.formatting.entities import (
    format_entity_detail,
    format_entity_name,
    format_entity_with_contents,
    format_room_entities,
    interpolate_description,
)
from mudd.services.entity import EntityInstance, ResolvedEntity


class MockService:
    """Mock entity service for testing."""

    def __init__(self, contents: list[EntityInstance] | None = None):
        self._contents = contents or []

    async def get_container_contents(
        self, container_id: str, room: str
    ) -> list[EntityInstance]:
        return self._contents


class TestFormatEntityName:
    """Test format_entity_name function."""

    def test_wraps_name_in_italics(self):
        """Name is wrapped in Discord italic markers."""
        assert format_entity_name("Wooden Table") == "*Wooden Table*"

    def test_handles_single_word(self):
        """Single word names work correctly."""
        assert format_entity_name("Table") == "*Table*"

    def test_handles_special_characters(self):
        """Names with special characters are preserved."""
        assert format_entity_name("Old Man's Chair") == "*Old Man's Chair*"


class TestInterpolateDescription:
    """Test interpolate_description function."""

    def test_replaces_name_placeholder(self):
        """The {name} placeholder is replaced with formatted name."""
        result = interpolate_description("a {name} sits here", "Wooden Table")
        assert result == "a *Wooden Table* sits here"

    def test_handles_multiple_placeholders(self):
        """Multiple {name} placeholders are all replaced."""
        result = interpolate_description("the {name} is a nice {name}", "Flower Vase")
        assert result == "the *Flower Vase* is a nice *Flower Vase*"

    def test_handles_no_placeholder(self):
        """Template without placeholder is returned unchanged."""
        result = interpolate_description("a simple table", "Wooden Table")
        assert result == "a simple table"

    def test_handles_none_template(self):
        """None template returns empty string."""
        result = interpolate_description(None, "Wooden Table")
        assert result == ""


class TestFormatEntityWithContents:
    """Test format_entity_with_contents function."""

    def test_entity_without_contents(self):
        """Entity without contents shows only its description."""
        entity = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {name} sits here",
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            contents_visible=True,
            spawn_mode="none",
        )
        result = format_entity_with_contents(entity, None)
        assert result == "a *Wooden Table* sits here"

    def test_entity_with_empty_contents(self):
        """Entity with empty contents list shows only its description."""
        entity = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {name} sits here",
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            contents_visible=True,
            spawn_mode="none",
        )
        result = format_entity_with_contents(entity, [])
        assert result == "a *Wooden Table* sits here"

    def test_entity_with_contents(self):
        """Entity with contents shows nested items."""
        table = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {name} sits here",
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            contents_visible=True,
            spawn_mode="none",
        )
        vase = ResolvedEntity(
            id="vase",
            name="Flower Vase",
            description_short="a {name}",
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            contents_visible=None,
            spawn_mode="none",
        )
        plaque = ResolvedEntity(
            id="plaque",
            name="Inscribed Plaque",
            description_short="a {name}",
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            contents_visible=None,
            spawn_mode="none",
        )
        contents = [
            EntityInstance(
                instance_id=uuid4(), entity=vase, room="foyer", owner_id=None
            ),
            EntityInstance(
                instance_id=uuid4(), entity=plaque, room="foyer", owner_id=None
            ),
        ]

        result = format_entity_with_contents(table, contents)
        assert result == (
            "a *Wooden Table* sits here. On it: a *Flower Vase*, a *Inscribed Plaque*"
        )


@pytest.mark.asyncio
class TestFormatRoomEntities:
    """Test format_room_entities function."""

    async def test_empty_entities_returns_empty_string(self):
        """No entities returns empty string."""
        result = await format_room_entities([], MockService(), "foyer")
        assert result == ""

    async def test_single_entity_no_contents(self):
        """Single entity without visible contents."""
        table = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {name} sits here",
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            contents_visible=False,  # Not visible
            spawn_mode="none",
        )
        entities = [
            EntityInstance(
                instance_id=uuid4(), entity=table, room="foyer", owner_id=None
            ),
        ]

        result = await format_room_entities(entities, MockService(), "foyer")
        assert result == "a *Wooden Table* sits here"

    async def test_entity_with_visible_contents(self):
        """Entity with contents_visible=True fetches and displays contents."""
        table = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {name} sits here",
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            contents_visible=True,
            spawn_mode="none",
        )
        vase = ResolvedEntity(
            id="vase",
            name="Flower Vase",
            description_short="a {name}",
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            contents_visible=None,
            spawn_mode="none",
        )
        entities = [
            EntityInstance(
                instance_id=uuid4(), entity=table, room="foyer", owner_id=None
            ),
        ]

        class MockService:
            async def get_container_contents(self, container_id, room):
                if container_id == "table":
                    return [
                        EntityInstance(
                            instance_id=uuid4(),
                            entity=vase,
                            room="foyer",
                            owner_id=None,
                        ),
                    ]
                return []

        result = await format_room_entities(entities, MockService(), "foyer")
        assert result == "a *Wooden Table* sits here. On it: a *Flower Vase*"

    async def test_multiple_entities(self):
        """Multiple top-level entities are joined with newlines."""
        table = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {name} sits here",
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            contents_visible=False,
            spawn_mode="none",
        )
        chair = ResolvedEntity(
            id="chair",
            name="Old Chair",
            description_short="an {name} is in the corner",
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            contents_visible=None,
            spawn_mode="none",
        )
        entities = [
            EntityInstance(
                instance_id=uuid4(), entity=table, room="foyer", owner_id=None
            ),
            EntityInstance(
                instance_id=uuid4(), entity=chair, room="foyer", owner_id=None
            ),
        ]

        result = await format_room_entities(entities, MockService(), "foyer")
        assert result == ("a *Wooden Table* sits here\nan *Old Chair* is in the corner")


@pytest.mark.asyncio
class TestFormatEntityDetail:
    """Tests for format_entity_detail function."""

    async def test_shows_description_long(self):
        """Shows entity's long description."""
        entity = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {name}",
            description_long="A sturdy oak table with worn edges.",
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            contents_visible=None,
            spawn_mode="none",
        )
        instance = EntityInstance(
            instance_id=uuid4(),
            entity=entity,
            room="foyer",
            owner_id=None,
        )

        result = await format_entity_detail(instance, MockService(), "foyer")
        assert "A sturdy oak table with worn edges." in result

    async def test_falls_back_to_description_short(self):
        """Falls back to description_short when description_long is None."""
        entity = ResolvedEntity(
            id="plaque",
            name="Inscribed Plaque",
            description_short="a {name} on the wall",
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            contents_visible=None,
            spawn_mode="none",
        )
        instance = EntityInstance(
            instance_id=uuid4(),
            entity=entity,
            room="foyer",
            owner_id=None,
        )

        result = await format_entity_detail(instance, MockService(), "foyer")
        assert "a *Inscribed Plaque* on the wall" in result

    async def test_shows_container_contents_long_description(self):
        """Shows long descriptions of container contents."""
        table_entity = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {name}",
            description_long="A sturdy oak table.",
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            contents_visible=True,
            spawn_mode="none",
        )
        table_instance = EntityInstance(
            instance_id=uuid4(),
            entity=table_entity,
            room="foyer",
            owner_id=None,
        )

        vase_entity = ResolvedEntity(
            id="vase",
            name="Flower Vase",
            description_short="a {name}",
            description_long="A teal ceramic vase with gold trim.",
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            contents_visible=None,
            spawn_mode="none",
        )
        vase_instance = EntityInstance(
            instance_id=uuid4(),
            entity=vase_entity,
            room="foyer",
            owner_id=None,
        )

        mock_service = MockService([vase_instance])
        result = await format_entity_detail(table_instance, mock_service, "foyer")

        assert "A sturdy oak table." in result
        assert "On it:" in result
        assert "A teal ceramic vase with gold trim." in result

    async def test_returns_default_when_no_description(self):
        """Returns default message when entity has no descriptions."""
        entity = ResolvedEntity(
            id="blank",
            name="Blank",
            description_short=None,
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            contents_visible=None,
            spawn_mode="none",
        )
        instance = EntityInstance(
            instance_id=uuid4(),
            entity=entity,
            room="foyer",
            owner_id=None,
        )

        result = await format_entity_detail(instance, MockService(), "foyer")
        assert result == "You see nothing special."

    async def test_interpolates_name_in_descriptions(self):
        """Interpolates {name} placeholder in descriptions."""
        entity = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {name}",
            description_long="The {name} looks sturdy.",
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            contents_visible=None,
            spawn_mode="none",
        )
        instance = EntityInstance(
            instance_id=uuid4(),
            entity=entity,
            room="foyer",
            owner_id=None,
        )

        result = await format_entity_detail(instance, MockService(), "foyer")
        assert "The *Wooden Table* looks sturdy." in result
