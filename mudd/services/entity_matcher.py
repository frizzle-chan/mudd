"""Entity name matching and filtering for commands."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from mudd.services.entity import EntityInstance

if TYPE_CHECKING:
    from mudd.services.focus_context import FocusContext


class AutocompleteEntityFetcher(Protocol):
    """Protocol for entity service methods needed by autocomplete."""

    async def get_top_level_room_entities(self, room: str) -> list[EntityInstance]: ...

    async def get_container_contents(
        self, container_id: str, room: str
    ) -> list[EntityInstance]: ...


class FocusContextFetcher(Protocol):
    """Protocol for focus context service methods needed by autocomplete."""

    async def get_focus(self, user_id: int, room: str) -> "FocusContext | None": ...

    async def get_focused_contents(self, user_id: int, room: str) -> list[str]: ...


async def get_autocomplete_entities(
    entity_service: AutocompleteEntityFetcher,
    room: str,
) -> list[EntityInstance]:
    """Get entities visible for autocomplete.

    Includes top-level entities and entities in containers with contents_visible=True.
    Excludes entities in containers with contents_visible=False.
    """
    # Start with top-level entities (always visible)
    top_level = await entity_service.get_top_level_room_entities(room)
    result = list(top_level)

    # Add contents of visible containers
    for instance in top_level:
        if instance.entity.contents_visible:
            contents = await entity_service.get_container_contents(
                instance.entity.id, room
            )
            result.extend(contents)

    return result


@dataclass(frozen=True)
class EntityMatch:
    """Single entity match result."""

    instance: EntityInstance
    match_quality: int  # 0=exact, 1=word-prefix


@dataclass(frozen=True)
class MatchResult:
    """Result of entity name matching."""

    matches: list[EntityMatch]

    def is_unique(self) -> bool:
        """Check if exactly one entity matched."""
        return len(self.matches) == 1

    def is_ambiguous(self) -> bool:
        """Check if multiple entities matched."""
        return len(self.matches) > 1

    def is_empty(self) -> bool:
        """Check if no entities matched."""
        return len(self.matches) == 0


def match_entity_by_prefix(
    query: str,
    entities: list[EntityInstance],
) -> MatchResult:
    """Match entities by word prefix.

    Matching rules:
    - Case-insensitive
    - Matches if ANY word in entity.name starts with query
    - "tab" matches "Wooden Table" (word "Table" starts with "tab")
    - "wood" matches "Wooden Table" (word "Wooden" starts with "wood")
    - Exact matches (full name) have higher quality (0) than prefix matches (1)

    Args:
        query: User input string
        entities: List of entity instances to search

    Returns:
        MatchResult with all matching entities
    """
    if not query:
        return MatchResult(matches=[])

    query_lower = query.lower().strip()
    if not query_lower:
        return MatchResult(matches=[])

    matches: list[EntityMatch] = []

    for instance in entities:
        name = instance.entity.name
        name_lower = name.lower()

        # Check for exact match first
        if name_lower == query_lower:
            matches.append(EntityMatch(instance=instance, match_quality=0))
            continue

        # Check for word prefix match
        words = name_lower.split()
        if any(word.startswith(query_lower) for word in words):
            matches.append(EntityMatch(instance=instance, match_quality=1))

    # Sort by match quality (exact matches first)
    matches.sort(key=lambda m: m.match_quality)

    return MatchResult(matches=matches)


@dataclass(frozen=True)
class AutocompleteChoice:
    """Autocomplete choice with optional focus prefix."""

    instance: EntityInstance
    display_name: str
    is_focused: bool


async def get_focus_aware_autocomplete_entities(
    entity_service: AutocompleteEntityFetcher,
    focus_service: FocusContextFetcher,
    user_id: int,
    room: str,
) -> list[AutocompleteChoice]:
    """Get entities for autocomplete with focus-aware prefixes.

    When a user has an active focus (e.g., open container), this function
    returns entities with the focused container's contents listed first,
    prefixed with "[Container Name]" for visual distinction.

    Args:
        entity_service: Service for entity queries
        focus_service: Service for focus context queries
        user_id: Discord user ID
        room: Current room name

    Returns:
        List of AutocompleteChoice objects with focused items first.
        Focused items have display_name prefixed with "[Container Name]".
    """
    # Get standard visible entities
    visible = await get_autocomplete_entities(entity_service, room)

    # Check for active focus
    focus = await focus_service.get_focus(user_id, room)
    if not focus:
        # No focus: return all visible entities without prefix
        return [
            AutocompleteChoice(
                instance=inst,
                display_name=inst.entity.name,
                is_focused=False,
            )
            for inst in visible
        ]

    # Get focused container contents directly (may include items not in 'visible'
    # list when container has contents_visible=False)
    focused_contents = await entity_service.get_container_contents(
        focus.entity_id, room
    )

    prefix = f"[{focus.entity_name}]"

    # Build focused items from container contents (including hidden ones)
    focused_items: list[AutocompleteChoice] = []
    for inst in focused_contents:
        focused_items.append(
            AutocompleteChoice(
                instance=inst,
                display_name=f"{prefix} {inst.entity.name}",
                is_focused=True,
            )
        )

    # Build room items from visible entities, excluding focused contents
    focused_content_ids = {inst.entity.id for inst in focused_contents}
    room_items: list[AutocompleteChoice] = []
    for inst in visible:
        # Skip items in the focused container (they're already in focused_items)
        if inst.entity.id not in focused_content_ids:
            room_items.append(
                AutocompleteChoice(
                    instance=inst,
                    display_name=inst.entity.name,
                    is_focused=False,
                )
            )

    # Focused items first, then room items
    return focused_items + room_items
