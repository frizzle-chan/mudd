# ADR 0001: Static Entity System

## Status

Accepted

## Context

MUDD needs interactable objects in rooms to create an engaging game world. Players should be able to `/look` to see entities in a room and `/interact` with them using natural language verbs. The system must support:

- Reusable entity definitions without repetitive boilerplate
- Human-editable entity data that developers can version control
- Runtime storage for fast entity lookups during gameplay
- Multiple instances of the same entity type across different rooms
- Natural language verb matching (e.g., "smash", "hit", "strike" all trigger the same action)

## Decisions

### Entity Definition Format

In the context of **authoring entity definitions**, facing **the need for human-readable, version-controllable data files**, we decided to **use GNU recutils `.rec` format**, to achieve **plain-text entity definitions that are readable without tooling and easy to edit**, accepting **an additional conversion step to load data into the database**.

The recutils format provides schema validation including unique ID enforcement, foreign key validation for prototype and container references, required field checking, and field whitelisting.

**Jinja2 Templates:**
Text fields (descriptions and handlers) are Jinja2 templates. The template context includes the entity name (formatted for display) and the resolved entity with all properties. This allows inherited templates to reference child entity values.

**`On*` handlers represent actions, not results:**
Handler names describe what the player *does* (the action), not what happens (the result). For example, `OnAttack` is triggered when a player attacks an entity - the handler text describes the outcome, which may or may not result in destruction. This keeps handlers predictable and reusable across entity types.

**Field naming convention:**
All entity fields use PascalCase (e.g., `DescriptionShort`, `OnAttack`). This avoids visual noise from underscores and maintains consistency across the codebase.

### Entity Inheritance Model

In the context of **defining entity behaviors**, facing **repetitive default responses across many entity types** (e.g., "you attack the object, but nothing happens"), we decided to **use prototypical inheritance via a `prototype` field**, to achieve **DRY definitions where child entities inherit all properties from ancestors**, accepting **the complexity of resolving inheritance chains at query time**.

Inheritance chain example:
```
object (base) -> glass_object -> vase
```

A `vase` inherits `OnTouch` from `object` and `OnAttack` from `glass_object`, only defining its own `DescriptionLong`.

**Resolution rules:**
- Child properties override parent properties (first non-NULL wins)
- `On*` handlers are NOT merged - child completely overrides parent
- Circular inheritance is an error detected at load time
- Maximum inheritance depth is capped to prevent runaway chains
- Inheritance is resolved at **query time**, not materialized

### Storage & Persistence

In the context of **runtime entity access**, facing **the need for fast lookups during `/look` and `/interact` commands**, we decided to **store entity models and instances in a relational database**, to achieve **ACID-compliant storage with powerful querying capabilities**, accepting **a database as a runtime dependency**.

The storage layer consists of:
- **Entity definitions table**: Stores entity templates with their properties, prototype references, and container relationships
- **Entity instances table**: Stores placements of entities in rooms, referencing entity definitions

Inheritance resolution happens via recursive queries that walk the prototype chain and return the first non-NULL value for each property.

### Instance Pattern (Flyweight)

In the context of **placing entities in rooms**, facing **multiple instances of the same entity type needing different per-instance state**, we decided to **use the flyweight pattern separating models from instances**, to achieve **memory efficiency and clean separation of definition vs. placement**, accepting **indirection when accessing entity properties**.

```
vase (entity definition)
vase_instance_1 = { entity_id: "vase", room: "tavern" }
vase_instance_2 = { entity_id: "vase", room: "kitchen" }
```

### Interaction Verb Matching

In the context of **parsing `/interact <verb> <entity>` commands**, facing **users typing varied natural language verbs** ("smash", "hit", "strike", "punch"), we decided to **use pre-built word lists mapping synonym groups to action triggers** (e.g., `OnAttack`), to achieve **fast, deterministic verb resolution without external dependencies**, accepting **manual curation of word lists and potential gaps in vocabulary coverage**.

Word lists are curated offline (e.g., using dictionary filtering to find all words meaning "attack"). Each action has its own word list, and verbs are mapped to actions at runtime.

**Fallback behavior:** Unrecognized verbs return a generic response: "You can't do that."

### Data Loading Workflow

In the context of **syncing entity definitions to the database**, facing **the need to populate the database before the bot can serve entity data**, we decided to **use a manual CLI script run by developers before deploy**, to achieve **explicit control over data loading and fast bot startup times**, accepting **the risk of forgetting to run the script before deploy**.

The loader parses `.rec` files, validates entity definitions (unique IDs, valid prototypes, no cycles), and inserts entities into the database with proper ordering for prototype references.

### Room Identification

In the context of **keying entity instances to rooms**, facing **the choice between Discord channel IDs and logical room names**, we decided to **use logical room names** (e.g., "tavern", "armory"), to achieve **readable data files and portability across Discord servers**, accepting **the need for a channel-to-room mapping layer**.

The channel-to-room mapping is maintained as an in-memory cache, populated at bot startup from Discord channel names.

### Entity Disambiguation

In the context of **resolving `/interact` commands**, facing **multiple entities in a room potentially matching the user's input**, we decided to **use word-prefix matching with disambiguation prompts**, to achieve **predictable, fast matching without database queries during autocomplete**, accepting **slightly less flexible matching than fuzzy search**.

**Matching algorithm:**
1. Case-insensitive comparison
2. Matches if ANY word in entity name starts with the query
3. Exact matches (full name) have higher priority than prefix matches
4. Results sorted by match quality

**Resolution flow:**
1. Match user input against all entity names in the room using word-prefix matching
2. If single match: proceed with interaction
3. If multiple matches: show disambiguation prompt listing all matches
4. If no matches: respond with "You don't see that here"

### Verb and Target Selection (Autocomplete-First)

In the context of **parsing `/interact` commands**, facing **the complexity of natural language parsing** (articles, prepositions, multi-word verbs), we decided to **use explicit slash command parameters with Discord autocomplete**, to achieve **predictable UX with zero parsing complexity**, accepting **slightly more verbose command syntax**.

**Command format:**
```
/interact with:<entity> action:<verb>
```

**Benefits over freeform parsing:**
- No article stripping ("the", "a", "an")
- No verb extraction logic
- Entity selection via autocomplete dropdown
- Verb validation happens server-side via word list lookup

**Entity autocomplete:**
- Suggests entities from current room as user types
- Uses word-prefix matching for filtering (same as disambiguation)
- *Note: ADR 0003 introduces `focus_mode` to control interaction context*

### Look Output Format

In the context of **displaying room contents via `/look`**, facing **the choice between terse name lists and descriptive prose**, we decided to **show each entity's `DescriptionShort` rendered as a Jinja2 template with the entity name as a formatted variable**, to achieve **immersive room descriptions where interactable objects are visually distinct**, accepting **the need for every entity to have a `DescriptionShort` (directly or via inheritance)**.

Entity names are wrapped in Discord markdown italics for visual distinction. Entities without a `DescriptionShort` fall back to a generic format.

Example `/look` output:
> The tavern is warm and inviting.
>
> a *Fancy Vase* sits on the mantle. a *Wooden Chair* rests by the fire.

### Entity Containment

In the context of **modeling nested objects** (e.g., a lamp on a table), facing **the need for entities to exist within other entities**, we decided to **add an optional `container_id` field referencing a parent entity**, to achieve **hierarchical entity relationships with automatic child listing**, accepting **single-level nesting only (no containers within containers)**.

**Fields:**
- `container_id` - References the parent entity this item is contained within
- `contents_visible` - Whether children are auto-listed (default: `TRUE`)
  - `TRUE` (table, shelf): Children listed when container appears in room or is examined
  - `FALSE` (chest, drawer): Children not auto-listed in room descriptions; visibility controlled separately from focus behavior
  - *Note: ADR 0003 introduces `focus_mode` to control interaction context separately from visibility*

**Room `/look` behavior:**
- Top-level entities (no `container_id`) appear in room descriptions
- If `contents_visible = TRUE`, children are auto-listed with the container
- If `contents_visible = FALSE`, children are hidden until the container is examined

*Note: ADR 0003 supersedes the stateless container model with a focus-based interaction system.*

**Container examination:**
When examining an entity that has children, auto-append them to the output:
> You see a sturdy wooden table with worn edges.
>
> On the *Wooden Table* you see: a *Brass Lamp*, a *Silver Picture Frame*.

**Interaction targeting:**
1. Search all entities in room (including contained) when resolving targets
2. If single match → proceed with interaction
3. If multiple matches → disambiguate with container context
4. Qualified syntax (`/interact look lamp on table`) narrows search to that container's children

**Validation constraints:**
- `container_id` must reference an existing entity
- Circular containment is an error detected at load time
- Self-containment is prevented
- Multi-level nesting is prohibited: if an entity has a `container_id`, it cannot itself be a container

## Consequences

### Positive

- Entity definitions are human-readable and version-controllable
- Prototypical inheritance eliminates boilerplate responses
- Query-time inheritance provides debuggable entity lookups
- Flyweight pattern scales to many entity instances efficiently
- Word lists provide predictable, debuggable verb matching

### Negative

- Requires a data pipeline: `.rec` files → loader → database
- Query-time inheritance adds complexity vs. materialized properties
- Word lists need manual curation and may miss edge cases

### Future Considerations

- Semantic verb matching (deferred - word lists sufficient for MVP)
- Stateful entities with mutable properties (out of scope for static entity system)
- Admin commands for runtime entity placement
- Player inventory support
