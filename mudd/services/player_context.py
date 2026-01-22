"""Player context service for entity visibility and focus management.

Consolidates entity + focus logic into a single service with clean caching.
This is the primary interface for autocomplete and player state queries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from mudd.matching.entity_matcher import match_entity_by_prefix
from mudd.services.entity import EntityInstance, ResolvedEntity
from mudd.services.focus_context import FocusContext


class EntityFetcher(Protocol):
    """Protocol for entity service methods needed by PlayerContextService."""

    async def get_visible_entities(self, room: str) -> list[EntityInstance]: ...

    async def get_container_contents(
        self, container_id: str, room: str
    ) -> list[EntityInstance]: ...


class FocusContextFetcher(Protocol):
    """Protocol for focus context service methods needed by PlayerContextService."""

    async def get_focus(self, user_id: int, room: str) -> FocusContext | None: ...

    async def set_focus(
        self, user_id: int, room: str, entity: ResolvedEntity
    ) -> str | None: ...

    async def clear_focus(
        self, user_id: int, reason: str = "interaction"
    ) -> str | None: ...

    async def update_focus_timestamp(self, user_id: int) -> None: ...

    async def is_entity_in_focus(
        self, user_id: int, room: str, entity_id: str
    ) -> bool: ...


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AutocompleteChoice:
    """Autocomplete choice with focus tracking."""

    instance: EntityInstance
    display_name: str
    is_focused: bool


class PlayerContextService:
    """Manages player context for entity visibility and focus state.

    Consolidates EntityService and FocusContextService into a single API
    with caching. The cache key is (room, focus_entity_id) since candidates
    only depend on room and focus state, not on which user is asking.

    Usage:
        service = PlayerContextService(entity_service, focus_service)
        choices = await service.get_visible_entities(room, user_id, query="tab")
    """

    def __init__(
        self,
        entity_service: EntityFetcher,
        focus_service: FocusContextFetcher,
    ) -> None:
        self._entity_service = entity_service
        self._focus_service = focus_service
        # Cache key: (room, focus_entity_id | None)
        # Candidates only depend on room + focus state, not user_id
        self._autocomplete_cache: dict[
            tuple[str, str | None], list[AutocompleteChoice]
        ] = {}

    async def get_visible_entities(
        self, room: str, user_id: int, query: str = ""
    ) -> list[AutocompleteChoice]:
        """Get visible entities for autocomplete, filtered by query.

        This is the main entry point for autocomplete. It:
        1. Gets cached visible entities for the room
        2. Checks user focus state
        3. Builds candidate list with focus ordering
        4. Filters by text using prefix matching

        Args:
            room: Current room name
            user_id: Discord user ID
            query: User input text to filter by (empty string = no filtering)

        Returns:
            List of AutocompleteChoice objects, filtered and ordered.
        """
        # Get focus state first (needed for cache key)
        focus = await self._focus_service.get_focus(user_id, room)
        focus_entity_id = focus.entity_id if focus else None

        # Check cache - key is (room, focus_entity_id), not per-user
        cache_key = (room, focus_entity_id)
        if cache_key not in self._autocomplete_cache:
            # Build candidates and cache
            candidates = await self._build_candidates(room, focus)
            self._autocomplete_cache[cache_key] = candidates
        else:
            candidates = self._autocomplete_cache[cache_key]

        # Filter by query (cheap in-memory operation)
        if query:
            match_result = match_entity_by_prefix(
                query, [c.instance for c in candidates]
            )
            matched_ids = {m.instance.entity.id for m in match_result.matches}
            candidates = [c for c in candidates if c.instance.entity.id in matched_ids]

        # When focused, return only focused items
        focused = [c for c in candidates if c.is_focused]
        if focused:
            return focused

        return candidates

    async def _build_candidates(
        self, room: str, focus: FocusContext | None
    ) -> list[AutocompleteChoice]:
        """Build autocomplete candidates for a room with optional focus."""
        visible = await self._entity_service.get_visible_entities(room)

        if focus:
            focused_contents = await self._entity_service.get_container_contents(
                focus.entity_id, room
            )
            return self._build_focused_candidates(
                visible, focused_contents, focus.entity_id
            )
        else:
            return self._build_unfocused_candidates(visible)

    def _build_unfocused_candidates(
        self, visible: list[EntityInstance]
    ) -> list[AutocompleteChoice]:
        """Build autocomplete choices from visible entities (no focus)."""
        return [
            AutocompleteChoice(
                instance=inst,
                display_name=inst.entity.display_name,
                is_focused=False,
            )
            for inst in visible
        ]

    def _build_focused_candidates(
        self,
        visible: list[EntityInstance],
        focused_contents: list[EntityInstance],
        focus_parent_id: str,
    ) -> list[AutocompleteChoice]:
        """Build autocomplete choices with focused items first.

        Args:
            visible: Visible room entities
            focused_contents: Contents of the focused container
            focus_parent_id: Entity ID of the focused container itself

        Returns:
            Focus parent first, then contents, then room items
        """
        focused_content_ids = {inst.entity.id for inst in focused_contents}

        # Build focus parent item first
        focus_parent_item: list[AutocompleteChoice] = []
        room_items: list[AutocompleteChoice] = []

        for inst in visible:
            if inst.entity.id in focused_content_ids:
                continue  # Skip contents (added separately)
            if inst.entity.id == focus_parent_id:
                focus_parent_item = [
                    AutocompleteChoice(
                        instance=inst,
                        display_name=inst.entity.display_name,
                        is_focused=True,
                    )
                ]
            else:
                room_items.append(
                    AutocompleteChoice(
                        instance=inst,
                        display_name=inst.entity.display_name,
                        is_focused=False,
                    )
                )

        # Build focused content items
        content_items = [
            AutocompleteChoice(
                instance=inst,
                display_name=inst.entity.display_name,
                is_focused=True,
            )
            for inst in focused_contents
        ]

        return focus_parent_item + content_items + room_items

    # Delegated focus operations (invalidate cache on change)

    async def get_focus(self, user_id: int, room: str) -> FocusContext | None:
        """Get user's current focus in their current room.

        Delegates to FocusContextService.
        """
        return await self._focus_service.get_focus(user_id, room)

    async def set_focus(
        self, user_id: int, room: str, entity: ResolvedEntity
    ) -> str | None:
        """Establish focus on an entity.

        Delegates to FocusContextService. No cache invalidation needed since
        changing focus just changes which cache key is used for lookups.
        """
        return await self._focus_service.set_focus(user_id, room, entity)

    async def clear_focus(
        self, user_id: int, reason: str = "interaction"
    ) -> str | None:
        """Clear user's focus.

        Delegates to FocusContextService. No cache invalidation needed since
        clearing focus just changes which cache key is used for lookups.
        """
        return await self._focus_service.clear_focus(user_id, reason)

    async def update_focus_timestamp(self, user_id: int) -> None:
        """Update the timestamp on a user's focus to prevent timeout.

        Delegates to FocusContextService. Does not invalidate cache since
        focus state hasn't changed.
        """
        await self._focus_service.update_focus_timestamp(user_id)

    async def is_entity_in_focus(self, user_id: int, room: str, entity_id: str) -> bool:
        """Check if an entity is the focused container or in its contents.

        Delegates to FocusContextService.
        """
        return await self._focus_service.is_entity_in_focus(user_id, room, entity_id)

    # Cache invalidation

    def invalidate_cache(self) -> None:
        """Clear all caches.

        Called by Sync cog after entity sync to ensure caches reflect latest data.
        """
        self._autocomplete_cache.clear()
        logger.debug("PlayerContext autocomplete cache invalidated")

    async def prepopulate_cache(self, rooms: list[str]) -> int:
        """Prepopulate cache for unfocused state in given rooms.

        Called by Sync cog after entity sync to warm the cache. This ensures
        the first autocomplete request in each room is fast (no DB query).

        Args:
            rooms: List of room names to prepopulate cache for.

        Returns:
            Number of rooms prepopulated.
        """
        count = 0
        failed = 0
        for room in rooms:
            cache_key = (room, None)  # Unfocused state
            if cache_key not in self._autocomplete_cache:
                try:
                    candidates = await self._build_candidates(room, focus=None)
                    self._autocomplete_cache[cache_key] = candidates
                    count += 1
                except Exception:
                    logger.exception("Failed to prepopulate cache for room '%s'", room)
                    failed += 1
        if failed:
            logger.warning(
                "Cache prepopulation: %d succeeded, %d failed", count, failed
            )
        logger.debug("PlayerContext cache prepopulated for %d rooms", count)
        return count
