# ADR 0001: Static Entity System

## Status

Proposed

## Context

MUDD needs interactable objects in rooms to create an engaging game world. Players should be able to `/look` to see entities in a room and `/interact` with them using natural language verbs. The system must support:

- Reusable entity definitions without repetitive boilerplate
- Human-editable entity data that developers can version control
- Runtime storage for fast entity lookups during gameplay
- Multiple instances of the same entity type across different rooms
- Natural language verb matching (e.g., "smash", "hit", "strike" all trigger the same action)

## Decisions

### Entity Definition Format

In the context of **authoring entity definitions**, facing **the need for human-readable, version-controllable data files**, we decided to **use GNU recutils `.rec` format**, to achieve **plain-text entity definitions that are readable without tooling and easy to edit**, accepting **an additional conversion step to load data into Valkey**.

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

**Template interpolation:**
Text fields (`DescriptionShort`, `DescriptionLong`, `On*` handlers) support `{name}` placeholder interpolation. At render time, `{name}` is replaced with the entity's `Name` value. This allows reusable descriptions in prototypes.

Example:
```rec
Id: object
DescriptionShort: a {name}
OnTouch: you poke the {name}
```

A child entity with `Name: Fancy Vase` would render `DescriptionShort` as "a Fancy Vase".

**`On*` handlers represent actions, not results:**
Handler names describe what the player *does* (the action), not what happens (the result). For example, `OnAttack` is triggered when a player attacks an entity - the handler text describes the outcome, which may or may not result in destruction. This keeps handlers predictable and reusable across entity types.

**Field naming convention:**
All entity fields use PascalCase (e.g., `DescriptionShort`, `OnAttack`). This avoids visual noise from underscores and maintains consistency across the codebase.

### Entity Inheritance Model

In the context of **defining entity behaviors**, facing **repetitive default responses across many entity types** (e.g., "you attack the object, but nothing happens"), we decided to **use prototypical inheritance via a `prototype` field**, to achieve **DRY definitions where child entities inherit all properties from ancestors**, accepting **the complexity of resolving inheritance chains at load time**.

Inheritance chain example:
```
object (base) -> glass_object -> vase
```

A `vase` inherits `OnTouch` from `object` and `OnAttack` from `glass_object`, only defining its own `DescriptionLong`.

**Resolution rules:**
- Child properties override parent properties (last wins)
- `On*` handlers are NOT merged - child completely overrides parent
- Circular inheritance is an error detected at load time
- Maximum inheritance depth: 10 (prevents runaway chains)

### Storage & Persistence

In the context of **runtime entity access**, facing **the need for fast lookups during `/look` and `/interact` commands**, we decided to **store entity models and instances in Valkey**, to achieve **low-latency access consistent with existing user location storage**, accepting **Valkey as a runtime dependency and the need for a data loading script**.

Key schema:
- `entity:model:{id}` - Entity model definitions (JSON with resolved inheritance)
- `entity:instance:{room_name}:{instance_id}` - Entity placements in rooms
- `room:{room_name}:entities` - SET of instance IDs for O(1) room entity listing

### Instance Pattern (Flyweight)

In the context of **placing entities in rooms**, facing **multiple instances of the same entity type needing different per-instance state**, we decided to **use the flyweight pattern separating models from instances**, to achieve **memory efficiency and clean separation of definition vs. placement**, accepting **indirection when accessing entity properties**.

```
vase_model = { all properties from entity definition }
vase_instance_1 = { model: "vase", room: "tavern", params: {...} }
vase_instance_2 = { model: "vase", room: "kitchen", params: {...} }
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

In the context of **syncing entity definitions to Valkey**, facing **the need to populate Valkey before the bot can serve entity data**, we decided to **use a manual CLI script run by developers before deploy**, to achieve **explicit control over data loading and fast bot startup times**, accepting **the risk of forgetting to run the script before deploy**.

Usage:
```bash
# Load entities into Valkey
python -m mudd.scripts.load_entities --valkey-url $VALKEY_URL data/entities.rec
```

The script:
- Parses `.rec` files using recutils
- Resolves prototype inheritance chains
- Validates entity definitions (unique IDs, valid prototypes, no cycles)
- Writes resolved entity models to Valkey as JSON

### Room Identification

In the context of **keying entity instances to rooms**, facing **the choice between Discord channel IDs and logical room names**, we decided to **use logical room names** (e.g., "tavern", "armory"), to achieve **readable data files and portability across Discord servers**, accepting **the need for a channel-to-room mapping layer**.

Key schema uses room names:
- `entity:instance:{room_name}:{instance_id}` - Entity placements
- `room:{room_name}:entities` - SET of instance IDs

The channel-to-room mapping is maintained as an in-memory cache, populated at bot startup from channel configuration. This cache translates the user's current Discord channel to a room name for entity lookups.

### Entity Disambiguation

In the context of **resolving `/interact` commands**, facing **multiple entities in a room potentially matching the user's input**, we decided to **use fuzzy matching with a "be more specific" response**, to achieve **flexible input handling without stateful interaction**, accepting **the need for users to re-issue commands with more specific names**.

Resolution flow:
1. Normalize user input (lowercase, strip articles like "the", "a", "an")
2. Attempt exact match against entity names in the room
3. If no exact match, attempt fuzzy match (substring, prefix, or similarity threshold) - this tolerates noise words like prepositions ("at", "on") without explicit stripping
4. If single match: proceed with interaction
5. If multiple matches: list matching entities and ask user to be more specific
6. If no matches: respond with "You don't see that here"

Example disambiguation response:
> User: /interact look vase
> Bot: Be more specific. Did you mean: Fancy Vase, Cracked Vase?

### Verb Extraction

In the context of **parsing `/interact <input>` commands**, facing **the need to extract verb and target from natural language input**, we decided to **use first-word extraction with scene-aware fuzzy matching**, to achieve **simple, predictable parsing without NLP dependencies**, accepting **that complex sentence structures (prepositions, multi-word verbs) won't be supported**.

**Parsing rules:**
1. Split input on whitespace
2. First token = verb (looked up in verb mapping)
3. Remaining tokens = target phrase
4. Fuzzy match target phrase against entities in the current room
5. Use existing disambiguation rules (substring, prefix, similarity threshold)

**Examples:**
- `/interact smash the gosh darn vase` → verb: `smash`, target phrase fuzzy-matches "Fancy Vase"
- `/interact look at fancy vase` → verb: `look`, target phrase fuzzy-matches "Fancy Vase"
- `/interact break it` → verb: `break`, no entity match → "You don't see that here"

**Edge cases:**
- Single word input (e.g., `/interact vase`): Treated as entity target with implicit "look" action
- Unknown verb: Falls through to generic "You can't do that" response

### Look Output Format

In the context of **displaying room contents via `/look`**, facing **the choice between terse name lists and descriptive prose**, we decided to **show each entity's `DescriptionShort` with the `{name}` placeholder hydrated in Discord italics**, to achieve **immersive room descriptions where interactable objects are visually distinct**, accepting **the need for every entity to have a `DescriptionShort` (directly or via inheritance)**.

Format: `DescriptionShort` uses a `{name}` template placeholder. The core template system replaces `{name}` with the entity's `Name` value. When rendering for `/look` output specifically, the name is wrapped in Discord markdown italics (`*Name*`) for visual distinction.

Example entity definition:
```rec
Id: vase
Name: Fancy Vase
DescriptionShort: a {name} sits on the mantle
```

Example `/look` output:
> The tavern is warm and inviting.
>
> a *Fancy Vase* sits on the mantle. a *Wooden Chair* rests by the fire.

Entities without a `DescriptionShort` fall back to: "a *{name}* is here."

### Entity Containment

In the context of **modeling nested objects** (e.g., a lamp on a table), facing **the need for entities to exist within other entities**, we decided to **add an optional `Container` field referencing a parent entity**, to achieve **hierarchical entity relationships with automatic child listing**, accepting **single-level nesting only (no containers within containers)**.

**Schema addition:**
```rec
%type: Container rec Entity
%type: ContentsVisible bool
%allowed: Id Name Prototype Container ContentsVisible DescriptionShort DescriptionLong
```

**Fields:**
- `Container` - References the parent entity this item is contained within
- `ContentsVisible` - Whether children are auto-listed (default: `yes`)
  - `yes` (table, shelf): Children listed when container appears in room or is examined
  - `no` (chest, drawer): Children only listed when container is directly examined via `/look`

**Example:**
```rec
Id: table
Name: Wooden Table
Prototype: furniture
DescriptionShort: a {name} sits in the corner
ContentsVisible: yes

Id: lamp
Name: Brass Lamp
Prototype: object
Container: table

Id: chest
Name: Wooden Chest
Prototype: furniture
DescriptionShort: a {name} rests against the wall
ContentsVisible: no

Id: gold_ring
Name: Gold Ring
Prototype: object
Container: chest
```

**Room `/look` behavior:**
- Top-level entities (no `Container`) appear in room descriptions
- If `ContentsVisible: yes`, children are auto-listed with the container
- If `ContentsVisible: no`, children are hidden until the container is examined

**Stateless interactions:**
Containers have no "opened" state. Players can interact with hidden items if they guess correctly - the visibility flag only affects what's shown, not what's accessible.

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
- `Container` must reference an existing entity (enforced by `%type: Container rec Entity`)
- Circular containment (A contains B, B contains A) is an error detected at load time
- Self-containment (A contains A) is an error
- Multi-level nesting is prohibited: if an entity has a `Container`, it cannot itself be a container

## Consequences

### Positive

- Entity definitions are human-readable and version-controllable
- Prototypical inheritance eliminates boilerplate responses
- Valkey provides sub-millisecond entity lookups
- Flyweight pattern scales to many entity instances efficiently
- Word lists provide predictable, debuggable verb matching

### Negative

- Requires a data pipeline: `.rec` files -> Python loader (using `recsel` or parsing) -> Valkey
- Inheritance resolution adds complexity to the loading process
- Word lists need manual curation and may miss edge cases
- Valkey becomes a harder dependency (already present for locations)

### Future Considerations

- Vector database for semantic verb matching (deferred - word lists sufficient for MVP)
- Stateful entities with mutable properties (out of scope for static entity system)
- Admin commands for runtime entity placement via "architect" role

