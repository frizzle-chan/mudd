"""Tests for template renderer."""

import pytest

from mudd.services.entity import ResolvedEntity
from mudd.services.rendering import (
    RenderingService,
    TemplateRenderer,
    TemplateRenderError,
)


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
        contents_visible=None,
        spawn_mode="none",
        focus_mode="none",
    )


@pytest.fixture
def rendering_service() -> RenderingService:
    """Create a RenderingService for tests."""
    return RenderingService()


class TestRender:
    """Tests for RenderingService.render() method."""

    def test_simple_template_renders(self, rendering_service):
        """Simple template text renders correctly."""
        entity = make_entity()
        result = rendering_service.render("Hello world", entity)
        assert result == "Hello world"

    def test_template_with_name_variable(self, rendering_service):
        """Template can use {{ name }} variable."""
        entity = make_entity()
        result = rendering_service.render("You look at the {{ name }}.", entity)
        assert result == "You look at the *Test Entity*."

    def test_template_with_entity_properties(self, rendering_service):
        """Template can access entity properties via e."""
        entity = make_entity(description_long="A sturdy table.")
        result = rendering_service.render("{{ e.description_long }}", entity)
        assert result == "A sturdy table."

    def test_template_with_conditional(self, rendering_service):
        """Template can use Jinja conditionals."""
        entity = make_entity(description_long="Detailed text.")
        template = (
            "{% if e.description_long %}{{ e.description_long }}"
            "{% else %}Nothing special.{% endif %}"
        )
        result = rendering_service.render(template, entity)
        assert result == "Detailed text."

    def test_template_with_or_fallback(self, rendering_service):
        """Template can use or for fallback values."""
        entity = make_entity(description_long=None, description_short="Short desc.")
        template = "{{ e.description_long or e.description_short or 'Nothing.' }}"
        result = rendering_service.render(template, entity)
        assert result == "Short desc."

    def test_none_template_returns_empty_string(self, rendering_service):
        """None template returns empty string."""
        entity = make_entity()
        result = rendering_service.render(None, entity)
        assert result == ""

    def test_syntax_error_raises_exception(self, rendering_service):
        """Template syntax error raises TemplateRenderError."""
        entity = make_entity()
        with pytest.raises(TemplateRenderError):
            rendering_service.render("{% if %}broken{% endif %}", entity)

    def test_undefined_variable_raises_exception(self, rendering_service):
        """Undefined variable raises TemplateRenderError."""
        entity = make_entity()
        with pytest.raises(TemplateRenderError):
            rendering_service.render("{{ undefined_var }}", entity)

    def test_contents_variable_available(self, rendering_service):
        """Template can use {{ contents }} variable."""
        entity = make_entity()
        result = rendering_service.render(
            "Items:{{ contents }}", entity, contents="\n- a *Vase*"
        )
        assert result == "Items:\n- a *Vase*"

    def test_contents_defaults_to_empty_string(self, rendering_service):
        """{{ contents }} is empty string when not provided."""
        entity = make_entity()
        result = rendering_service.render("[{{ contents }}]", entity)
        assert result == "[]"


class TestTemplateRenderer:
    """Tests for internal TemplateRenderer class."""

    def test_template_caching(self):
        """Same template source uses cached compiled template."""
        renderer = TemplateRenderer()
        entity = make_entity()
        template_source = "Cached template {{ name }}"

        renderer.render_template(template_source, entity, "*Test*")
        assert template_source in renderer._cache

        # Second render uses cache
        renderer.render_template(template_source, entity, "*Test2*")
        assert len(renderer._cache) == 1

    def test_clear_cache(self):
        """clear_cache removes all cached templates."""
        renderer = TemplateRenderer()
        entity = make_entity()

        renderer.render_template("Template 1", entity, "*Test*")
        renderer.render_template("Template 2", entity, "*Test*")
        assert len(renderer._cache) == 2

        renderer.clear_cache()
        assert len(renderer._cache) == 0


class TestRenderingServiceClearCache:
    """Tests for RenderingService.clear_cache() method."""

    def test_clear_cache_method(self, rendering_service):
        """clear_cache() clears the renderer's template cache."""
        entity = make_entity()

        # Render some templates to populate cache
        rendering_service.render("Template A", entity)
        rendering_service.render("Template B", entity)

        # Clear and verify no exception
        rendering_service.clear_cache()
