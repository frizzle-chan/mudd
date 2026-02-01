"""Simple Jinja2 template rendering for action commands."""

from typing import Any

from jinja2 import (
    Environment,
    StrictUndefined,
    Template,
    TemplateError,
    select_autoescape,
)


class TemplateRenderError(Exception):
    """Raised when a template fails to render."""

    pass


_env = Environment(
    autoescape=select_autoescape(default_for_string=False),
    undefined=StrictUndefined,
)
_cache: dict[str, Template] = {}


def render(template: str, context: dict[str, Any]) -> str:
    """Render a Jinja2 template with the given context.

    Args:
        template: Jinja2 template string
        context: Variables available in the template

    Returns:
        Rendered template output

    Raises:
        TemplateRenderError: If the template fails to compile or render
    """
    try:
        if template not in _cache:
            _cache[template] = _env.from_string(template)
        return _cache[template].render(context)
    except TemplateError as e:
        raise TemplateRenderError(f"Template render failed: {e}") from e


def clear_cache() -> None:
    """Clear the template cache."""
    _cache.clear()
