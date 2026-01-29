"""Tests for template renderer."""

import pytest

from mudd.services.entity import ResolvedEntity
from mudd.services.rendering import (
    RenderingService,
    TemplateRenderer,
    TemplateRenderError,
)
from mudd.types import UserContext


def make_entity(
    entity_id: str = "test",
    name: str = "Test Entity",
    description_short: str | None = "a {{ name }}",
    description_long: str | None = "A detailed description.",
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
    """Tests for RenderingService.render() method."""

    async def test_simple_template_renders(self, rendering_service):
        """Simple template text renders correctly."""
        entity = make_entity()
        result = await rendering_service.render("Hello world", entity)
        assert result == "Hello world"

    async def test_template_with_name_variable(self, rendering_service):
        """Template can use {{ name }} variable."""
        entity = make_entity()
        result = await rendering_service.render("You look at the {{ name }}.", entity)
        assert result == "You look at the *Test Entity*."

    async def test_template_with_entity_properties(self, rendering_service):
        """Template can access entity properties via e."""
        entity = make_entity(description_long="A sturdy table.")
        result = await rendering_service.render("{{ e.description_long }}", entity)
        assert result == "A sturdy table."

    async def test_template_with_conditional(self, rendering_service):
        """Template can use Jinja conditionals."""
        entity = make_entity(description_long="Detailed text.")
        template = (
            "{% if e.description_long %}{{ e.description_long }}"
            "{% else %}Nothing special.{% endif %}"
        )
        result = await rendering_service.render(template, entity)
        assert result == "Detailed text."

    async def test_template_with_or_fallback(self, rendering_service):
        """Template can use or for fallback values."""
        entity = make_entity(description_long=None, description_short="Short desc.")
        template = "{{ e.description_long or e.description_short or 'Nothing.' }}"
        result = await rendering_service.render(template, entity)
        assert result == "Short desc."

    async def test_none_template_returns_empty_string(self, rendering_service):
        """None template returns empty string."""
        entity = make_entity()
        result = await rendering_service.render(None, entity)
        assert result == ""

    async def test_syntax_error_raises_exception(self, rendering_service):
        """Template syntax error raises TemplateRenderError."""
        entity = make_entity()
        with pytest.raises(TemplateRenderError):
            await rendering_service.render("{% if %}broken{% endif %}", entity)

    async def test_undefined_variable_raises_exception(self, rendering_service):
        """Undefined variable raises TemplateRenderError."""
        entity = make_entity()
        with pytest.raises(TemplateRenderError):
            await rendering_service.render("{{ undefined_var }}", entity)

    async def test_contents_variable_available(self, rendering_service):
        """Template can use {{ contents }} variable."""
        entity = make_entity()
        result = await rendering_service.render(
            "Items:{{ contents }}", entity, contents="\n- a *Vase*"
        )
        assert result == "Items:\n- a *Vase*"

    async def test_contents_defaults_to_empty_string(self, rendering_service):
        """{{ contents }} is empty string when not provided."""
        entity = make_entity()
        result = await rendering_service.render("[{{ contents }}]", entity)
        assert result == "[]"


class TestTemplateRenderer:
    """Tests for internal TemplateRenderer class."""

    async def test_template_caching(self):
        """Same template source uses cached compiled template."""
        renderer = TemplateRenderer()
        entity = make_entity()
        template_source = "Cached template {{ name }}"

        await renderer.render_template(template_source, entity, "*Test*")
        assert template_source in renderer._cache

        # Second render uses cache
        await renderer.render_template(template_source, entity, "*Test2*")
        assert len(renderer._cache) == 1

    async def test_clear_cache(self):
        """clear_cache removes all cached templates."""
        renderer = TemplateRenderer()
        entity = make_entity()

        await renderer.render_template("Template 1", entity, "*Test*")
        await renderer.render_template("Template 2", entity, "*Test*")
        assert len(renderer._cache) == 2

        renderer.clear_cache()
        assert len(renderer._cache) == 0


class TestRenderingServiceClearCache:
    """Tests for RenderingService.clear_cache() method."""

    async def test_clear_cache_method(self, rendering_service):
        """clear_cache() clears the renderer's template cache."""
        entity = make_entity()

        # Render some templates to populate cache
        await rendering_service.render("Template A", entity)
        await rendering_service.render("Template B", entity)

        # Clear and verify no exception
        rendering_service.clear_cache()


class TestRenderWithEffects:
    """Tests for RenderingService.render_with_effects() method."""

    async def test_simple_template_returns_output_and_effects(self, rendering_service):
        """render_with_effects returns tuple of (output, effects)."""
        entity = make_entity()
        user = UserContext(name="Frizzle", mention="<@12345>")
        output, effects = await rendering_service.render_with_effects(
            "Hello world", entity, user
        )
        assert output == "Hello world"
        assert effects.broadcasts == []

    async def test_template_with_user_context(self, rendering_service):
        """Template can access user.name and user.mention."""
        entity = make_entity()
        user = UserContext(name="Frizzle", mention="<@12345>")
        output, effects = await rendering_service.render_with_effects(
            "Welcome {{ user.name }}!", entity, user
        )
        assert output == "Welcome Frizzle!"

    async def test_template_with_user_mention(self, rendering_service):
        """Template can use user.mention for @mentions."""
        entity = make_entity()
        user = UserContext(name="Frizzle", mention="<@12345>")
        output, effects = await rendering_service.render_with_effects(
            "{{ user.mention }} did something", entity, user
        )
        assert output == "<@12345> did something"

    async def test_template_with_broadcast_effect(self, rendering_service):
        """effects.broadcast() collects messages in effects.broadcasts."""
        entity = make_entity()
        user = UserContext(name="Frizzle", mention="<@12345>")
        template = '{{ effects.broadcast("**" ~ user.name ~ "** did it.") }}You did it!'
        output, effects = await rendering_service.render_with_effects(
            template, entity, user
        )
        assert output == "You did it!"
        assert effects.broadcasts == ["**Frizzle** did it."]

    async def test_template_with_multiple_broadcasts(self, rendering_service):
        """Multiple broadcast() calls collect all messages."""
        entity = make_entity()
        user = UserContext(name="Frizzle", mention="<@12345>")
        template = (
            '{{ effects.broadcast("First") }}{{ effects.broadcast("Second") }}Output'
        )
        output, effects = await rendering_service.render_with_effects(
            template, entity, user
        )
        assert output == "Output"
        assert effects.broadcasts == ["First", "Second"]

    async def test_none_template_returns_empty_output_and_effects(
        self, rendering_service
    ):
        """None template returns empty string and empty effects."""
        entity = make_entity()
        user = UserContext(name="Frizzle", mention="<@12345>")
        output, effects = await rendering_service.render_with_effects(
            None, entity, user
        )
        assert output == ""
        assert effects.broadcasts == []

    async def test_template_with_entity_and_user_context(self, rendering_service):
        """Template can use both entity (e) and user context."""
        entity = make_entity(description_long="A magical item.")
        user = UserContext(name="Frizzle", mention="<@12345>")
        template = "{{ user.name }} examines {{ name }}. {{ e.description_long }}"
        output, effects = await rendering_service.render_with_effects(
            template, entity, user
        )
        assert output == "Frizzle examines *Test Entity*. A magical item."

    async def test_template_with_contents(self, rendering_service):
        """Template can use contents variable."""
        entity = make_entity()
        user = UserContext(name="Frizzle", mention="<@12345>")
        output, effects = await rendering_service.render_with_effects(
            "Items:{{ contents }}", entity, user, contents="\n- a *Vase*"
        )
        assert output == "Items:\n- a *Vase*"

    async def test_syntax_error_raises_exception(self, rendering_service):
        """Template syntax error raises TemplateRenderError."""
        entity = make_entity()
        user = UserContext(name="Frizzle", mention="<@12345>")
        with pytest.raises(TemplateRenderError):
            await rendering_service.render_with_effects(
                "{% if %}broken{% endif %}", entity, user
            )

    async def test_undefined_variable_raises_exception(self, rendering_service):
        """Undefined variable raises TemplateRenderError."""
        entity = make_entity()
        user = UserContext(name="Frizzle", mention="<@12345>")
        with pytest.raises(TemplateRenderError):
            await rendering_service.render_with_effects(
                "{{ undefined_var }}", entity, user
            )
