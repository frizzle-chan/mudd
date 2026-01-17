"""Tests for template renderer."""

import pytest

from mudd.services.entity import ResolvedEntity
from mudd.templating import TemplateRenderError, clear_cache, render
from mudd.templating.renderer import TemplateRenderer


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


class TestRender:
    """Tests for public render() function."""

    def test_simple_template_renders(self):
        """Simple template text renders correctly."""
        entity = make_entity()
        result = render("Hello world", entity)
        assert result == "Hello world"

    def test_template_with_name_variable(self):
        """Template can use {{ name }} variable."""
        entity = make_entity()
        result = render("You look at the {{ name }}.", entity)
        assert result == "You look at the *Test Entity*."

    def test_template_with_entity_properties(self):
        """Template can access entity properties via e."""
        entity = make_entity(description_long="A sturdy table.")
        result = render("{{ e.description_long }}", entity)
        assert result == "A sturdy table."

    def test_template_with_conditional(self):
        """Template can use Jinja conditionals."""
        entity = make_entity(description_long="Detailed text.")
        template = (
            "{% if e.description_long %}{{ e.description_long }}"
            "{% else %}Nothing special.{% endif %}"
        )
        result = render(template, entity)
        assert result == "Detailed text."

    def test_template_with_or_fallback(self):
        """Template can use or for fallback values."""
        entity = make_entity(description_long=None, description_short="Short desc.")
        template = "{{ e.description_long or e.description_short or 'Nothing.' }}"
        result = render(template, entity)
        assert result == "Short desc."

    def test_none_template_returns_empty_string(self):
        """None template returns empty string."""
        entity = make_entity()
        result = render(None, entity)
        assert result == ""

    def test_syntax_error_raises_exception(self):
        """Template syntax error raises TemplateRenderError."""
        entity = make_entity()
        with pytest.raises(TemplateRenderError):
            render("{% if %}broken{% endif %}", entity)

    def test_undefined_variable_raises_exception(self):
        """Undefined variable raises TemplateRenderError."""
        entity = make_entity()
        with pytest.raises(TemplateRenderError):
            render("{{ undefined_var }}", entity)

    def test_contents_variable_available(self):
        """Template can use {{ contents }} variable."""
        entity = make_entity()
        result = render("Items:{{ contents }}", entity, contents="\n- a *Vase*")
        assert result == "Items:\n- a *Vase*"

    def test_contents_defaults_to_empty_string(self):
        """{{ contents }} is empty string when not provided."""
        entity = make_entity()
        result = render("[{{ contents }}]", entity)
        assert result == "[]"


class TestTemplateRenderer:
    """Tests for internal TemplateRenderer class."""

    def test_template_caching(self):
        """Same template source uses cached compiled template."""
        renderer = TemplateRenderer()
        entity = make_entity()
        template_source = "Cached template {{ name }}"

        renderer.render(template_source, entity, "*Test*")
        assert template_source in renderer._cache

        # Second render uses cache
        renderer.render(template_source, entity, "*Test2*")
        assert len(renderer._cache) == 1

    def test_clear_cache(self):
        """clear_cache removes all cached templates."""
        renderer = TemplateRenderer()
        entity = make_entity()

        renderer.render("Template 1", entity, "*Test*")
        renderer.render("Template 2", entity, "*Test*")
        assert len(renderer._cache) == 2

        renderer.clear_cache()
        assert len(renderer._cache) == 0


class TestClearCache:
    """Tests for public clear_cache() function."""

    def test_clear_cache_function(self):
        """clear_cache() clears the singleton renderer's cache."""
        entity = make_entity()

        # Render some templates to populate cache
        render("Template A", entity)
        render("Template B", entity)

        # Clear and verify no exception
        clear_cache()
