# ADR 0003: Modal Interaction System

## Status

Accepted

## Addendum (2026-02)

The `focus_mode` field described in this ADR has been replaced with explicit template effects:
- `effects.set_focus()` - Called in `on_open` or `on_use` handlers to establish focus
- `effects.clear_focus()` - Called in `on_close` handlers to clear focus

This change makes focus behavior explicit in templates rather than implicit via a database field, enabling new use cases like setting focus when looking at a painting or using a terminal. The focus infrastructure (user_focus table, FocusContext, EntityModal) remains unchanged.

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

A focus context tracks:
- The user and their current room
- The focused entity (e.g., the chest being examined)
- The focus mode (type of interaction)
- A timestamp for timeout calculation

Container contents are retrieved dynamically rather than stored in the focus context, avoiding stale data if contents change.

### Focus Persistence

In the context of **frequent bot deployments**, facing **the need for focus state to survive restarts**, we decided to **store focus context in the database**, to achieve **seamless UX across deployments**, accepting **additional database queries on interaction**.

Foreign key relationships ensure focus is automatically cleaned up when users, rooms, or entities are deleted.

### Focus Context Service

In the context of **managing per-user focus state**, facing **the need for global access to focus contexts across the application**, we decided to **create a focus context service following the pattern of other services**, to achieve **consistent state management with familiar patterns**, accepting **database persistence with in-memory caching for performance**.

> **Note:** *Superseded by ADR 0004*: The focus context service is now wrapped by a unified entity resolution service. Application code should use the unified service rather than the focus service directly.

**Service operations:**
- **Get focus**: Returns the current focus, or nothing if none exists, the user moved rooms, or the focus expired
- **Set focus**: Creates or updates focus on an entity
- **Clear focus**: Removes focus, optionally returning a close message
- **Update timestamp**: Refreshes the timestamp to prevent timeout during interaction
- **Check focus membership**: Determines if an entity is within the current focus context

### Focus Establishment Rules

In the context of **determining when focus is established**, facing **the need for intuitive, predictable behavior**, we decided to **establish focus only when an open action executes on an entity with focus mode enabled**, to achieve **explicit user intent without surprises**, accepting **that looking at or using entities doesn't change autocomplete behavior**.

**Focus is established when:**
1. User executes an open action (verbs like "open", "unlock")
2. Target entity has a focus mode other than "none"

**Why not on look?** Looking at a container shows its contents in the response, but doesn't change autocomplete. This keeps looking as a read-only action that doesn't establish new state.

**Why not on use?** "Use" has different semantics than "open". You can "use" an open door to walk through it without re-opening it. Separating open/use/close gives entities cleaner, more composable behaviors.

### Focus Mode as First-Class Field

In the context of **determining which entities can establish focus**, facing **the original design's reliance on inferring focus behavior from `contents_visible`**, we decided to **introduce an explicit `focus_mode` field on entities**, to achieve **clear separation between visibility (presentation) and focus behavior (interaction)**, accepting **an additional schema field**.

**The problem with inferring from visibility:**
- Visibility answers "should contents appear in room descriptions?" (presentation concern)
- Focus behavior answers "should this entity capture user attention state?" (interaction concern)
- Conflating these prevents future focus types that aren't about hidden contents (documents, terminals, conversations)

**Focus modes:**

| Mode | Behavior | Example |
|------|----------|---------|
| `none` | No focus established on open | Open door, visible shelf |
| `container` | Focus established on open, contents become autocomplete targets | Chest, vault, locked box |

**Future extension points** (not implemented initially):
- `document` - Focus on pages/sections within a book or file
- `terminal` - Focus on commands/subsystems within a computer
- `conversation` - Focus on dialogue options with an NPC

**Design principle:** Visibility controls what players *see* in room descriptions; focus mode controls what players *interact with* after opening. A chest might have hidden contents (not shown in room view) but establish focus when opened. A shelf might have visible contents (shown in room) but not establish focus when opened.

### Focus Lifecycle

In the context of **managing when focus contexts are destroyed**, facing **the need for intuitive, predictable behavior**, we decided to **clear focus when interacting with unrelated entities, changing rooms, or after inactivity**, to achieve **a simple mental model where focus follows interaction**, accepting **that users must re-open containers after switching context**.

**Focus is cleared when:**
- User interacts with a different entity NOT in current focus contents
- User selects an escape option from autocomplete
- User moves to a different room
- Inactivity timeout (e.g., 5 minutes)
- User explicitly closes via close action

**Focus is NOT cleared when:**
- User interacts with an item inside the focused container
- User looks at any entity (looking is read-only and doesn't affect focus)
- User looks at the room itself

### OnOpen and OnClose Handlers

In the context of **distinguishing opening, using, and closing actions**, facing **the need for clear separation of concerns**, we decided to **add separate OnOpen and OnClose handler fields to entities**, to achieve **clean semantics where "open" opens, "use" uses, and "close" closes**, accepting **new schema fields and verb action types**.

**New entity fields:**
- `on_open` - Handler for opening (chest, door, book)
- `on_close` - Handler for closing

**New verb actions:**
- Open verbs (open, pry, unlock, unseal)
- Close verbs (close, lock, seal, shut)

**Focus behavior:**
- Open action on container with focus mode → establish focus
- Close action → clear focus
- Use action → no focus change

### Autocomplete Enhancement

In the context of **helping users interact with focused container contents**, facing **autocomplete showing all room entities equally**, we decided to **show only focused contents when a container is open, with an escape option to close it**, to achieve **clean autocomplete that prioritizes contextually relevant items**, accepting **that room entities are hidden while focused**.

> **Note:** *Superseded by ADR 0004*: Autocomplete values are now prefixed for unambiguous resolution. The display names remain the same but the underlying values encode the source context.

**Behavior:**
- When focused on a container, autocomplete shows only the container's contents
- A special escape option appears at the top to close the container and return to room view
- Selecting the escape option clears focus and shows the room description

**Example autocomplete when focused on "Wooden Chest":**
```
[Close Wooden Chest] Room        <- escape option
Vinyl Record - Abbey Road        <- focused content
Vinyl Record - Dark Side         <- focused content
Gold Ring                        <- focused content
```

**Example autocomplete with no focus:**
```
Room                             <- view room description
Wooden Chest                     <- room entity
Wooden Table                     <- room entity
Brass Lamp                       <- room entity
```

### Focus-Aware Interaction Flow

In the context of **the interaction command flow**, facing **the need to check and update focus state**, we decided to **integrate focus checks into the existing interaction pipeline**, to achieve **transparent focus management without changing command syntax**, accepting **additional service calls in the interaction handler**.

**Updated flow:**
1. Resolve target entity (unchanged)
2. **NEW:** Check if target is in current focus contents or is the focused container
3. **NEW:** If target is unrelated room entity → clear focus
4. Execute handler (unchanged)
5. **NEW:** After handler executes:
   - If action is open AND entity has container focus mode → establish focus
   - If action is close → clear focus

### Focus-Aware Look Flow

The look command does NOT clear focus. Focus is only cleared by:
- Room movement
- Interaction with an unrelated entity
- Explicit close action
- Inactivity timeout

Looking at entities or the room does not clear focus—only explicit interaction does.

### Entity Schema Changes

In the context of **adding open and close behaviors to entities**, facing **the need for custom open/close responses and explicit focus control**, we decided to **add open handler, close handler, and focus mode fields to entities**, to achieve **separate open, use, and close behaviors with custom templates and explicit focus intent**, accepting **schema migration and loader updates**.

**New fields:**
- `on_open` - Template for open actions
- `on_close` - Template for close actions
- `focus_mode` - Enum controlling focus behavior (none, container)

**Inheritance:** All new fields inherit from prototypes like other handler fields. A null focus mode means "inherit from prototype"; explicit values override.

## Consequences

### Positive

- Dramatically improved UX for containers with many items
- Autocomplete prioritizes contextually relevant entities
- Natural mental model: focus follows attention
- Focus persists across bot restarts
- Graceful degradation: stateless interaction still works if focus is lost
- Clean separation of open, use, and close behaviors
- Composable entity behaviors (door can be opened, walked through, closed as separate actions)
- Explicit focus intent per entity via focus mode field
- Separation of visibility concerns from focus behavior
- Extensible to future focus types via enum values

### Negative

- New database table required for focus state
- Entity schema changes required for new fields
- Two new verb action types and verb files
- Additional database queries on interaction
- Slightly longer autocomplete entries due to escape option

### Future Considerations

- Nested focus (computer → directory → file) - currently single-level only
- Focus-specific actions (e.g., certain verbs only valid when focused)
