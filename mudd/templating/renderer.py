"""Template rendering service for entity triggers."""

import logging

from jinja2 import (
    Environment,
    StrictUndefined,
    Template,
    TemplateSyntaxError,
    UndefinedError,
)

from mudd.services.entity import ResolvedEntity

logger = logging.getLogger(__name__)


class TemplateRenderError(Exception):
    """Raised when a template fails to render."""

    pass


class TemplateRenderer:
    """Renders Jinja2 templates for entity triggers.

    Provides template compilation with caching and error handling.
    Templates have access to:
        - `e`: The ResolvedEntity
        - `name`: Entity name formatted with Discord italics (*Name*)
        - `contents`: Pre-formatted bullet list of container contents (empty if none)

    Usage:
        renderer = TemplateRenderer()
        output = renderer.render(
            template_source=entity.on_look,
            entity=entity,
            name_formatted="*Wooden Table*",
            contents="\\n- a *Vase*\\n- a *Plaque*",
        )
    """

    def __init__(self) -> None:
        self._env = Environment(
            autoescape=False,  # Plain text output, not HTML
            undefined=StrictUndefined,  # Fail on undefined variables
        )
        self._cache: dict[str, Template] = {}  # template source -> compiled Template

    def render(
        self,
        template_source: str,
        entity: ResolvedEntity,
        name_formatted: str,
        contents: str = "",
    ) -> str:
        """Render a Jinja2 template with entity context.

        Args:
            template_source: Jinja2 template string
            entity: ResolvedEntity available as `e` in template
            name_formatted: Pre-formatted name (e.g., "*Wooden Table*")
            contents: Pre-formatted bullet list of contents (e.g., "\\n- a *Vase*")

        Returns:
            Rendered string

        Raises:
            TemplateRenderError: If template has syntax errors or undefined variables
        """
        try:
            template = self._get_or_compile(template_source)
            context = {"e": entity, "name": name_formatted, "contents": contents}
            return template.render(context)
        except TemplateSyntaxError as exc:
            logger.error(
                "Template syntax error in entity '%s': %s", entity.id, str(exc)
            )
            raise TemplateRenderError(str(exc)) from exc
        except UndefinedError as exc:
            logger.error(
                "Template undefined variable in entity '%s': %s", entity.id, str(exc)
            )
            raise TemplateRenderError(str(exc)) from exc
        except Exception as exc:
            logger.exception(
                "Unexpected template error in entity '%s': %s", entity.id, str(exc)
            )
            raise TemplateRenderError(str(exc)) from exc

    def _get_or_compile(self, template_source: str) -> Template:
        """Get cached template or compile and cache it.

        Templates are cached by source text, so entities with identical
        template strings share the same compiled template object.
        """
        if template_source not in self._cache:
            self._cache[template_source] = self._env.from_string(template_source)
        return self._cache[template_source]

    def clear_cache(self) -> None:
        """Clear the template cache.

        Called when entities are reloaded to ensure fresh templates.
        """
        self._cache.clear()
        logger.debug("Template cache cleared")
