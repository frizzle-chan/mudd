"""Entity formatting for room descriptions."""

import logging
from typing import Protocol

from mudd.services.entity import EntityInstance, ResolvedEntity
from mudd.templating import TemplateRenderError, render

logger = logging.getLogger(__name__)


class ContainerContentsFetcher(Protocol):
    """Protocol for fetching container contents."""

    async def get_container_contents(
        self, container_id: str, room: str
    ) -> list[EntityInstance]: ...


def _lowercase_first(s: str) -> str:
    """Lowercase the first character of a string, preserving the rest."""
    if not s:
        return s
    return s[0].lower() + s[1:]


def build_contents_string(contents: list[EntityInstance]) -> str:
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
            desc = render(c.entity.description_short, c.entity)
            if desc:
                descriptions.append(desc)
        except TemplateRenderError:
            # Fallback to entity name if template is malformed
            logger.warning(
                "Template error rendering description_short for entity '%s', "
                "using name fallback",
                c.entity.id,
            )
            descriptions.append(f"*{c.entity.name}*")

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
    contents_str = build_contents_string(contents or [])
    return render(entity.description_short, entity, contents=contents_str)


async def format_room_entities(
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

        formatted = format_entity_with_contents(entity, contents)
        if formatted:
            lines.append(formatted)

    return "\n".join(lines) if lines else ""


async def render_entity_on_look(
    instance: EntityInstance,
    entity_service: ContainerContentsFetcher,
    room: str,
) -> str:
    """Render entity on_look template for /look at:<entity>.

    Uses Jinja2 templating for on_look field. Template context:
        - `e`: The ResolvedEntity with all properties
        - `name`: Entity name formatted with Discord italics (*Name*)
        - `contents`: Pre-formatted bullet list of container contents (empty if none)

    If on_look is None or template fails, falls back to description_long
    or description_short. Template errors append a warning suffix.

    Args:
        instance: Entity instance to render
        entity_service: Service to fetch container contents
        room: Room ID for querying contents

    Returns:
        Rendered on_look output
    """
    entity = instance.entity
    parts: list[str] = [f"### {entity.name}"]

    # Fetch and format container contents
    contents_str = ""
    if entity.contents_visible:
        contents = await entity_service.get_container_contents(entity.id, room)
        contents_str = build_contents_string(contents)

    # Build fallback from descriptions (also rendered as templates)
    fallback = render(
        entity.description_long or entity.description_short, entity, contents_str
    )
    if not fallback:
        fallback = "You see nothing special."

    # Render on_look template (use fallback if on_look is None)
    has_error = False
    if entity.on_look is None:
        output = fallback
    else:
        try:
            output = render(entity.on_look, entity, contents_str)
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
