"""Tests for entity formatting.

Tests:
1. format_entity_with_contents formats entity without contents
2. format_entity_with_contents formats entity with nested contents
3. format_room_entities returns empty string for no entities
4. format_room_entities formats multiple entities
5. format_entity_detail shows entity details
6. render_entity_on_look renders on_look templates
"""

from uuid import uuid4

import pytest

from mudd.formatting.entities import (
    format_entity_with_contents,
    format_room_entities,
    render_entity_on_look,
)
from mudd.services.entity import EntityInstance, ResolvedEntity
from mudd.templating import render


class MockService:
    """Mock entity service for testing."""

    def __init__(self, contents: list[EntityInstance] | None = None):
        self._contents = contents or []

    async def get_container_contents(
        self, container_id: str, room: str
    ) -> list[EntityInstance]:
        return self._contents


def make_entity(
    entity_id: str = "test",
    name: str = "Test Entity",
    description_short: str | None = "a {{ name }}",
    description_long: str | None = None,
) -> ResolvedEntity:
    """Create a test entity."""
    return ResolvedEntity(
        id=entity_id,
        name=name,
        description_short=description_short,
        description_long=description_long,
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


class TestRender:
    """Test render function from mudd.templating."""

    def test_renders_name_template(self):
        """The {{ name }} template variable is replaced with formatted name."""
        entity = make_entity(name="Wooden Table", description_short="a {{ name }}")
        result = render("a {{ name }} sits here", entity)
        assert result == "a *Wooden Table* sits here"

    def test_handles_multiple_name_references(self):
        """Multiple {{ name }} references are all replaced."""
        entity = make_entity(name="Flower Vase")
        result = render("the {{ name }} is a nice {{ name }}", entity)
        assert result == "the *Flower Vase* is a nice *Flower Vase*"

    def test_handles_no_template_variables(self):
        """Template without variables is returned unchanged."""
        entity = make_entity(name="Wooden Table")
        result = render("a simple table", entity)
        assert result == "a simple table"

    def test_handles_none_template(self):
        """None template returns empty string."""
        entity = make_entity(name="Wooden Table")
        result = render(None, entity)
        assert result == ""

    def test_renders_entity_properties(self):
        """Can access entity properties via e variable."""
        entity = make_entity(description_long="A sturdy table.")
        result = render("{{ e.description_long }}", entity)
        assert result == "A sturdy table."


class TestFormatEntityWithContents:
    """Test format_entity_with_contents function."""

    def test_entity_without_contents(self):
        """Entity without contents shows only its description."""
        entity = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {{ name }} sits here",
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
            focus_mode="none",
        )
        result = format_entity_with_contents(entity, None)
        assert result == "a *Wooden Table* sits here"

    def test_entity_with_empty_contents(self):
        """Entity with empty contents list shows only its description."""
        entity = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {{ name }} sits here",
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
            focus_mode="none",
        )
        result = format_entity_with_contents(entity, [])
        assert result == "a *Wooden Table* sits here"

    def test_entity_with_contents_uses_template(self):
        """Entity with contents passes {{ contents }} to template."""
        table = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {{ name }}. On it:{{ contents }}",
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
            focus_mode="none",
        )
        vase = ResolvedEntity(
            id="vase",
            name="Flower Vase",
            description_short="a {{ name }}",
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
        plaque = ResolvedEntity(
            id="plaque",
            name="Inscribed Plaque",
            description_short="a {{ name }}",
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
            "a *Wooden Table*. On it:\n- a *Flower Vase*\n- a *Inscribed Plaque*"
        )

    def test_contents_variable_empty_when_no_contents(self):
        """The {{ contents }} variable is empty string when no contents."""
        entity = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {{ name }}[{{ contents }}]",  # Brackets show empty
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
            focus_mode="none",
        )
        result = format_entity_with_contents(entity, [])
        assert result == "a *Wooden Table*[]"

    def test_malformed_content_template_uses_fallback(self):
        """Malformed item template falls back to entity name."""
        table = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {{ name }}. On it:{{ contents }}",
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
            focus_mode="none",
        )
        # Vase has broken template
        vase = ResolvedEntity(
            id="vase",
            name="Broken Vase",
            description_short="{% if %}broken{% endif %}",  # Syntax error
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
        contents = [
            EntityInstance(
                instance_id=uuid4(), entity=vase, room="foyer", owner_id=None
            ),
        ]

        result = format_entity_with_contents(table, contents)
        # Should fall back to entity name
        assert "*Broken Vase*" in result


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
            description_short="a {{ name }} sits here",
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            on_open=None,
            on_close=None,
            contents_visible=False,  # Not visible
            spawn_mode="none",
            focus_mode="none",
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
            description_short=(
                "a {{ name }} sits here"
                "{% if contents %}. On it:{{ contents }}{% endif %}"
            ),
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
            focus_mode="none",
        )
        vase = ResolvedEntity(
            id="vase",
            name="Flower Vase",
            description_short="a {{ name }}",
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
        assert result == "a *Wooden Table* sits here. On it:\n- a *Flower Vase*"

    async def test_multiple_entities(self):
        """Multiple top-level entities are joined with newlines."""
        table = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {{ name }} sits here",
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            on_open=None,
            on_close=None,
            contents_visible=False,
            spawn_mode="none",
            focus_mode="none",
        )
        chair = ResolvedEntity(
            id="chair",
            name="Old Chair",
            description_short="an {{ name }} is in the corner",
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
class TestRenderEntityOnLook:
    """Tests for render_entity_on_look function."""

    async def test_renders_on_look_template(self):
        """Renders on_look template with entity context."""
        entity = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {{ name }}",
            description_long="A sturdy oak table.",
            on_look="You examine the {{ name }}. {{ e.description_long }}",
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
        instance = EntityInstance(
            instance_id=uuid4(),
            entity=entity,
            room="foyer",
            owner_id=None,
        )

        result = await render_entity_on_look(instance, MockService(), "foyer")
        assert result == "You examine the *Wooden Table*. A sturdy oak table."

    async def test_falls_back_to_description_when_no_on_look(self):
        """Falls back to description_long when on_look is None."""
        entity = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {{ name }}",
            description_long="A sturdy oak table with worn edges.",
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
        instance = EntityInstance(
            instance_id=uuid4(),
            entity=entity,
            room="foyer",
            owner_id=None,
        )

        result = await render_entity_on_look(instance, MockService(), "foyer")
        assert result == "A sturdy oak table with worn edges."

    async def test_falls_back_to_description_short(self):
        """Falls back to description_short when description_long is None."""
        entity = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {{ name }} sits here",
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
        instance = EntityInstance(
            instance_id=uuid4(),
            entity=entity,
            room="foyer",
            owner_id=None,
        )

        result = await render_entity_on_look(instance, MockService(), "foyer")
        assert result == "a *Wooden Table* sits here"

    async def test_shows_error_warning_on_bad_template(self):
        """Shows error warning when template has syntax error."""
        entity = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {{ name }}",
            description_long="A sturdy table.",
            on_look="{% if %}broken{% endif %}",
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
        instance = EntityInstance(
            instance_id=uuid4(),
            entity=entity,
            room="foyer",
            owner_id=None,
        )

        result = await render_entity_on_look(instance, MockService(), "foyer")
        assert "A sturdy table." in result
        assert "-# (error rendering template)" in result

    async def test_includes_container_contents(self):
        """Shows container contents via {{ contents }} template variable."""
        table_entity = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {{ name }}",
            description_long="A sturdy oak table.",
            on_look=(
                "{{ e.description_long }}"
                "{% if contents %}\n\nOn it:{{ contents }}{% endif %}"
            ),
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            on_open=None,
            on_close=None,
            contents_visible=True,
            spawn_mode="none",
            focus_mode="none",
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
            description_short="a teal {{ name }}",
            description_long="A teal ceramic vase.",
            on_look="{{ e.description_long }}",
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
        vase_instance = EntityInstance(
            instance_id=uuid4(),
            entity=vase_entity,
            room="foyer",
            owner_id=None,
        )

        mock_service = MockService([vase_instance])
        result = await render_entity_on_look(table_instance, mock_service, "foyer")

        assert "A sturdy oak table." in result
        assert "On it:" in result
        assert "a teal *Flower Vase*" in result  # Uses description_short

    async def test_returns_default_when_no_descriptions(self):
        """Returns default message when entity has no descriptions or on_look."""
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
            on_open=None,
            on_close=None,
            contents_visible=None,
            spawn_mode="none",
            focus_mode="none",
        )
        instance = EntityInstance(
            instance_id=uuid4(),
            entity=entity,
            room="foyer",
            owner_id=None,
        )

        result = await render_entity_on_look(instance, MockService(), "foyer")
        assert result == "You see nothing special."

    async def test_contents_uses_description_short(self):
        """Contents are rendered using description_short, not on_look."""
        table_entity = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {{ name }}",
            description_long="A sturdy oak table.",
            on_look=(
                "{{ e.description_long }}"
                "{% if contents %}\n\nOn it:{{ contents }}{% endif %}"
            ),
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            on_open=None,
            on_close=None,
            contents_visible=True,
            spawn_mode="none",
            focus_mode="none",
        )
        table_instance = EntityInstance(
            instance_id=uuid4(),
            entity=table_entity,
            room="foyer",
            owner_id=None,
        )

        # Vase has on_look that's different from description_short
        vase_entity = ResolvedEntity(
            id="vase",
            name="Flower Vase",
            description_short="a {{ name }}",
            description_long="A teal ceramic vase.",
            on_look="You examine the vase closely.",  # NOT used in contents
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
        vase_instance = EntityInstance(
            instance_id=uuid4(),
            entity=vase_entity,
            room="foyer",
            owner_id=None,
        )

        mock_service = MockService([vase_instance])
        result = await render_entity_on_look(table_instance, mock_service, "foyer")

        assert "A sturdy oak table." in result
        assert "On it:" in result
        assert "a *Flower Vase*" in result  # Uses description_short
        assert "examine the vase closely" not in result  # on_look NOT used
