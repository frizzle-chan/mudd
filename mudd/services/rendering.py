"""Entity rendering service using Jinja2 templates."""

from __future__ import annotations

import logging
from typing import Any, Protocol

import asyncpg
from jinja2 import (
    Environment,
    StrictUndefined,
    Template,
    TemplateSyntaxError,
    UndefinedError,
    select_autoescape,
)

from mudd.services.entity import EntityInstance, ResolvedEntity
from mudd.services.trigger_effects import TriggerEffects
from mudd.types import UserContext

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
        # Plain text output - no HTML escaping for string templates
        self._env = Environment(
            autoescape=select_autoescape(default_for_string=False),
            undefined=StrictUndefined,  # Fail on undefined variables
        )
        self._cache: dict[str, Template] = {}  # template source -> compiled Template

    def render_template(
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
        context = {"e": entity, "name": name_formatted, "contents": contents}
        return self.render_with_context(template_source, context, entity.id)

    def render_with_context(
        self,
        template_source: str,
        context: dict[str, Any],
        entity_id: str,
    ) -> str:
        """Render a Jinja2 template with a custom context dictionary.

        Args:
            template_source: Jinja2 template string
            context: Dictionary of template variables
            entity_id: Entity ID for error logging

        Returns:
            Rendered string

        Raises:
            TemplateRenderError: If template has syntax errors or undefined variables
        """
        try:
            template = self._get_or_compile(template_source)
            return template.render(context)
        except TemplateSyntaxError as exc:
            logger.error(
                "Template syntax error in entity '%s': %s", entity_id, str(exc)
            )
            raise TemplateRenderError(str(exc)) from exc
        except UndefinedError as exc:
            logger.error(
                "Template undefined variable in entity '%s': %s", entity_id, str(exc)
            )
            raise TemplateRenderError(str(exc)) from exc
        except Exception as exc:
            logger.exception(
                "Unexpected template error in entity '%s': %s", entity_id, str(exc)
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


class ContainerContentsFetcher(Protocol):
    """Protocol for fetching container contents."""

    async def get_container_contents(
        self, container_id: str, room: str
    ) -> list[EntityInstance]: ...

    async def get_top_level_room_entities(self, room: str) -> list[EntityInstance]: ...


class RoomContext:
    """Lazy room data access for room entity templates.

    Provides room.description() and room.entities() template functions
    for rendering room entities. Data is pre-fetched before template
    rendering to allow synchronous access in templates.

    Usage:
        room_ctx = RoomContext(room_id, pool, entity_service)
        await room_ctx.prefetch(rendering_service)
        # Now room_ctx.description() and room_ctx.entities() are available
    """

    def __init__(
        self,
        room_id: str,
        pool: asyncpg.Pool,
        entity_service: ContainerContentsFetcher,
    ) -> None:
        self._room_id = room_id
        self._pool = pool
        self._entity_service = entity_service
        self._description_cache: str | None = None
        self._entities_cache: str | None = None

    def description(self) -> str:
        """Fetch room description synchronously (pre-fetched).

        Returns:
            Room description from rooms table, or default message.

        Raises:
            RuntimeError: If prefetch() was not called first.
        """
        if self._description_cache is None:
            raise RuntimeError("RoomContext not initialized - call prefetch() first")
        return self._description_cache

    def entities(self) -> str:
        """Fetch formatted entity list synchronously (pre-fetched).

        Returns:
            Formatted string of visible entities, or empty string if none.

        Raises:
            RuntimeError: If prefetch() was not called first.
        """
        if self._entities_cache is None:
            raise RuntimeError("RoomContext not initialized - call prefetch() first")
        return self._entities_cache

    async def prefetch(self, rendering_service: RenderingService) -> None:
        """Pre-fetch room data before template rendering.

        Args:
            rendering_service: Service for formatting entities.
        """
        # Get room description from rooms table
        row = await self._pool.fetchrow(
            "SELECT name, description FROM rooms WHERE id = $1", self._room_id
        )
        self._description_cache = (
            row["description"] if row else "You see nothing special."
        )

        # Get and format visible entities
        entities = await self._entity_service.get_top_level_room_entities(self._room_id)
        self._entities_cache = await rendering_service.format_room_entities(
            entities, self._entity_service, self._room_id
        )


def _lowercase_first(s: str) -> str:
    """Lowercase the first character of a string, preserving the rest."""
    if not s:
        return s
    return s[0].lower() + s[1:]


class RenderingService:
    """Renders entities using Jinja2 templates.

    Owns a TemplateRenderer instance and provides high-level methods for
    rendering entity descriptions and on_look output.
    """

    def __init__(self) -> None:
        self._renderer = TemplateRenderer()

    def clear_cache(self) -> None:
        """Clear template cache (call after entity sync)."""
        self._renderer.clear_cache()

    def render(
        self, template: str | None, entity: ResolvedEntity, contents: str = ""
    ) -> str:
        """Render a template with entity context.

        Template context:
            - `e`: The ResolvedEntity
            - `name`: Entity name formatted with Discord italics (*Name*)
            - `contents`: Pre-formatted bullet list of container contents

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
        name_formatted = f"*{entity.display_name}*"
        return self._renderer.render_template(
            template, entity, name_formatted, contents
        )

    def render_with_effects(
        self,
        template: str | None,
        entity: ResolvedEntity,
        user: UserContext,
        contents: str = "",
        container: ResolvedEntity | None = None,
        balance: str = "",
    ) -> tuple[str, TriggerEffects]:
        """Render a template and collect side effects.

        Extended template context:
            - `e`: The ResolvedEntity
            - `name`: Entity name formatted with Discord italics (*Name*)
            - `contents`: Pre-formatted bullet list of container contents
            - `user`: UserContext with name and mention
            - `effects`: TriggerEffects for queuing side effects
            - `container`: Optional ResolvedEntity for focused container (drop target)
            - `balance`: Formatted currency balance (e.g., "¥1,000")

        Example template:
            {{ effects.broadcast("**" ~ user.name ~ "** put on some music.") }}
            You slide the record onto the turntable.

        Args:
            template: Jinja2 template string (or None)
            entity: The entity providing context
            user: User context with name and mention
            contents: Pre-formatted bullet list of contents (default: "")
            container: Optional container entity for drop context (default: None)
            balance: Formatted currency balance (default: "")

        Returns:
            Tuple of (rendered output, collected effects)

        Raises:
            TemplateRenderError: If template has syntax errors or undefined variables
        """
        effects = TriggerEffects()
        if template is None:
            return "", effects
        context: dict[str, Any] = {
            "e": entity,
            "name": f"*{entity.display_name}*",
            "contents": contents,
            "user": user,
            "effects": effects,
            "container": container,  # Always include, may be None
            "balance": balance,
        }
        output = self._renderer.render_with_context(template, context, entity.id)
        return output, effects

    def build_contents_string(self, contents: list[EntityInstance]) -> str:
        """Build a formatted string from container contents.

        Formats based on item count:
        - 1 item: " Item" (space-prefixed, capitalized)
        - 2 items: " Item1 and item2" (space-prefixed, first capitalized)
        - 3+ items: "\\n- item1\\n- item2\\n- item3" (bullet list)

        Args:
            contents: List of contained entity instances

        Returns:
            Formatted string or empty string if no contents
        """
        if not contents:
            return ""

        # Render all item descriptions
        descriptions: list[str] = []
        for c in contents:
            try:
                desc = self.render(c.entity.description_short, c.entity)
                if desc:
                    descriptions.append(desc)
            except TemplateRenderError:
                # Fallback to entity name if template is malformed
                logger.warning(
                    "Template error rendering description_short for entity '%s', "
                    "using name fallback",
                    c.entity.id,
                )
                descriptions.append(f"*{c.entity.display_name}*")

        if not descriptions:
            return ""

        # Format based on count
        if len(descriptions) == 1:
            # Single item: space-prefixed, lowercase (follows colon in template)
            return " " + _lowercase_first(descriptions[0])
        elif len(descriptions) == 2:
            # Two items: space-prefixed, joined with "and", both lowercased
            return (
                " "
                + _lowercase_first(descriptions[0])
                + " and "
                + _lowercase_first(descriptions[1])
            )
        else:
            # Three or more: bullet list (no case change, each line starts fresh)
            return "\n" + "\n".join(f"- {desc}" for desc in descriptions)

    def format_entity_with_contents(
        self,
        entity: ResolvedEntity,
        contents: list[EntityInstance] | None = None,
    ) -> str:
        """Format a single entity with optional visible contents.

        The entity's description_short template receives a `contents` variable
        containing a bullet-list of contents (empty string if none).

        Args:
            entity: The resolved entity to format
            contents: List of contained entity instances (if any)

        Returns:
            Rendered description_short with contents interpolated
        """
        contents_str = self.build_contents_string(contents or [])
        return self.render(entity.description_short, entity, contents=contents_str)

    async def format_room_entities(
        self,
        entities: list[EntityInstance],
        entity_service: ContainerContentsFetcher,
        room: str,
    ) -> str:
        """Format all room entities into a paragraph.

        Args:
            entities: Top-level entity instances in the room
            entity_service: Service to fetch container contents
            room: Room ID for querying contents

        Returns:
            Formatted paragraph with all entities, or empty string if none
        """
        if not entities:
            return ""

        lines = []
        for instance in entities:
            entity = instance.entity

            # Get contents if visible
            contents = None
            if entity.contents_visible:
                contents = await entity_service.get_container_contents(entity.id, room)

            formatted = self.format_entity_with_contents(entity, contents)
            if formatted:
                lines.append(formatted)

        return "\n".join(lines) if lines else ""

    async def render_entity_on_look(
        self,
        instance: EntityInstance,
        entity_service: ContainerContentsFetcher,
        room: str | None,
        balance: str = "",
        include_heading: bool = True,
    ) -> str:
        """Render entity on_look template for /look at:<entity>.

        Uses Jinja2 templating for on_look field. Template context:
            - `e`: The ResolvedEntity with all properties
            - `name`: Entity name formatted with Discord italics (*Name*)
            - `contents`: Pre-formatted bullet list of contents
            - `balance`: Formatted currency balance (e.g., "¥1,000")

        If on_look is None or template fails, falls back to description_long
        or description_short. Template errors append a warning suffix.

        Args:
            instance: Entity instance to render
            entity_service: Service to fetch container contents
            room: Room ID for querying contents (None for inventory items)
            balance: Formatted currency balance (default: "")
            include_heading: Whether to include the entity name as a heading
                (default: True). Set to False for inventory threads where
                the thread title already shows the name.

        Returns:
            Rendered on_look output
        """
        entity = instance.entity
        parts: list[str] = []
        if include_heading:
            parts.append(f"### {entity.display_name}")

        # Fetch and format container contents (skip for inventory items with no room)
        contents_str = ""
        if entity.contents_visible and room is not None:
            contents = await entity_service.get_container_contents(entity.id, room)
            contents_str = self.build_contents_string(contents)

        # Build base context
        base_context: dict[str, Any] = {
            "e": entity,
            "name": f"*{entity.display_name}*",
            "contents": contents_str,
            "balance": balance,
        }

        # Build fallback from descriptions (also rendered as templates)
        try:
            fallback = self._renderer.render_with_context(
                entity.description_long or entity.description_short or "",
                base_context,
                entity.id,
            )
        except TemplateRenderError:
            fallback = ""
        if not fallback:
            fallback = "You see nothing special."

        # Render on_look template (use fallback if on_look is None)
        has_error = False
        if entity.on_look is None:
            output = fallback
        else:
            try:
                output = self._renderer.render_with_context(
                    entity.on_look, base_context, entity.id
                )
            except TemplateRenderError:
                logger.warning(
                    "Template error rendering on_look for entity '%s', using fallback",
                    entity.id,
                )
                output = fallback
                has_error = True

        if output:
            parts.append(output)

        # Add error warning if template failed
        if has_error:
            parts.append("-# (error rendering template)")

        return "\n\n".join(parts) if parts else "You see nothing special."

    async def render_room_entity(
        self,
        entity: ResolvedEntity,
        room_id: str,
        pool: asyncpg.Pool,
        entity_service: ContainerContentsFetcher,
    ) -> tuple[str, TriggerEffects]:
        """Render a room entity's on_look with room context.

        Room entities have access to a special `room` context providing:
            - `room.description()`: Room description from database
            - `room.entities()`: Formatted list of visible entities

        Args:
            entity: The room entity to render
            room_id: Room ID for fetching room data
            pool: Database connection pool
            entity_service: Service for fetching entities

        Returns:
            Tuple of (rendered output, collected effects)
        """
        room_ctx = RoomContext(room_id, pool, entity_service)
        await room_ctx.prefetch(self)

        effects = TriggerEffects()
        context: dict[str, Any] = {
            "e": entity,
            "name": f"*{entity.display_name}*",
            "room": room_ctx,
            "effects": effects,
        }

        default_room_template = "{{ room.description() }}\n\n{{ room.entities() }}"
        template_text = entity.on_look or default_room_template

        try:
            output = self._renderer.render_with_context(
                template_text, context, entity.id
            )
        except TemplateRenderError:
            logger.warning(
                "Template error rendering on_look for room entity '%s', using fallback",
                entity.id,
            )
            output = f"{room_ctx.description()}\n\n{room_ctx.entities()}"

        return output, effects
