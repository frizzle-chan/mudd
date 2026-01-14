"""Entity formatting for room descriptions."""

from typing import Protocol

from mudd.services.entity import EntityInstance, ResolvedEntity


class ContainerContentsFetcher(Protocol):
    """Protocol for fetching container contents."""

    async def get_container_contents(
        self, container_id: str, room: str
    ) -> list[EntityInstance]: ...


def format_entity_name(name: str) -> str:
    """Format entity name with Discord italics.

    Args:
        name: Entity display name

    Returns:
        Name wrapped in Discord italic markers (*name*)
    """
    return f"*{name}*"


def interpolate_description(template: str | None, name: str) -> str:
    """Replace {name} placeholder with formatted entity name.

    Args:
        template: Description template with optional {name} placeholder
        name: Entity name (will be formatted with italics)

    Returns:
        Interpolated string, or empty string if template is None
    """
    if template is None:
        return ""
    formatted_name = format_entity_name(name)
    return template.replace("{name}", formatted_name)


def format_entity_with_contents(
    entity: ResolvedEntity,
    contents: list[EntityInstance] | None = None,
) -> str:
    """Format a single entity with optional visible contents.

    Args:
        entity: The resolved entity to format
        contents: List of contained entity instances (if any)

    Returns:
        Formatted string like "a *Wooden Table*. On it: a *Flower Vase*, a *Plaque*"
    """
    base = interpolate_description(entity.description_short, entity.name)

    if not contents:
        return base

    content_descriptions = [
        interpolate_description(c.entity.description_short, c.entity.name)
        for c in contents
    ]

    return f"{base}. On it: {', '.join(content_descriptions)}"


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
