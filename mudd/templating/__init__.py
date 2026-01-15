"""Jinja2 templating for entity triggers."""

from mudd.services.entity import ResolvedEntity
from mudd.templating.renderer import TemplateRenderer, TemplateRenderError

__all__ = ["render", "clear_cache", "TemplateRenderError"]


_renderer: TemplateRenderer | None = None


def _get_renderer() -> TemplateRenderer:
    """Get or create the singleton renderer."""
    global _renderer
    if _renderer is None:
        _renderer = TemplateRenderer()
    return _renderer


def render(template: str | None, entity: ResolvedEntity, contents: str = "") -> str:
    """Render a Jinja2 template with entity context.

    Template context:
        - `e`: The ResolvedEntity
        - `name`: Entity name formatted with Discord italics (*Name*)
        - `contents`: Pre-formatted bullet list of container contents (empty if none)

    Args:
        template: Jinja2 template string (or None)
        entity: The entity providing context
        contents: Pre-formatted bullet list of contents (default: "")

    Returns:
        Rendered string, or empty string if template is None

    Raises:
        TemplateRenderError: If template has syntax errors or undefined variables
    """
    if template is None:
        return ""
    name_formatted = f"*{entity.name}*"
    return _get_renderer().render(template, entity, name_formatted, contents)


def clear_cache() -> None:
    """Clear the template cache."""
    _get_renderer().clear_cache()
