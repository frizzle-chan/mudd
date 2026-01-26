"""Tests for entity rendering via RenderingService.

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

from mudd.services.entity import EntityInstance, ResolvedEntity
from mudd.services.rendering import RenderingService


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
        on_drop=None,
        contents_visible=None,
        focus_mode="none",
        rarity="none",
    )


@pytest.fixture
def rendering_service() -> RenderingService:
    """Create a RenderingService for tests."""
    return RenderingService()


class TestRender:
    """Test render method on RenderingService."""

    def test_renders_name_template(self, rendering_service):
        """The {{ name }} template variable is replaced with formatted name."""
        entity = make_entity(name="Wooden Table", description_short="a {{ name }}")
        result = rendering_service.render("a {{ name }} sits here", entity)
        assert result == "a *Wooden Table* sits here"

    def test_handles_multiple_name_references(self, rendering_service):
        """Multiple {{ name }} references are all replaced."""
        entity = make_entity(name="Flower Vase")
        result = rendering_service.render("the {{ name }} is a nice {{ name }}", entity)
        assert result == "the *Flower Vase* is a nice *Flower Vase*"

    def test_renders_rarity_emoji_in_name(self, rendering_service):
        """Entity name includes rarity emoji when rarity is not 'none'."""
        entity = ResolvedEntity(
            id="gem",
            name="Ruby",
            description_short="a {{ name }}",
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            on_open=None,
            on_close=None,
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="rare",
        )
        result = rendering_service.render("You found {{ name }}!", entity)
        assert result == "You found *Ruby 🔵*!"

    def test_handles_no_template_variables(self, rendering_service):
        """Template without variables is returned unchanged."""
        entity = make_entity(name="Wooden Table")
        result = rendering_service.render("a simple table", entity)
        assert result == "a simple table"

    def test_handles_none_template(self, rendering_service):
        """None template returns empty string."""
        entity = make_entity(name="Wooden Table")
        result = rendering_service.render(None, entity)
        assert result == ""

    def test_renders_entity_properties(self, rendering_service):
        """Can access entity properties via e variable."""
        entity = make_entity(description_long="A sturdy table.")
        result = rendering_service.render("{{ e.description_long }}", entity)
        assert result == "A sturdy table."


class TestBuildContentsString:
    """Test build_contents_string method."""

    def test_empty_list_returns_empty_string(self, rendering_service):
        """Empty contents list returns empty string."""
        result = rendering_service.build_contents_string([])
        assert result == ""

    def test_single_item_space_prefixed(self, rendering_service):
        """Single item returns space-prefixed description."""
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
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="none",
        )
        contents = [
            EntityInstance(
                instance_id=uuid4(), entity=vase, room="foyer", owner_id=None
            ),
        ]

        result = rendering_service.build_contents_string(contents)
        assert result == " a *Flower Vase*"

    def test_two_items_joined_with_and(self, rendering_service):
        """Two items are joined with 'and', second lowercased."""
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
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="none",
        )
        plaque = ResolvedEntity(
            id="plaque",
            name="Inscribed Plaque",
            description_short="An {{ name }}",  # Starts with capital
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            on_open=None,
            on_close=None,
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="none",
        )
        contents = [
            EntityInstance(
                instance_id=uuid4(), entity=vase, room="foyer", owner_id=None
            ),
            EntityInstance(
                instance_id=uuid4(), entity=plaque, room="foyer", owner_id=None
            ),
        ]

        result = rendering_service.build_contents_string(contents)
        # Second item "An" should be lowercased to "an"
        assert result == " a *Flower Vase* and an *Inscribed Plaque*"

    def test_three_items_bullet_list(self, rendering_service):
        """Three or more items returns bullet list."""
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
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="none",
        )
        plaque = ResolvedEntity(
            id="plaque",
            name="Inscribed Plaque",
            description_short="an {{ name }}",
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            on_open=None,
            on_close=None,
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="none",
        )
        book = ResolvedEntity(
            id="book",
            name="Old Book",
            description_short="an {{ name }}",
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            on_open=None,
            on_close=None,
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="none",
        )
        contents = [
            EntityInstance(
                instance_id=uuid4(), entity=vase, room="foyer", owner_id=None
            ),
            EntityInstance(
                instance_id=uuid4(), entity=plaque, room="foyer", owner_id=None
            ),
            EntityInstance(
                instance_id=uuid4(), entity=book, room="foyer", owner_id=None
            ),
        ]

        result = rendering_service.build_contents_string(contents)
        assert result == "\n- a *Flower Vase*\n- an *Inscribed Plaque*\n- an *Old Book*"

    def test_skips_items_with_empty_description(self, rendering_service):
        """Items with empty rendered descriptions are skipped."""
        empty = ResolvedEntity(
            id="empty",
            name="Empty",
            description_short="",  # Empty description
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            on_open=None,
            on_close=None,
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="none",
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
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="none",
        )
        contents = [
            EntityInstance(
                instance_id=uuid4(), entity=empty, room="foyer", owner_id=None
            ),
            EntityInstance(
                instance_id=uuid4(), entity=vase, room="foyer", owner_id=None
            ),
        ]

        result = rendering_service.build_contents_string(contents)
        # Empty item skipped, only vase remains (single item format)
        assert result == " a *Flower Vase*"


class TestFormatEntityWithContents:
    """Test format_entity_with_contents method."""

    def test_entity_without_contents(self, rendering_service):
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
            on_drop=None,
            contents_visible=True,
            focus_mode="none",
            rarity="none",
        )
        result = rendering_service.format_entity_with_contents(entity, None)
        assert result == "a *Wooden Table* sits here"

    def test_entity_with_empty_contents(self, rendering_service):
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
            on_drop=None,
            contents_visible=True,
            focus_mode="none",
            rarity="none",
        )
        result = rendering_service.format_entity_with_contents(entity, [])
        assert result == "a *Wooden Table* sits here"

    def test_entity_with_contents_uses_template(self, rendering_service):
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
            on_drop=None,
            contents_visible=True,
            focus_mode="none",
            rarity="none",
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
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="none",
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
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="none",
        )
        contents = [
            EntityInstance(
                instance_id=uuid4(), entity=vase, room="foyer", owner_id=None
            ),
            EntityInstance(
                instance_id=uuid4(), entity=plaque, room="foyer", owner_id=None
            ),
        ]

        result = rendering_service.format_entity_with_contents(table, contents)
        # 2 items: space-prefixed, joined with "and", second lowercased
        assert result == (
            "a *Wooden Table*. On it: a *Flower Vase* and a *Inscribed Plaque*"
        )

    def test_contents_variable_empty_when_no_contents(self, rendering_service):
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
            on_drop=None,
            contents_visible=True,
            focus_mode="none",
            rarity="none",
        )
        result = rendering_service.format_entity_with_contents(entity, [])
        assert result == "a *Wooden Table*[]"

    def test_malformed_content_template_uses_fallback(self, rendering_service):
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
            on_drop=None,
            contents_visible=True,
            focus_mode="none",
            rarity="none",
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
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="none",
        )
        contents = [
            EntityInstance(
                instance_id=uuid4(), entity=vase, room="foyer", owner_id=None
            ),
        ]

        result = rendering_service.format_entity_with_contents(table, contents)
        # Should fall back to entity name
        assert "*Broken Vase*" in result


@pytest.mark.asyncio
class TestFormatRoomEntities:
    """Test format_room_entities method."""

    async def test_empty_entities_returns_empty_string(self, rendering_service):
        """No entities returns empty string."""
        result = await rendering_service.format_room_entities(
            [], MockService(), "foyer"
        )
        assert result == ""

    async def test_single_entity_no_contents(self, rendering_service):
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
            on_drop=None,
            contents_visible=False,  # Not visible
            focus_mode="none",
            rarity="none",
        )
        entities = [
            EntityInstance(
                instance_id=uuid4(), entity=table, room="foyer", owner_id=None
            ),
        ]

        result = await rendering_service.format_room_entities(
            entities, MockService(), "foyer"
        )
        assert result == "a *Wooden Table* sits here"

    async def test_entity_with_visible_contents(self, rendering_service):
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
            on_drop=None,
            contents_visible=True,
            focus_mode="none",
            rarity="none",
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
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="none",
        )
        entities = [
            EntityInstance(
                instance_id=uuid4(), entity=table, room="foyer", owner_id=None
            ),
        ]

        class MockServiceWithContents:
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

        result = await rendering_service.format_room_entities(
            entities, MockServiceWithContents(), "foyer"
        )
        # 1 item: space-prefixed, no case change
        assert result == "a *Wooden Table* sits here. On it: a *Flower Vase*"

    async def test_multiple_entities(self, rendering_service):
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
            on_drop=None,
            contents_visible=False,
            focus_mode="none",
            rarity="none",
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
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="none",
        )
        entities = [
            EntityInstance(
                instance_id=uuid4(), entity=table, room="foyer", owner_id=None
            ),
            EntityInstance(
                instance_id=uuid4(), entity=chair, room="foyer", owner_id=None
            ),
        ]

        result = await rendering_service.format_room_entities(
            entities, MockService(), "foyer"
        )
        assert result == ("a *Wooden Table* sits here\nan *Old Chair* is in the corner")


@pytest.mark.asyncio
class TestRenderEntityOnLook:
    """Tests for render_entity_on_look method."""

    async def test_renders_on_look_template(self, rendering_service):
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
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="none",
        )
        instance = EntityInstance(
            instance_id=uuid4(),
            entity=entity,
            room="foyer",
            owner_id=None,
        )

        result = await rendering_service.render_entity_on_look(
            instance, MockService(), "foyer"
        )
        expected = (
            "### Wooden Table\n\nYou examine the *Wooden Table*. A sturdy oak table."
        )
        assert result == expected

    async def test_falls_back_to_description_when_no_on_look(self, rendering_service):
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
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="none",
        )
        instance = EntityInstance(
            instance_id=uuid4(),
            entity=entity,
            room="foyer",
            owner_id=None,
        )

        result = await rendering_service.render_entity_on_look(
            instance, MockService(), "foyer"
        )
        assert result == "### Wooden Table\n\nA sturdy oak table with worn edges."

    async def test_falls_back_to_description_short(self, rendering_service):
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
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="none",
        )
        instance = EntityInstance(
            instance_id=uuid4(),
            entity=entity,
            room="foyer",
            owner_id=None,
        )

        result = await rendering_service.render_entity_on_look(
            instance, MockService(), "foyer"
        )
        assert result == "### Wooden Table\n\na *Wooden Table* sits here"

    async def test_shows_error_warning_on_bad_template(self, rendering_service):
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
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="none",
        )
        instance = EntityInstance(
            instance_id=uuid4(),
            entity=entity,
            room="foyer",
            owner_id=None,
        )

        result = await rendering_service.render_entity_on_look(
            instance, MockService(), "foyer"
        )
        assert "A sturdy table." in result
        assert "-# (error rendering template)" in result

    async def test_includes_container_contents(self, rendering_service):
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
            on_drop=None,
            contents_visible=True,
            focus_mode="none",
            rarity="none",
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
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="none",
        )
        vase_instance = EntityInstance(
            instance_id=uuid4(),
            entity=vase_entity,
            room="foyer",
            owner_id=None,
        )

        mock_service = MockService([vase_instance])
        result = await rendering_service.render_entity_on_look(
            table_instance, mock_service, "foyer"
        )

        assert "A sturdy oak table." in result
        assert "On it:" in result
        # 1 item: no case change (uses description_short, not on_look)
        assert "a teal *Flower Vase*" in result

    async def test_returns_default_when_no_descriptions(self, rendering_service):
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
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="none",
        )
        instance = EntityInstance(
            instance_id=uuid4(),
            entity=entity,
            room="foyer",
            owner_id=None,
        )

        result = await rendering_service.render_entity_on_look(
            instance, MockService(), "foyer"
        )
        assert result == "### Blank\n\nYou see nothing special."

    async def test_contents_uses_description_short(self, rendering_service):
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
            on_drop=None,
            contents_visible=True,
            focus_mode="none",
            rarity="none",
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
            on_drop=None,
            contents_visible=None,
            focus_mode="none",
            rarity="none",
        )
        vase_instance = EntityInstance(
            instance_id=uuid4(),
            entity=vase_entity,
            room="foyer",
            owner_id=None,
        )

        mock_service = MockService([vase_instance])
        result = await rendering_service.render_entity_on_look(
            table_instance, mock_service, "foyer"
        )

        assert "A sturdy oak table." in result
        assert "On it:" in result
        # 1 item: no case change (uses description_short, not on_look)
        assert "a *Flower Vase*" in result
        assert "examine the vase closely" not in result  # on_look NOT used
