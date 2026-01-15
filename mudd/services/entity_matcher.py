"""Entity name matching and filtering for commands."""

from dataclasses import dataclass

from mudd.services.entity import EntityInstance


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
