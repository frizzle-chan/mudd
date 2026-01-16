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

In the context of **authoring entity definitions**, facing **the need for human-readable, version-controllable data files**, we decided to **use GNU recutils `.rec` format**, to achieve **plain-text entity definitions that are readable without tooling and easy to edit**, accepting **an additional conversion step to load data into PostgreSQL**.

Example recutils format with schema validation:
```rec
%rec: Entity
%key: Id
%type: Prototype rec Entity
%type: Container rec Entity
%mandatory: Id Name
%allowed: Id Name Prototype Container DescriptionShort DescriptionLong
%allowed: OnLook OnTouch OnAttack OnUse OnTake

Id: vase
Name: Fancy Vase
Prototype: glass_object
DescriptionLong: A blue ceramic vase
+ with a flower pattern on it
+ and gold trim around the rim.
```

The `%rec` descriptor enables:
- `%key: Id` - Ensures unique entity IDs
- `%type: Prototype rec Entity` - Validates prototype references exist
- `%type: Container rec Entity` - Validates container references exist
- `%mandatory` - Required fields for all entities
- `%allowed` - Whitelist of valid field names

**Jinja2 Templates:**
Text fields (`DescriptionShort`, `DescriptionLong`, `On*` handlers) are Jinja2 templates. The template context includes:
- `name`: Entity name formatted with Discord italics (`*Name*`)
- `e`: The resolved entity with all properties

Example:
```rec
Id: object
DescriptionShort: a {{ name }}
OnTouch: you poke the {{ name }}
OnLook: {{ e.description_long or e.description_short or "You see nothing special." }}
```

A child entity with `Name: Fancy Vase` would render `DescriptionShort` as "a *Fancy Vase*".

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
- Maximum inheritance depth: 10 (prevents runaway chains)
- Inheritance is resolved at **query time** via recursive CTEs, not materialized

### Storage & Persistence

In the context of **runtime entity access**, facing **the need for fast lookups during `/look` and `/interact` commands**, we decided to **store entity models and instances in PostgreSQL**, to achieve **ACID-compliant storage with powerful querying capabilities**, accepting **PostgreSQL as a runtime dependency**.

**Schema:**

```sql
-- Enable fuzzy matching for entity name search
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    prototype_id TEXT REFERENCES entities(id),

    -- Descriptions (Jinja2 templates with {{ name }} and {{ e.* }} support)
    description_short TEXT,
    description_long TEXT,

    -- Handlers: NULL means "inherit from prototype"
    on_look TEXT,
    on_touch TEXT,
    on_attack TEXT,
    on_use TEXT,
    on_take TEXT,

    -- Containment (for nested objects like "lamp on table")
    container_id TEXT REFERENCES entities(id),
    contents_visible BOOLEAN,

    CHECK (id != prototype_id),
    CHECK (id != container_id)
);

CREATE TABLE entity_instances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id TEXT NOT NULL REFERENCES entities(id),
    room TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_entity_instances_room ON entity_instances(room);
CREATE INDEX idx_entities_name_trgm ON entities USING gin(name gin_trgm_ops);
CREATE INDEX idx_entities_prototype ON entities(prototype_id);
```

**Inheritance resolution function:**

```sql
CREATE OR REPLACE FUNCTION resolve_entity(target_id TEXT)
RETURNS TABLE (
    id TEXT, name TEXT, description_short TEXT, description_long TEXT,
    on_look TEXT, on_touch TEXT, on_attack TEXT, on_use TEXT, on_take TEXT,
    contents_visible BOOLEAN
) AS $$
WITH RECURSIVE inheritance_chain AS (
    SELECT e.*, 0 AS depth FROM entities e WHERE e.id = target_id
    UNION ALL
    SELECT e.*, ic.depth + 1
    FROM entities e JOIN inheritance_chain ic ON e.id = ic.prototype_id
    WHERE ic.depth < 10
)
SELECT target_id,
    (SELECT name FROM inheritance_chain WHERE name IS NOT NULL ORDER BY depth LIMIT 1),
    (SELECT description_short FROM inheritance_chain WHERE description_short IS NOT NULL ORDER BY depth LIMIT 1),
    (SELECT description_long FROM inheritance_chain WHERE description_long IS NOT NULL ORDER BY depth LIMIT 1),
    (SELECT on_look FROM inheritance_chain WHERE on_look IS NOT NULL ORDER BY depth LIMIT 1),
    (SELECT on_touch FROM inheritance_chain WHERE on_touch IS NOT NULL ORDER BY depth LIMIT 1),
    (SELECT on_attack FROM inheritance_chain WHERE on_attack IS NOT NULL ORDER BY depth LIMIT 1),
    (SELECT on_use FROM inheritance_chain WHERE on_use IS NOT NULL ORDER BY depth LIMIT 1),
    (SELECT on_take FROM inheritance_chain WHERE on_take IS NOT NULL ORDER BY depth LIMIT 1),
    (SELECT contents_visible FROM inheritance_chain WHERE contents_visible IS NOT NULL ORDER BY depth LIMIT 1);
$$ LANGUAGE sql STABLE;
```

### Instance Pattern (Flyweight)

In the context of **placing entities in rooms**, facing **multiple instances of the same entity type needing different per-instance state**, we decided to **use the flyweight pattern separating models from instances**, to achieve **memory efficiency and clean separation of definition vs. placement**, accepting **indirection when accessing entity properties**.

```
vase (entity definition in entities table)
vase_instance_1 = { entity_id: "vase", room: "tavern" }
vase_instance_2 = { entity_id: "vase", room: "kitchen" }
```

### Interaction Verb Matching

In the context of **parsing `/interact <verb> <entity>` commands**, facing **users typing varied natural language verbs** ("smash", "hit", "strike", "punch"), we decided to **use pre-built word lists mapping synonym groups to action triggers** (e.g., `OnAttack`), to achieve **fast, deterministic verb resolution without external dependencies**, accepting **manual curation of word lists and potential gaps in vocabulary coverage**.

Word list generation: One-time offline task using dictionary filtering (e.g., find all words meaning "attack").

**Fallback behavior:** Unrecognized verbs return a generic response: "You can't do that."

**Word list format** (flat files, one per action):
- Files named by action: `OnAttack.txt`, `OnLook.txt`, `OnTouch.txt`, etc.
- Each file contains verbs that trigger that action, one word per line
- Loaded into a dictionary at runtime mapping verb → action

Example `data/verbs/OnAttack.txt`:
```
attack
bash
hit
punch
slash
smash
strike
```

### Data Loading Workflow

In the context of **syncing entity definitions to PostgreSQL**, facing **the need to populate the database before the bot can serve entity data**, we decided to **use a manual CLI script run by developers before deploy**, to achieve **explicit control over data loading and fast bot startup times**, accepting **the risk of forgetting to run the script before deploy**.

Usage:
```bash
python -m mudd.scripts.load_entities data/entities.rec
```

The script:
- Parses `.rec` files using recutils
- Validates entity definitions (unique IDs, valid prototypes, no cycles)
- Inserts entities into PostgreSQL (prototype references require proper ordering)

### Room Identification

In the context of **keying entity instances to rooms**, facing **the choice between Discord channel IDs and logical room names**, we decided to **use logical room names** (e.g., "tavern", "armory"), to achieve **readable data files and portability across Discord servers**, accepting **the need for a channel-to-room mapping layer**.

The `entity_instances.room` column stores logical room names. The channel-to-room mapping is maintained as an in-memory cache, populated at bot startup from Discord channel names.

### Entity Disambiguation

In the context of **resolving `/interact` commands**, facing **multiple entities in a room potentially matching the user's input**, we decided to **use word-prefix matching with disambiguation prompts**, to achieve **predictable, fast matching without database queries during autocomplete**, accepting **slightly less flexible matching than fuzzy search**.

**Matching algorithm** (implemented in `entity_matcher.py`):
1. Case-insensitive comparison
2. Matches if ANY word in entity name starts with the query
3. Exact matches (full name) have higher priority than prefix matches
4. Results sorted by match quality

**Examples:**
- `"tab"` matches "Wooden Table" (word "Table" starts with "tab")
- `"wood"` matches "Wooden Table" (word "Wooden" starts with "wood")
- `"Wooden Table"` is an exact match (highest priority)

**Resolution flow:**
1. Match user input against all entity names in the room using word-prefix matching
2. If single match: proceed with interaction
3. If multiple matches: show disambiguation prompt listing all matches
4. If no matches: respond with "You don't see that here"

**Example disambiguation response:**
> User: /interact do:smash target:vase
> Bot: Which one? *Fancy Vase*, *Cracked Vase*

### Verb and Target Selection (Autocomplete-First)

In the context of **parsing `/interact` commands**, facing **the complexity of natural language parsing** (articles, prepositions, multi-word verbs), we decided to **use explicit slash command parameters with Discord autocomplete**, to achieve **predictable UX with zero parsing complexity**, accepting **slightly more verbose command syntax**.

**Command format:**
```
/interact do:<verb> target:<entity>
```

**Benefits over freeform parsing:**
- No article stripping ("the", "a", "an")
- No verb extraction logic
- Entity selection via autocomplete dropdown
- Verb validation happens server-side via word list lookup

**Verb resolution** (implemented in `verb_matcher.py`):
1. Look up verb in `verbs` table using pg_trgm fuzzy matching
2. If match found: map to action handler (`on_attack`, `on_touch`, etc.)
3. If no match: respond with "You can't do that"

**Entity autocomplete:**
- Suggests entities from current room as user types
- Uses word-prefix matching for filtering (same as disambiguation)
- ~~Excludes entities inside containers with `contents_visible=FALSE`~~
- *Superseded by ADR 0003*: Entity autocomplete is now controlled by focus context, not `contents_visible`

**Example:**
> User types: `/interact do:smash target:va`
> Autocomplete suggests: "Fancy Vase", "Cracked Vase"
> User selects: "Fancy Vase"
> Bot executes: attack handler for Fancy Vase

### Look Output Format

In the context of **displaying room contents via `/look`**, facing **the choice between terse name lists and descriptive prose**, we decided to **show each entity's `DescriptionShort` rendered as a Jinja2 template with `{{ name }}` as a formatted variable**, to achieve **immersive room descriptions where interactable objects are visually distinct**, accepting **the need for every entity to have a `DescriptionShort` (directly or via inheritance)**.

Format: `DescriptionShort` is a Jinja2 template. The `{{ name }}` variable is replaced with the entity's `Name` value wrapped in Discord markdown italics (`*Name*`) for visual distinction.

Example entity definition:
```rec
Id: vase
Name: Fancy Vase
DescriptionShort: a {{ name }} sits on the mantle
```

Example `/look` output:
> The tavern is warm and inviting.
>
> a *Fancy Vase* sits on the mantle. a *Wooden Chair* rests by the fire.

Entities without a `DescriptionShort` fall back to: "a *{entity name}* is here."

### Entity Containment

In the context of **modeling nested objects** (e.g., a lamp on a table), facing **the need for entities to exist within other entities**, we decided to **add an optional `container_id` field referencing a parent entity**, to achieve **hierarchical entity relationships with automatic child listing**, accepting **single-level nesting only (no containers within containers)**.

**Fields:**
- `container_id` - References the parent entity this item is contained within
- `contents_visible` - Whether children are auto-listed (default: `TRUE`)
  - `TRUE` (table, shelf): Children listed when container appears in room or is examined
  - ~~`FALSE` (chest, drawer): Children only listed when container is directly examined via `/look`~~
  - `FALSE` (chest, drawer): Children not auto-listed in room descriptions; visibility controlled separately from focus behavior
  - *Note: ADR 0003 introduces `focus_mode` to control interaction context separately from visibility*

**Example:**
```sql
INSERT INTO entities (id, name, prototype_id, description_short, contents_visible) VALUES
('table', 'Wooden Table', 'furniture', 'a {{ name }} sits in the corner', TRUE),
('lamp', 'Brass Lamp', 'object', NULL, NULL),
('chest', 'Wooden Chest', 'furniture', 'a {{ name }} rests against the wall', FALSE),
('gold_ring', 'Gold Ring', 'object', 'a {{ name }}', NULL);

UPDATE entities SET container_id = 'table' WHERE id = 'lamp';
UPDATE entities SET container_id = 'chest' WHERE id = 'gold_ring';
```

**Room `/look` behavior:**
- Top-level entities (no `container_id`) appear in room descriptions
- If `contents_visible = TRUE`, children are auto-listed with the container
- If `contents_visible = FALSE`, children are hidden until the container is examined

~~**Stateless interactions:**~~
~~Containers have no "opened" state. Players can interact with hidden items if they guess correctly - the visibility flag only affects what's shown, not what's accessible.~~

*Superseded by ADR 0003*: The modal interaction system introduces focus context to track which container a player is interacting with. See ADR 0003 for focus establishment and lifecycle rules.

**Container examination:**
When examining an entity that has children, auto-append them to the output:
> You see a sturdy wooden table with worn edges.
>
> On the *Wooden Table* you see: a *Brass Lamp*, a *Silver Picture Frame*.

**Interaction targeting:**
1. Search **all entities in room** (including contained) when resolving targets
2. If single match → proceed with interaction
3. If multiple matches → disambiguate with container context: "Be more specific. Did you mean: Brass Lamp (on Wooden Table), Brass Lamp (on Nightstand)?"
4. Qualified syntax (`/interact look lamp on table`) narrows search to that container's children

**Validation constraints:**
- `container_id` must reference an existing entity (enforced by foreign key)
- Circular containment (A contains B, B contains A) is an error detected at load time
- Self-containment (A contains A) is prevented by CHECK constraint
- Multi-level nesting is prohibited: if an entity has a `container_id`, it cannot itself be a container

## Consequences

### Positive

- Entity definitions are human-readable and version-controllable
- Prototypical inheritance eliminates boilerplate responses
- PostgreSQL with query-time inheritance provides debuggable entity lookups
- Explicit columns make it easy to inspect entities in the database
- `pg_trgm` enables fuzzy entity name matching with typo tolerance
- Flyweight pattern scales to many entity instances efficiently
- Word lists provide predictable, debuggable verb matching

### Negative

- Requires a data pipeline: `.rec` files → Python loader → PostgreSQL
- Query-time inheritance adds complexity vs. materialized properties
- Word lists need manual curation and may miss edge cases
- PostgreSQL is a heavier operational dependency but provides ACID guarantees

### Future Considerations

- Vector database for semantic verb matching (deferred - word lists sufficient for MVP)
- Stateful entities with mutable properties (out of scope for static entity system)
- Admin commands for runtime entity placement via "architect" role
- Player inventory support via `owner_id` column on `entity_instances`
