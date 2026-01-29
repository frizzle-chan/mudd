# ADR 0006: Focus as Template Effect

## Status

Accepted

## Context

ADR 0003 introduced the modal interaction system with `focus_mode` as a schema-level enum controlling whether `ON_OPEN` establishes focus. While functional, this approach has several problems:

**1. Inflexible focus establishment**: Focus can only be established via `ON_OPEN` on entities with `focus_mode != 'none'`. This prevents natural interactions like:
- Studying a detailed painting should focus on its details
- Reading a document should focus on its pages
- Examining a puzzle should focus on its components

**2. Duplicated spaghetti code**: Focus management logic is scattered across multiple cogs:
- `/look` cog checks `is_entity_in_focus`, clears focus if not in focus, updates timestamp if in focus
- `/interact` cog has identical duplicated logic
- `OpenCommand` and `CloseCommand` have hardcoded focus behavior

**3. Special-cased escape mechanism**: The `[Close X] Room` autocomplete option is hardcoded in `EntityResolutionService` rather than being a proper entity. This creates special-case code paths throughout the resolution system.

**4. Mixed abstraction levels**: `focus_mode` is declarative (a property) but focus behavior is imperative (something that happens). This creates a confusing mental model where the schema declares intent but commands implement behavior.

## Decisions

### Focus Effects in Templates

In the context of **flexible focus control**, facing **the limitation that only ON_OPEN can establish focus**, we decided to **add `effects.set_focus()` and `effects.clear_focus()` template functions**, to achieve **any handler being able to control focus state**, accepting **migration of existing entities to use the new effects**.

**New template effects:**
```python
class TriggerEffects:
    def set_focus(self) -> str:
        """Establish focus on the current entity. Returns empty string."""
        self._set_focus = True
        return ""

    def clear_focus(self) -> str:
        """Clear the user's current focus. Returns empty string."""
        self._clear_focus = True
        return ""
```

**Example usage in templates:**
```jinja
{# Painting on_look - studying it focuses on details #}
{{ effects.set_focus() }}You study the {{ name }} closely.

The brushwork reveals incredible detail...

{# Container on_open - traditional container behavior #}
{{ effects.set_focus() }}You open the {{ name }}.{{ contents }}

{# Container on_close #}
{{ effects.clear_focus() }}You close the {{ name }}.
```

### Room as Entity

In the context of **the special-cased escape mechanism**, facing **hardcoded `[Close X] Room` logic scattered throughout resolution**, we decided to **create actual room entities in the database**, to achieve **unified entity resolution where room is just another entity**, accepting **additional entities in the database and sync complexity**.

**Room entity design:**
- **ID convention**: Namespaced as `room:<room_id>` (e.g., `room:foyer`, `room:office`)
- **Name**: The actual room name (e.g., "Foyer", "Office") - display as "Room" happens at autocomplete time
- **Prototype**: All room entities inherit from `base-room`
- **Creation**: Room entities and instances are created during zone sync when rooms are synced
- **Autocomplete position**: Room entity always appears first in autocomplete results

**Schema implications:**
```sql
-- Room entities created during sync
-- Example: room entity for 'foyer'
INSERT INTO entities (id, name, prototype)
VALUES ('room:foyer', 'Foyer', 'base-room');

-- Room instances created during sync (one per room)
INSERT INTO entity_instances (id, entity_id, room)
VALUES (gen_random_uuid(), 'room:foyer', 'foyer');
```

**Autocomplete display**: The `[Close X] Room` or `Room` display name is computed at autocomplete time based on focus state, not stored in the database.

### /look with No Target

In the context of **`/look` command with no target**, facing **special-case code for showing room description**, we decided to **implicitly resolve to the room entity and execute its `on_look` handler**, to achieve **unified code path where all lookups go through entity resolution**, accepting **that room entity must exist for `/look` to work**.

### Room Template Context

In the context of **room entities needing access to room data**, facing **the need for room description and visible entities in templates**, we decided to **provide lazy `room.description()` and `room.entities()` template functions**, to achieve **on-demand fetching since room lookups are rare**, accepting **special template context for room entities**.

**Template functions:**
```python
class RoomContext:
    """Lazy room data access for room entity templates."""

    def __init__(self, room_id: str, services: ...):
        self._room_id = room_id
        self._services = services

    async def description(self) -> str:
        """Fetch room description (channel topic)."""
        # Returns the room's description from rooms table or channel topic

    async def entities(self) -> str:
        """Fetch formatted list of visible entities."""
        # Returns formatted entity list like current room rendering
```

**Base room template:**
```jinja
{# base-room on_look #}
{{ effects.clear_focus() }}{{ room.description() }}

{{ room.entities() }}
```

### Simplified Focus Lifecycle

In the context of **focus clearing triggers**, facing **redundant "interacting with unrelated entity clears focus" logic**, we decided to **remove the unrelated-entity clearing since focused state prevents interacting with unfocused entities anyway**, to achieve **simpler mental model and less code**, accepting **that focus clearing now happens only via explicit mechanisms**.

**Focus is cleared when:**
- `effects.clear_focus()` is called in a template
- User moves to a different room (`/move` command)
- 5-minute inactivity timeout

**Removed trigger:**
- ~~Interacting with entity not in current focus~~ (not reachable when focused anyway)

### Deprecate focus_mode Column

In the context of **migrating to effect-based focus**, facing **the now-redundant `focus_mode` schema column**, we decided to **deprecate `focus_mode` but keep the column temporarily**, to achieve **backwards compatibility during migration**, accepting **temporary schema cruft**.

**Migration path:**
1. Add `effects.set_focus()` and `effects.clear_focus()` to TriggerEffects
2. Update `base-container` prototype to use `effects.set_focus()` in `on_open`
3. Update `base-container` prototype to use `effects.clear_focus()` in `on_close`
4. Remove `focus_mode` checks from `OpenCommand` and `CloseCommand`
5. Remove duplicated focus logic from `/look` and `/interact` cogs
6. Create room entities during sync
7. Update autocomplete to use room entities instead of hardcoded escape option
8. Future: Remove `focus_mode` column entirely

### Remove Hardcoded Command Focus Logic

In the context of **OpenCommand and CloseCommand having hardcoded focus behavior**, facing **the shift to template-controlled focus**, we decided to **remove focus logic from commands and let templates control focus via effects**, to achieve **consistent effect-based control**, accepting **that all focus-establishing entities must call `effects.set_focus()` explicitly**.

**Before (OpenCommand):**
```python
def execute(self, ctx: ActionContext) -> ActionResult:
    # ... render template ...
    if ctx.entity.focus_mode != "none":
        return ActionResult(..., set_focus=ctx.entity)
```

**After (OpenCommand):**
```python
def execute(self, ctx: ActionContext) -> ActionResult:
    # ... render template ...
    # Focus handled by effects.set_focus() in template
    return ActionResult(...)
```

## Consequences

### Positive

- Any handler can establish focus (paintings, documents, puzzles)
- Room is a proper entity with unified resolution path
- Removed duplicated focus logic from cogs
- Simpler mental model: templates control behavior via effects
- Extensible: new focus behaviors don't require schema changes
- Room rendering uses lazy evaluation (efficient for rare lookups)

### Negative

- Migration complexity for existing entities
- Additional entities in database (one per room)
- Sync must create/maintain room entities
- `focus_mode` column becomes cruft until removed
- Templates must explicitly call `effects.set_focus()` (no implicit behavior)

### Future Considerations

- `effects.set_focus(entity_id)` - focus on a different entity than the one being interacted with
- Rooms as actual containers for entities (parent-child relationship)
- Remove `focus_mode` column after migration verified complete
