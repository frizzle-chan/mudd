"""Entity resolution service for entity visibility and focus management.

Consolidates entity + focus logic into a single service with clean caching.
This is the primary interface for autocomplete and player state queries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

import asyncpg
from discord import Interaction, app_commands

from mudd.matching.entity_matcher import match_entity_by_prefix
from mudd.services.entity import EntityInstance, ResolvedEntity
from mudd.services.focus_context import FocusContext

if TYPE_CHECKING:
    import discord

logger = logging.getLogger(__name__)


# Valid source prefixes for encoded autocomplete values
VALID_SOURCES = frozenset({"room", "inventory", "container", "escape"})


class ViewMode(str, Enum):
    """View mode for entity resolution context."""

    ROOM = "room"  # Normal room view (with optional focus)
    INVENTORY = "inventory"  # Typed "i." prefix
    INVENTORY_THREAD = "thread"  # In inventory forum thread


@dataclass(frozen=True)
class InteractionContext:
    """Captures all context needed for entity resolution.

    Built once at the start of autocomplete/command execution to ensure
    consistent resolution throughout the interaction.
    """

    user_id: int
    room: str  # Always populated (for action execution)
    view_mode: ViewMode
    focus_entity_id: str | None = None  # Only for ROOM mode
    thread_instance_id: UUID | None = None  # Only for INVENTORY_THREAD


@dataclass(frozen=True)
class ResolvedTarget:
    """Result of resolving an encoded autocomplete value."""

    instance: EntityInstance
    source: str  # "room", "inventory", "container"


@dataclass(frozen=True)
class ResolutionError:
    """Error when target resolution fails."""

    error_type: str  # "not_found", "escape", "ambiguous"
    message: str
    matches: list[EntityInstance] | None = None  # For ambiguous case


class EntityFetcher(Protocol):
    """Protocol for entity service methods needed by EntityResolutionService."""

    async def get_visible_entities(self, room: str) -> list[EntityInstance]: ...

    async def get_container_contents(
        self, container_id: str, room: str
    ) -> list[EntityInstance]: ...

    async def get_user_inventory(self, user_id: int) -> list[EntityInstance]: ...

    async def get_room_entities(self, room: str) -> list[EntityInstance]: ...


class FocusContextFetcher(Protocol):
    """Protocol for focus context service methods needed by EntityResolutionService."""

    async def get_focus(self, user_id: int, room: str) -> FocusContext | None: ...

    async def set_focus(
        self, user_id: int, entity_instance_id: UUID
    ) -> str | None: ...

    async def clear_focus(
        self, user_id: int, reason: str = "interaction"
    ) -> str | None: ...

    async def update_focus_timestamp(self, user_id: int) -> None: ...

    async def is_entity_in_focus(
        self, user_id: int, room: str, entity_id: str
    ) -> bool: ...


class InventoryFetcher(Protocol):
    """Protocol for inventory service methods needed by EntityResolutionService."""

    async def get_thread_item(
        self, channel: discord.abc.GuildChannel | discord.Thread | None
    ) -> EntityInstance | None: ...


def encode_choice(source: str, name: str) -> str:
    """Encode a choice value with source prefix.

    Args:
        source: One of "room", "inventory", "container", "escape"
        name: Human-readable entity name

    Returns:
        Encoded string in format "{source}:{name}"
    """
    return f"{source}:{name}"


def decode_choice(value: str) -> tuple[str, str]:
    """Decode a choice value. Returns (source, entity_name).

    Handles both encoded values (source:name) and legacy plain names.

    Args:
        value: Encoded or plain autocomplete value

    Returns:
        (source, entity_name) tuple.
        Returns ("legacy", original_value) if no valid source prefix.
    """
    if ":" in value:
        source, name = value.split(":", 1)
        if source in VALID_SOURCES:
            return (source, name)
    return ("legacy", value)  # Fallback to full prefix matching


@dataclass(frozen=True)
class AutocompleteChoice:
    """Autocomplete choice with focus tracking."""

    instance: EntityInstance
    display_name: str
    is_focused: bool


class EntityResolutionService:
    """Manages entity resolution for visibility and focus state.

    Consolidates EntityService, FocusContextService, and InventoryService
    into a single API with caching. The cache key is (room, focus_entity_id, view_mode)
    since candidates depend on room, focus state, and view mode.

    Usage:
        service = EntityResolutionService(
            entity_service, focus_service, inventory_service, pool
        )
        ctx = await service.build_context(interaction, current)
        choices = await service.get_autocomplete_choices(ctx, current)
        result = await service.resolve_target(ctx, selected_value)
    """

    def __init__(
        self,
        entity_service: EntityFetcher,
        focus_service: FocusContextFetcher,
        inventory_service: InventoryFetcher,
        pool: asyncpg.Pool,
    ) -> None:
        self._entity_service = entity_service
        self._focus_service = focus_service
        self._inventory_service = inventory_service
        self._pool = pool
        # Cache key: (room, focus_entity_id | None, view_mode)
        # Candidates depend on room, focus state, and view mode
        self._autocomplete_cache: dict[
            tuple[str, str | None, ViewMode], list[AutocompleteChoice]
        ] = {}

    async def build_context(
        self, interaction: Interaction, query: str = ""
    ) -> InteractionContext:
        """Build context from Discord state.

        Detects view mode based on:
        1. Inventory thread: get_thread_item(channel) returns an item
        2. "i." prefix: query starts with "i."
        3. Default: ROOM mode (with focus lookup)

        Args:
            interaction: Discord interaction
            query: Current autocomplete query

        Returns:
            InteractionContext with all relevant state
        """
        import discord

        user_id = interaction.user.id

        # Get user's room from database (always needed for action execution)
        user_room = await self._pool.fetchval(
            "SELECT current_room FROM users WHERE id = $1",
            user_id,
        )
        if user_room is None:
            # User not in database - fallback to channel name
            user_room = getattr(interaction.channel, "name", None) or ""

        # Check if in inventory thread
        channel = interaction.channel
        if isinstance(channel, (discord.abc.GuildChannel, discord.Thread)):
            thread_item = await self._inventory_service.get_thread_item(channel)
            if thread_item is not None:
                # In inventory thread - check if container for implicit focus
                focus_entity_id = None
                if thread_item.entity.focus_mode != "none":
                    # Container in inventory - implicit focus on its contents
                    focus_entity_id = thread_item.entity.id

                return InteractionContext(
                    user_id=user_id,
                    room=user_room,
                    view_mode=ViewMode.INVENTORY_THREAD,
                    focus_entity_id=focus_entity_id,
                    thread_instance_id=thread_item.instance_id,
                )
        else:
            # Handle None channel case
            thread_item = None

        # Check for "i." prefix
        if query.lower().startswith("i."):
            return InteractionContext(
                user_id=user_id,
                room=user_room,
                view_mode=ViewMode.INVENTORY,
            )

        # Default: ROOM mode with focus lookup
        focus = await self._focus_service.get_focus(user_id, user_room)
        focus_entity_id = focus.entity_id if focus else None

        return InteractionContext(
            user_id=user_id,
            room=user_room,
            view_mode=ViewMode.ROOM,
            focus_entity_id=focus_entity_id,
        )

    async def get_autocomplete_choices(
        self, ctx: InteractionContext, query: str
    ) -> list[app_commands.Choice[str]]:
        """Get autocomplete choices with source-prefixed values.

        Args:
            ctx: InteractionContext from build_context()
            query: User input text to filter by

        Returns:
            List of Discord autocomplete choices with encoded values
        """
        if ctx.view_mode == ViewMode.INVENTORY_THREAD:
            return await self._get_inventory_thread_choices(ctx, query)
        elif ctx.view_mode == ViewMode.INVENTORY:
            return await self._get_inventory_choices(ctx, query)
        else:
            return await self._get_room_choices(ctx, query)

    async def _get_inventory_thread_choices(
        self, ctx: InteractionContext, query: str
    ) -> list[app_commands.Choice[str]]:
        """Get choices for inventory thread context.

        If thread item is a container (has focus), show container + contents.
        Otherwise, show only the thread's item.
        """
        if ctx.thread_instance_id is None:
            return []

        # Get the thread item
        from mudd.services.entity import EntityService

        entity_svc = self._entity_service
        if isinstance(entity_svc, EntityService):
            thread_item = await entity_svc.get_entity_instance(ctx.thread_instance_id)
        else:
            # Protocol fallback - this shouldn't happen in normal use
            return []

        if thread_item is None:
            return []

        choices: list[app_commands.Choice[str]] = []

        # If container with focus, show contents
        if ctx.focus_entity_id is not None:
            # Get container contents from inventory
            contents = await self._get_inventory_container_contents(
                ctx.user_id, ctx.focus_entity_id
            )

            # Add escape option first
            escape_label = f"[Close {thread_item.entity.name}]"
            choices.append(
                app_commands.Choice(
                    name=escape_label, value=encode_choice("escape", "container")
                )
            )

            # Add container itself
            choices.append(
                app_commands.Choice(
                    name=thread_item.entity.display_name,
                    value=encode_choice("inventory", thread_item.entity.name),
                )
            )

            # Add contents
            for item in contents:
                if query and not item.entity.name.lower().startswith(query.lower()):
                    continue
                choices.append(
                    app_commands.Choice(
                        name=f"  {item.entity.display_name}",  # Indent contents
                        value=encode_choice("container", item.entity.name),
                    )
                )
        else:
            # Non-container thread item - show only the item
            choices.append(
                app_commands.Choice(
                    name=thread_item.entity.display_name,
                    value=encode_choice("inventory", thread_item.entity.name),
                )
            )

        return choices[:25]

    async def _get_inventory_choices(
        self, ctx: InteractionContext, query: str
    ) -> list[app_commands.Choice[str]]:
        """Get choices for inventory mode (i. prefix)."""
        # Strip "i." prefix for matching
        search_query = query[2:] if query.lower().startswith("i.") else query

        inventory = await self._entity_service.get_user_inventory(ctx.user_id)

        if search_query:
            match_result = match_entity_by_prefix(search_query, inventory)
            inventory = [m.instance for m in match_result.matches]

        return [
            app_commands.Choice(
                name=f"[Inventory] {inst.entity.display_name}",
                value=encode_choice("inventory", inst.entity.name),
            )
            for inst in inventory
        ][:25]

    async def _get_room_choices(
        self, ctx: InteractionContext, query: str
    ) -> list[app_commands.Choice[str]]:
        """Get choices for room mode."""
        # Check cache
        cache_key = (ctx.room, ctx.focus_entity_id, ctx.view_mode)
        if cache_key not in self._autocomplete_cache:
            # Get focus context for building candidates
            focus = None
            if ctx.focus_entity_id:
                focus = await self._focus_service.get_focus(ctx.user_id, ctx.room)
            candidates = await self._build_candidates(ctx.room, focus)
            self._autocomplete_cache[cache_key] = candidates
        else:
            candidates = self._autocomplete_cache[cache_key]

        # Filter by query
        if query:
            match_result = match_entity_by_prefix(
                query, [c.instance for c in candidates]
            )
            matched_ids = {m.instance.entity.id for m in match_result.matches}
            candidates = [c for c in candidates if c.instance.entity.id in matched_ids]

        # Build choices
        choices: list[app_commands.Choice[str]] = []

        # Get focus for escape option
        focus = await self._focus_service.get_focus(ctx.user_id, ctx.room)

        # Add escape option when focused (and matches query)
        if focus:
            escape_label = f"[Close {focus.entity_name}] Room"
            if not query or "room".startswith(query.lower()):
                choices.append(
                    app_commands.Choice(
                        name=escape_label, value=encode_choice("escape", "room")
                    )
                )

        # When focused, return only focused items
        focused = [c for c in candidates if c.is_focused]
        if focused:
            for c in focused:
                # Focus parent is "room", focused contents are "container"
                if focus and c.instance.entity.id == focus.entity_id:
                    source = "room"
                else:
                    source = "container"
                choices.append(
                    app_commands.Choice(
                        name=c.display_name,
                        value=encode_choice(source, c.instance.entity.name),
                    )
                )
        else:
            # Not focused - add Room option at top
            if not query or "room".startswith(query.lower()):
                room_display = f"[Close {focus.entity_name}] Room" if focus else "Room"
                # Only add if we didn't already add escape option
                if not focus:
                    choices.append(
                        app_commands.Choice(
                            name=room_display, value=encode_choice("escape", "room")
                        )
                    )

            for c in candidates:
                # All visible items without focus are "room" items
                # (even those inside visible containers)
                choices.append(
                    app_commands.Choice(
                        name=c.display_name,
                        value=encode_choice("room", c.instance.entity.name),
                    )
                )

        return choices[:25]

    async def resolve_target(
        self, ctx: InteractionContext, encoded_value: str
    ) -> ResolvedTarget | ResolutionError:
        """Resolve encoded autocomplete value to EntityInstance.

        Args:
            ctx: InteractionContext from build_context()
            encoded_value: Value from autocomplete selection

        Returns:
            ResolvedTarget on success, ResolutionError on failure
        """
        source, name = decode_choice(encoded_value)

        # Handle escape action
        if source == "escape":
            return ResolutionError(
                error_type="escape",
                message="escape",  # Signals to clear focus and show room
            )

        # Determine search scope based on source
        if source == "room":
            entities = await self._entity_service.get_room_entities(ctx.room)
            not_found_msg = f"You don't see '{name}' here."
        elif source == "inventory":
            entities = await self._entity_service.get_user_inventory(ctx.user_id)
            not_found_msg = f"You don't have '{name}'."
        elif source == "container":
            # Get contents of focused container
            if ctx.focus_entity_id:
                if ctx.view_mode == ViewMode.INVENTORY_THREAD:
                    # Container in inventory
                    entities = await self._get_inventory_container_contents(
                        ctx.user_id, ctx.focus_entity_id
                    )
                else:
                    # Container in room
                    entities = await self._entity_service.get_container_contents(
                        ctx.focus_entity_id, ctx.room
                    )
            else:
                entities = []
            not_found_msg = f"You don't see '{name}' in the container."
        elif source == "legacy":
            # Legacy fallback - search based on view mode
            if ctx.view_mode in (ViewMode.INVENTORY_THREAD, ViewMode.INVENTORY):
                entities = await self._entity_service.get_user_inventory(ctx.user_id)
                not_found_msg = f"You don't have '{name}'."
            else:
                entities = await self._entity_service.get_room_entities(ctx.room)
                not_found_msg = f"You don't see '{name}' here."
        else:
            return ResolutionError(
                error_type="not_found",
                message=f"Unknown source: {source}",
            )

        # Try exact match first
        exact_matches = [e for e in entities if e.entity.name == name]
        if len(exact_matches) == 1:
            if source != "legacy":
                actual_source = source
            else:
                actual_source = self._infer_source(exact_matches[0], ctx)
            return ResolvedTarget(instance=exact_matches[0], source=actual_source)

        # Fallback to prefix matching
        match_result = match_entity_by_prefix(name, entities)

        if match_result.is_empty():
            return ResolutionError(error_type="not_found", message=not_found_msg)

        if match_result.is_ambiguous():
            names = [m.instance.entity.name for m in match_result.matches]
            names_list = ", ".join(f"*{n}*" for n in names)
            return ResolutionError(
                error_type="ambiguous",
                message=f"Which one? {names_list}",
                matches=[m.instance for m in match_result.matches],
            )

        matched = match_result.matches[0].instance
        if source != "legacy":
            actual_source = source
        else:
            actual_source = self._infer_source(matched, ctx)
        return ResolvedTarget(instance=matched, source=actual_source)

    def _infer_source(self, instance: EntityInstance, ctx: InteractionContext) -> str:
        """Infer source for legacy values based on instance and context."""
        if instance.owner_id is not None:
            return "inventory"
        if instance.container_entity_id is not None:
            return "container"
        return "room"

    async def _get_inventory_container_contents(
        self, user_id: int, container_entity_id: str
    ) -> list[EntityInstance]:
        """Get contents of a container in a user's inventory.

        Args:
            user_id: Discord user ID
            container_entity_id: Entity ID of the container

        Returns:
            List of EntityInstance objects inside the container
        """
        rows = await self._pool.fetch(
            """
            SELECT ei.id AS instance_id, ei.room, ei.owner_id,
                   ei.container_entity_id, r.*
            FROM entity_instances ei
            CROSS JOIN LATERAL resolve_entity(ei.entity_id) r
            WHERE ei.owner_id = $1 AND ei.container_entity_id = $2
            """,
            user_id,
            container_entity_id,
        )

        instances = []
        for row in rows:
            entity = ResolvedEntity(
                id=row["id"],
                name=row["name"],
                description_short=row["description_short"],
                description_long=row["description_long"],
                on_look=row["on_look"],
                on_touch=row["on_touch"],
                on_attack=row["on_attack"],
                on_use=row["on_use"],
                on_take=row["on_take"],
                on_open=row["on_open"],
                on_close=row["on_close"],
                on_drop=row["on_drop"],
                contents_visible=row["contents_visible"],
                focus_mode=row["focus_mode"],
                rarity=row["rarity"],
            )
            instances.append(
                EntityInstance(
                    instance_id=row["instance_id"],
                    entity=entity,
                    room=row["room"],
                    owner_id=row["owner_id"],
                    container_entity_id=row["container_entity_id"],
                )
            )

        return instances

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
        self, user_id: int, entity_instance_id: UUID
    ) -> str | None:
        """Establish focus on an entity instance.

        Delegates to FocusContextService. No cache invalidation needed since
        changing focus just changes which cache key is used for lookups.
        """
        return await self._focus_service.set_focus(user_id, entity_instance_id)

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
        logger.debug("EntityResolution autocomplete cache invalidated")

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
            cache_key = (room, None, ViewMode.ROOM)  # Unfocused state
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
        logger.debug("EntityResolution cache prepopulated for %d rooms", count)
        return count
