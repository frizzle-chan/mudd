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


def _money_filter(value: int) -> str:
    """Format an integer as a yen currency string."""
    return f"¥{value:,}"


def _md_list_filter(items: list[object]) -> str:
    """Format a list of objects as a markdown bullet list."""
    if not items:
        return ""
    return "\n".join(f"- {item}" for item in items)


_env = Environment(
    autoescape=select_autoescape(default_for_string=False),
    undefined=StrictUndefined,
    enable_async=True,
)
_env.filters["money"] = _money_filter
_env.filters["md_list"] = _md_list_filter
_cache: dict[str, Template] = {}


async def render(template: str, context: dict[str, Any]) -> str:
    """Render a Jinja2 template asynchronously with the given context.

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
        return await _cache[template].render_async(context)
    except TemplateError as e:
        raise TemplateRenderError(f"Template render failed: {e}") from e
