"""Entity rendering service using Jinja2 templates."""

from __future__ import annotations

import logging
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any, Literal, Protocol
from uuid import UUID

import asyncpg

if TYPE_CHECKING:
    from mudd.services.entity_resolution import EntityResolutionService
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


def _money_filter(value: int) -> str:
    """Format an integer as yen currency (e.g., 1000 -> "¥1,000")."""
    return f"¥{value:,}"


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

    Async mode is enabled, allowing templates to call async functions directly.
    For example, `{{ room.description() }}` will automatically await the async
    `description()` method.

    Usage:
        renderer = TemplateRenderer()
        output = await renderer.render_async(
            template_source=entity.on_look,
            context={"e": entity, "name": "*Wooden Table*"},
            entity_id=entity.id,
        )
    """

    def __init__(self) -> None:
        # Plain text output - no HTML escaping for string templates
        # enable_async allows templates to call async functions directly
        self._env = Environment(
            autoescape=select_autoescape(default_for_string=False),
            undefined=StrictUndefined,  # Fail on undefined variables
            enable_async=True,
        )
        self._env.filters["money"] = _money_filter
        self._cache: dict[str, Template] = {}  # template source -> compiled Template

    async def render_template(
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
        return await self.render_with_context(template_source, context, entity.id)

    async def render_with_context(
        self,
        template_source: str,
        context: dict[str, Any],
        entity_id: str,
    ) -> str:
        """Render a Jinja2 template with context.

        Supports templates that call async functions. For example,
        `{{ room.description() }}` will automatically await the async method.

        Args:
            template_source: Jinja2 template string
            context: Dictionary of template variables (may contain async callables)
            entity_id: Entity ID for error logging

        Returns:
            Rendered string

        Raises:
            TemplateRenderError: If template has syntax errors or undefined variables
        """
        try:
            template = self._get_or_compile(template_source)
            return await template.render_async(context)
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

    Provides room.description() and room.entities() as async template functions.
    With Jinja's enable_async mode, templates can call these directly and they
    will be automatically awaited.

    Usage in templates:
        {{ room.description() }}
        {{ room.entities() }}

    Usage in Python:
        room_ctx = RoomContext(room_id, pool, entity_service, rendering_service)
        # Pass to template context - methods are called lazily during render
    """

    def __init__(
        self,
        room_id: str,
        pool: asyncpg.Pool,
        entity_service: ContainerContentsFetcher,
        rendering_service: RenderingService,
    ) -> None:
        self._room_id = room_id
        self._pool = pool
        self._entity_service = entity_service
        self._rendering_service = rendering_service
        self._description_cache: str | None = None
        self._entities_cache: str | None = None

    @property
    def id(self) -> str:
        """The room ID."""
        return self._room_id

    async def description(self) -> str:
        """Fetch room description lazily.

        Returns:
            Room description from rooms table, or default message.
        """
        if self._description_cache is None:
            row = await self._pool.fetchrow(
                "SELECT name, description FROM rooms WHERE id = $1", self._room_id
            )
            self._description_cache = (
                row["description"] if row else "You see nothing special."
            )
        return self._description_cache

    async def entities(self) -> str:
        """Fetch formatted entity list lazily.

        Returns:
            Formatted string of visible entities, or empty string if none.
        """
        if self._entities_cache is None:
            entities = await self._entity_service.get_top_level_room_entities(
                self._room_id
            )
            self._entities_cache = await self._rendering_service.format_room_entities(
                entities, self._entity_service, self._room_id
            )
        return self._entities_cache


class EntityContext:
    """Lazy entity data access for templates.

    Wraps a ResolvedEntity and provides lazy contents fetching via e.contents.
    Proxies all ResolvedEntity properties for templates using {{ e.name }},
    {{ e.description_long }}, etc.

    Usage in templates:
        {{ e.contents }}
        {{ e.name }}
        {{ e.display_name }}

    Usage in Python:
        entity_ctx = EntityContext(
            entity=resolved_entity,
            instance_id=instance.instance_id,
            source="room",
            room="foyer",
            user_id=123,
            entity_service=entity_service,
            entity_resolution=entity_resolution,
            rendering_service=rendering_service,
        )
    """

    def __init__(
        self,
        entity: ResolvedEntity,
        instance_id: UUID,
        source: Literal["room", "inventory", "container"],
        room: str,
        user_id: int,
        entity_service: ContainerContentsFetcher,
        entity_resolution: EntityResolutionService | None,
        rendering_service: RenderingService,
        skip_contents: bool = False,
    ) -> None:
        self._entity = entity
        self._instance_id = instance_id
        self._source = source
        self._room = room
        self._user_id = user_id
        self._entity_service = entity_service
        self._entity_resolution = entity_resolution
        self._rendering_service = rendering_service
        self._skip_contents = skip_contents

    @property
    def instance_id(self) -> UUID:
        """The entity instance UUID."""
        return self._instance_id

    # Proxy all ResolvedEntity properties
    @property
    def id(self) -> str:
        return self._entity.id

    @property
    def name(self) -> str:
        return self._entity.name

    @property
    def display_name(self) -> str:
        return self._entity.display_name

    @property
    def description_short(self) -> str | None:
        return self._entity.description_short

    @property
    def description_long(self) -> str | None:
        return self._entity.description_long

    @property
    def on_look(self) -> str | None:
        return self._entity.on_look

    @property
    def on_touch(self) -> str | None:
        return self._entity.on_touch

    @property
    def on_attack(self) -> str | None:
        return self._entity.on_attack

    @property
    def on_use(self) -> str | None:
        return self._entity.on_use

    @property
    def on_take(self) -> str | None:
        return self._entity.on_take

    @property
    def on_open(self) -> str | None:
        return self._entity.on_open

    @property
    def on_close(self) -> str | None:
        return self._entity.on_close

    @property
    def on_drop(self) -> str | None:
        return self._entity.on_drop

    @property
    def contents_visible(self) -> bool | None:
        return self._entity.contents_visible

    @property
    def focus_mode(self) -> str:
        return self._entity.focus_mode

    @property
    def rarity(self) -> str:
        return self._entity.rarity

    @property
    def contents(self) -> Coroutine[Any, Any, str]:
        """Fetch and format container contents lazily.

        Returns a coroutine that Jinja2's render_async will auto-await.
        Templates use {{ e.contents }} (no parentheses needed).

        Returns:
            Coroutine yielding formatted bullet list of contents, or empty string.
        """
        return self._get_contents()

    async def _get_contents(self) -> str:
        """Internal async implementation for contents fetching."""
        if self._skip_contents:
            return ""

        is_inventory_source = self._source in ("inventory", "container")
        if is_inventory_source and self._entity_resolution is not None:
            container_contents = (
                await self._entity_resolution._get_inventory_container_contents(
                    self._user_id, self._entity.id
                )
            )
        else:
            container_contents = await self._entity_service.get_container_contents(
                self._entity.id, self._room
            )

        return await self._rendering_service.build_contents_string(container_contents)


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

    async def render(
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
        return await self._renderer.render_template(
            template, entity, name_formatted, contents
        )

    async def render_with_effects(
        self,
        template: str | None,
        entity: EntityContext,
        user: UserContext,
        container: ResolvedEntity | None = None,
        room: RoomContext | None = None,
    ) -> tuple[str, TriggerEffects]:
        """Render a template and collect side effects.

        Supports templates that call async functions like room.description(),
        room.entities(), user.balance(), and e.contents.

        Extended template context:
            - `e`: EntityContext with all entity properties and lazy e.contents
            - `name`: Entity name formatted with Discord italics (*Name*)
            - `user`: UserContext with name, mention, and optional async balance()
            - `effects`: TriggerEffects for queuing side effects
            - `container`: Optional ResolvedEntity for focused container (drop target)
            - `room`: Optional RoomContext with async room.description()/entities()

        Example template:
            {{ e.contents }}
            {{ room.description() }}
            {{ user.balance() }}

        Args:
            template: Jinja2 template string (or None)
            entity: EntityContext with lazy contents fetching
            user: User context with name, mention, and optional balance()
            container: Optional container entity for drop context (default: None)
            room: Optional RoomContext for room.description()/entities() (default: None)

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
            "user": user,
            "effects": effects,
            "container": container,
            "room": room,
        }
        output = await self._renderer.render_with_context(template, context, entity.id)
        return output, effects

    async def build_contents_string(self, contents: list[EntityInstance]) -> str:
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
                desc = await self.render(c.entity.description_short, c.entity)
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

    async def format_entity_with_contents(
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
        contents_str = await self.build_contents_string(contents or [])
        return await self.render(
            entity.description_short, entity, contents=contents_str
        )

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

            formatted = await self.format_entity_with_contents(entity, contents)
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
            contents_str = await self.build_contents_string(contents)

        # Build base context
        base_context: dict[str, Any] = {
            "e": entity,
            "name": f"*{entity.display_name}*",
            "contents": contents_str,
            "balance": balance,
        }

        # Build fallback from descriptions (also rendered as templates)
        try:
            fallback = await self._renderer.render_with_context(
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
                output = await self._renderer.render_with_context(
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
        room_ctx = RoomContext(room_id, pool, entity_service, self)

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
            output = await self._renderer.render_with_context(
                template_text, context, entity.id
            )
        except TemplateRenderError:
            logger.warning(
                "Template error rendering on_look for room entity '%s', using fallback",
                entity.id,
            )
            output = f"{await room_ctx.description()}\n\n{await room_ctx.entities()}"

        return output, effects
