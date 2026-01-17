# ADR 0003: Modal Interaction System

## Status

Accepted

## Context

ADR 0001 established a stateless entity interaction model where "containers have no 'opened' state" and "players can interact with hidden items if they guess correctly." While simple, this creates poor UX for containers with many items:

- **The chest problem**: Opening a chest with 20+ items shows a wall of text, then requires typing exact item names to interact
- **No context awareness**: Autocomplete suggests all room entities, not the contents of the container you just opened
- **Cognitive load**: Players must remember item names from a list they just saw

Similar challenges arise with other modal interactions:
- **Books/magazines**: Opening reveals pages or items inside that should become primary interaction targets
- **Computer terminals**: Logging in reveals sub-systems that should be interactable
- **NPC conversations**: Engaging an NPC should make conversation options primary

## Decisions

### Focus Context Model

In the context of **container and modal interactions**, facing **the poor UX of stateless interactions with many-item containers**, we decided to **introduce a "focus context" that tracks the entity a user is currently interacting with**, to achieve **contextual autocomplete that prioritizes relevant items**, accepting **database storage overhead for persistence across bot restarts**.

**Focus context structure:**
```python
@dataclass(frozen=True)
class FocusContext:
    user_id: int
    room: str
    entity_id: str           # The focused entity (e.g., chest)
    entity_name: str         # Display name for autocomplete prefix
    focus_mode: FocusMode    # Type of focus: 'none' or 'container'
    updated_at: datetime     # For timeout calculation
```

Note: Container contents are retrieved dynamically via `get_focused_contents()` rather than stored in the FocusContext dataclass, avoiding stale data if container contents change.

### Focus Persistence

In the context of **frequent bot deployments**, facing **the need for focus state to survive restarts**, we decided to **store focus context in PostgreSQL**, to achieve **seamless UX across deployments**, accepting **additional database queries on interaction**.

**Schema:**
```sql
CREATE TABLE user_focus (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    room TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_user_focus_updated ON user_focus(updated_at);
```

**Foreign keys:**
- `user_id` -> `users(id)` with `ON DELETE CASCADE`: If user is deleted, their focus is deleted
- `room` -> `rooms(id)` with `ON DELETE CASCADE`: If room is deleted, focus in that room is deleted
- `entity_id` -> `entities(id)` with `ON DELETE CASCADE`: If entity is deleted, focus on it is deleted

**Why not in-memory?** The bot is frequently deployed. Losing focus state on restart would frustrate users who just opened a container.

### Focus Context Service

In the context of **managing per-user focus state**, facing **the need for global access to focus contexts across cogs**, we decided to **create a FocusContextService singleton following the pattern of VisibilityService and EntityService**, to achieve **consistent state management with familiar patterns**, accepting **database persistence with in-memory caching for performance**.

**Service interface:**
```python
class FocusContextService:
    async def get_focus(self, user_id: int, room: str) -> FocusContext | None
    async def set_focus(self, user_id: int, room: str, entity: ResolvedEntity) -> str | None
    async def clear_focus(self, user_id: int, reason: str = "interaction") -> str | None
    async def update_focus_timestamp(self, user_id: int) -> None
    async def is_entity_in_focus(self, user_id: int, room: str, entity_id: str) -> bool
    async def get_focused_contents(self, user_id: int, room: str) -> list[str]
```

- `get_focus`: Returns None if no focus, stale (different room), or expired (>5 min). Stale/expired focus is lazily cleaned up.
- `set_focus`: Creates or updates focus. Returns None (no extra message needed for opening).
- `clear_focus`: Clears focus. When `reason="close"`, returns the `on_close` template for rendering.
- `update_focus_timestamp`: Refreshes the timestamp to prevent timeout when interacting with focused content.
- `is_entity_in_focus`: Checks if an entity is the focused container or contained within it.
- `get_focused_contents`: Returns entity IDs accessible through current focus (container + contents).

### Focus Establishment Rules

In the context of **determining when focus is established**, facing **the need for intuitive, predictable behavior**, we decided to **establish focus only when OnOpen executes on an entity with `focus_mode != 'none'`**, to achieve **explicit user intent without surprises**, accepting **that looking at or using entities doesn't change autocomplete behavior**.

**Focus is established when:**
1. User executes an `ON_OPEN` action (verbs like "open", "unlock", "unseal")
2. Target entity has `focus_mode != 'none'`

**Why not OnLook?** Looking at a container shows its contents in the response, but doesn't change autocomplete. This keeps `/look` as a read-only action that doesn't establish new state.

**Why not OnUse?** "Use" has different semantics than "open". You can "use" an open door to walk through it without re-opening it. Separating open/use/close gives entities cleaner, more composable behaviors.

### Focus Mode as First-Class Field

In the context of **determining which entities can establish focus**, facing **the original design's reliance on inferring focus behavior from `contents_visible=False`**, we decided to **introduce an explicit `focus_mode` enum field on entities**, to achieve **clear separation between visibility (presentation) and focus behavior (interaction)**, accepting **an additional schema column**.

**The problem with `contents_visible` inference:**
- `contents_visible` answers "should contents appear in room descriptions?" (presentation concern)
- Focus behavior answers "should this entity capture user attention state?" (interaction concern)
- Conflating these prevents future focus types that aren't about hidden contents (documents, terminals, conversations)

**Focus mode enum:**
```sql
CREATE TYPE focus_mode AS ENUM ('none', 'container');
-- Future values: 'document', 'terminal', 'conversation'
```

| Mode | Behavior | Example |
|------|----------|---------|
| `none` | No focus established on open | Open door, visible shelf |
| `container` | Focus established on open, contents become autocomplete targets | Chest, vault, locked box |

**Future extension points** (not implemented initially):
- `document` - Focus on pages/sections within a book or file
- `terminal` - Focus on commands/subsystems within a computer
- `conversation` - Focus on dialogue options with an NPC

**Design principle:** `contents_visible` controls what players *see* in room descriptions; `focus_mode` controls what players *interact with* after opening. A chest might have `contents_visible=False` (hidden in room view) and `focus_mode='container'` (establishes focus when opened). A shelf might have `contents_visible=True` (items shown in room) and `focus_mode='none'` (opening doesn't change autocomplete priority).

### Focus Lifecycle

In the context of **managing when focus contexts are destroyed**, facing **the need for intuitive, predictable behavior**, we decided to **clear focus when looking at or interacting with unrelated entities, changing rooms, or after 5 minutes of inactivity**, to achieve **a simple mental model where focus follows attention**, accepting **that users must re-open containers after switching context**.

**Focus is cleared when:**
- User interacts with a different entity NOT in current focus contents
- User looks at (`/look at:`) a different entity NOT in current focus contents
- User selects "Room" from autocomplete (the `[Close <container>] Room` option)
- User moves to a different room
- 5 minutes pass without interaction
- User explicitly closes via `/interact close <container>`

**Focus is NOT cleared when:**
- User interacts with an item inside the focused container
- User looks at an item inside the focused container
- User looks at the room itself (`/look` with no target)
- User looks at the focused container itself

**Why does looking break focus?** If you're looking at something across the room, you're no longer standing at the open chest. The physical metaphor is that you've walked away.

### OnOpen and OnClose Handlers

In the context of **distinguishing opening, using, and closing actions**, facing **the need for clear separation of concerns**, we decided to **add separate OnOpen and OnClose handler fields to entities**, to achieve **clean semantics where "open" opens, "use" uses, and "close" closes**, accepting **two new schema columns and verb action types**.

**New entity fields:**
- `on_open TEXT` - Handler for opening (chest, door, book)
- `on_close TEXT` - Handler for closing

**New verb actions:**
- `ON_OPEN` added to `verb_action` enum
- `ON_CLOSE` added to `verb_action` enum

**Verb files:**
- `data/verbs/on_open.txt`:
  ```
  open
  pry
  unlock
  unseal
  ```
- `data/verbs/on_close.txt`:
  ```
  close
  lock
  seal
  shut
  ```

**Example templates:**
```jinja
{# OnOpen - for opening a chest #}
You open the {{ name }}.{{ contents }}

{# OnClose - for closing a chest #}
You close the {{ name }}.

{# OnUse - for using something (e.g., walking through an open door) #}
You walk through the {{ name }}.
```

**Focus behavior:**
- `ON_OPEN` on closed container -> establish focus
- `ON_CLOSE` -> clear focus
- `ON_USE` -> no focus change (use is independent of open/close)

### Autocomplete Enhancement

In the context of **helping users interact with focused container contents**, facing **autocomplete showing all room entities equally**, we decided to **prepend focused contents with a distinguishing prefix and list them first**, to achieve **obvious visual distinction and easy selection of contextually relevant items**, accepting **longer autocomplete entries due to prefix**.

**Format:**
```
[Container Name] Item Name
```

**Example autocomplete order:**
```
[Wooden Chest] Vinyl Record - Abbey Road
[Wooden Chest] Vinyl Record - Dark Side
[Wooden Chest] Gold Ring
Wooden Table                    <- room entity
Brass Lamp                      <- room entity
```

**Disambiguation behavior:** When a query matches both focused and room entities, focused matches appear first. User sees a combined list with focused items prioritized.

### Focus-Aware Interaction Flow

In the context of **the /interact command flow**, facing **the need to check and update focus state**, we decided to **integrate focus checks into the existing interaction pipeline**, to achieve **transparent focus management without changing command syntax**, accepting **additional service calls in the interact cog**.

**Updated flow:**
1. Resolve target entity (unchanged)
2. **NEW:** Check if target is in current focus contents or is the focused container
3. **NEW:** If target is unrelated room entity -> clear focus
4. Execute handler (unchanged)
5. **NEW:** After handler executes:
   - If action is `ON_OPEN` AND entity is closed container -> establish focus
   - If action is `ON_CLOSE` -> clear focus

### Focus-Aware Look Flow

In the context of **the /look command flow**, facing **the need to clear focus when attention shifts**, we decided to **clear focus when looking at unrelated entities**, to achieve **consistent "attention follows gaze" behavior**, accepting **additional service calls in the look cog**.

**Updated flow:**
1. **NEW:** If looking at specific entity (`/look at:<target>`)
2. **NEW:** Check if target is in current focus or is the focused container
3. **NEW:** If target is unrelated -> clear focus
4. Execute look (unchanged)

**Note:** `/look` with no target (view room) does NOT clear focus.

### Entity Schema Changes

In the context of **adding open and close behaviors to entities**, facing **the need for custom open/close responses and explicit focus control**, we decided to **add `on_open`, `on_close`, and `focus_mode` columns to the entities table**, to achieve **separate open, use, and close behaviors with custom templates and explicit focus intent**, accepting **schema migration and loader updates**.

**Schema change:**
```sql
-- Focus mode enum
CREATE TYPE focus_mode AS ENUM ('none', 'container');
-- Future: 'document', 'terminal', 'conversation'

-- Handler columns
ALTER TABLE entities ADD COLUMN on_open TEXT;
ALTER TABLE entities ADD COLUMN on_close TEXT;

-- Focus mode column (nullable for prototype inheritance)
ALTER TABLE entities ADD COLUMN focus_mode focus_mode DEFAULT NULL;
```

**Recutils fields:** `OnOpen`, `OnClose`, `FocusMode` (same pattern as OnLook, OnUse, etc.)

**Inheritance:** `on_open`, `on_close`, and `focus_mode` inherit from prototypes like other handler fields. Include `focus_mode` in `resolve_entity()` inheritance chain. `focus_mode` is nullable: NULL means "inherit from prototype", explicit values override.

**Focus behavior** is controlled by the resolved `focus_mode` field:
- `focus_mode=NULL` -> inherit from prototype (default for derived entities)
- `focus_mode='none'` -> explicitly no focus (open door, visible shelf)
- `focus_mode='container'` -> focus established on OnOpen, cleared on OnClose (chest, vault)

## Consequences

### Positive

- Dramatically improved UX for containers with many items
- Autocomplete prioritizes contextually relevant entities
- Natural mental model: focus follows attention
- Focus persists across bot restarts
- Graceful degradation: stateless interaction still works if focus is lost
- Clean separation of open (OnOpen), use (OnUse), and close (OnClose) behaviors
- Composable entity behaviors (door can be opened, walked through, closed as separate actions)
- Explicit focus intent per entity via `focus_mode` field
- Separation of visibility concerns (`contents_visible`) from focus behavior (`focus_mode`)
- Extensible to future focus types (document, terminal, conversation) via enum values

### Negative

- New database table required (`user_focus`)
- Entity schema changes required (new `on_open`, `on_close`, and `focus_mode` columns)
- Two new verb action types (`ON_OPEN`, `ON_CLOSE`) and verb files
- Additional database queries on interaction/look
- Slightly longer autocomplete entries due to prefix

### Future Considerations

- Nested focus (computer -> directory -> file) - currently single-level only
- Focus-specific actions (e.g., certain verbs only valid when focused)
