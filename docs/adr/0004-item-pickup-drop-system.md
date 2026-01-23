# ADR 0004: Item Pickup and Drop System

## Status

Proposed

## Context

ADR 0002 introduced a basic inventory system. However, several gameplay scenarios were unsupported:

- **Quest items**: Items like a map in a treasure chest that every player can take once, but remain visible in the world for others.
- **Respawning items**: Consumables like beverages in a fridge that are removed when taken but periodically respawn.
- **Randomized spawns**: Spawn locations that draw from a pool of possible items with different rarities (common beer vs. rare champagne).
- **Dropping items**: Players need to drop items from their inventory back into rooms, with control over which items can be dropped.
- **Item granting**: Templates need to grant items as rewards (e.g., smashing a vase reveals a hidden key).
- **Flood prevention**: Without limits, players could spam-drop items to clutter rooms.

## Decisions

### Pickup Behavior via Template Effects

In the context of **controlling whether items can be picked up**, facing **the need for flexible, template-driven pickup behavior**, we decided to **use `effects.pickup()` in `on_take` templates to signal pickup intent**, to achieve **full template control over pickup logic**, accepting **that all pickable items must explicitly call `effects.pickup()`**.

**Behavior:**
- If `on_take` template calls `effects.pickup()`: item is picked up
- If `on_take` template doesn't call `effects.pickup()`: only the message is shown, item stays in room
- Quest items (`rarity=quest`) are cloned on pickup (original stays visible for other players)

### Quest Item Take Limit via Inventory Check

In the context of **quest items that should be takeable once per player**, facing **the need to prevent duplicate pickups while keeping items visible for others**, we decided to **check the player's inventory for an existing instance of the entity before allowing pickup**, to achieve **simple duplicate prevention using existing data structures**, accepting **that dropping and re-taking a quest item is allowed (inventory check, not historical tracking)**.

**Behavior:**
- On take attempt for `rarity=quest` entity:
  - Query `entity_instances` for `owner_id=user AND entity_id=target`
  - If found: "You already have this."
  - If not found: Create new instance in inventory (clone behavior)
- Item remains visible in world for all users

### Entity Tags and Rarity

In the context of **categorizing entities for spawning pools**, facing **the need to group items by type and control spawn frequency**, we decided to **add a tags system and rarity enum to entities**, to achieve **flexible categorization and weighted random selection**, accepting **additional schema complexity and content authoring overhead**.

**Tags:**
- Many-to-many relationship via `entity_tags` table
- Space-separated in `.rec` files (e.g., `Tags: beverage alcoholic`)
- Enable queries like "all beverages" or "all weapons"

**Rarity Tiers:**

| Emoji | Tier | Spawn Weight | Odds |
|-------|------|--------------|------|
| (none) | None | 0 | Not spawned |
| ⚪ | Common | 600 | 60% |
| 🟢 | Uncommon | 250 | 25% |
| 🔵 | Rare | 100 | 10% |
| 🟣 | Epic | 40 | 4% |
| 🟠 | Legendary | 9 | 0.9% |
| ㊙️ | Mythic | 1 | 0.1% |
| 🔷 | Quest | — | Not spawned |

- Weights sum to 1000 for precise probability calculation (excluding none and quest)
- **None**: Default for all entities. Static world items that cannot be picked up and shouldn't appear in spawning pools. Displays no emoji suffix.
- Quest items never spawn from pools—placed deliberately or granted via `effects.grant()`
- Rarity indicates discovery difficulty only, not power level
- No zone-based weight modifiers (same odds everywhere)

**Display Names:**
- Item names are displayed with their rarity icon suffix when applicable
- Format: `{name} {rarity_icon}` (e.g., "Beer ⚪", "White Claw 🔵", "Rusty Key 🔷")
- Items with "none" rarity display just the name with no emoji suffix
- The `display_name` property on entities and returned objects includes this formatting
- Templates should use `display_name` rather than `name` when showing items to players

### Spawning Pool System

In the context of **respawning items in the world**, facing **the need for items to reappear after being taken, with randomized variety**, we decided to **introduce spawning pools that query entities by tag and select randomly weighted by rarity**, to achieve **dynamic, varied item respawning without manual placement**, accepting **a background task for respawn processing and additional schema tables**.

**Spawning pool definition:**
- `id`: Unique identifier
- `room`: Room where items spawn
- `container_id`: Optional parent entity (e.g., fridge, chest)
- `tag_query`: Tag to filter eligible entities
- `max_count`: Maximum concurrent instances from this pool
- `respawn_interval_minutes`: Time between respawns in minutes (default: 30)

**Respawn algorithm:**
1. Background task runs periodically
2. For each spawning pool, count current instances
3. If below `max_count` and `respawn_interval` elapsed since last spawn:
   - Query entities matching `tag_query` (excluding `quest` rarity)
   - Roll 0-999 for weighted random selection
   - 0-599=Common, 600-849=Uncommon, 850-949=Rare, 950-989=Epic, 990-998=Legendary, 999=Mythic
   - Create instance linked to spawning pool

**Example:** Fridge spawning pool
```rec
Id: fridge-beverages
Room: lounge
Container: fridge
TagQuery: beverage
MaxCount: 3
RespawnIntervalMinutes: 30
```

Matching entities: Beer (common), White Monster (uncommon), White Claw (rare)

Most spawns = Beer, occasionally White Monster, rarely White Claw.

### On-Drop Handler Pattern

In the context of **allowing players to drop items from inventory**, facing **the need to control which items can be dropped and customize drop behavior**, we decided to **add an `on_drop` handler field following the existing handler pattern**, to achieve **template-driven drop behavior with side effects**, accepting **that items without an `on_drop` handler cannot be dropped**.

**Behavior:**
- No `on_drop` defined: "You can't drop that."
- `on_drop` defined: Execute template, which must call `effects.drop()` to perform the drop

**Template side effects:**
- `effects.drop()`: Moves instance from inventory to current room, sets `player_dropped=TRUE`
- `effects.broadcast(message)`: Announces the drop to the room (existing effect)

**Example droppable item:**
```rec
Id: beer
Name: Beer
OnDrop: {{ effects.drop() }}{{ effects.broadcast(user.name ~ " places " ~ name ~ " on the floor.") }}You place the {{ name }} on the floor.
```

### Item Granting via Templates

In the context of **rewarding players for interactions**, facing **the need to give items as outcomes of actions (puzzles, combat, exploration)**, we decided to **add `effects.grant()` and `effects.grant_random()` functions available in templates**, to achieve **scriptable item rewards without custom code**, accepting **that granted items bypass spawn mode restrictions**.

**`effects.grant(entity_id)`** - Grant a specific item:
- Creates new instance of entity in user's inventory
- Returns empty string (can be used inline in templates)
- Creates inventory thread via existing inventory system

**Example:**
```jinja
{{ effects.grant("rusty_key") }}The {{ name }} shatters! A *Rusty Key* clatters to the floor. You pick it up.
```

**`effects.grant_random(tag)`** - Grant a random item from a tag:
- Queues the grant; actual selection happens after template rendering
- Queries entities matching the tag, excluding `quest` rarity
- Weighted random selection using rarity weights (common=600, uncommon=250, rare=100, epic=40, legendary=9, mythic=1)
- Creates instance in user's inventory
- Broadcasts result to channel: "**{user.name}** picks up a *{item.display_name}*"
- Returns empty string (allows inline use in templates)
- If no matching entities, nothing happens (no grant, no broadcast)

**Example:**
```jinja
{{ effects.grant_random("treasure") }}The vase shatters!
```

The granted item (if any) is announced via broadcast to the room.

### Floor Clutter Limits

In the context of **preventing griefing via item spam**, facing **the risk of players flooding rooms with dropped items**, we decided to **limit player-dropped items per room to 5**, to achieve **clean room states while allowing meaningful item placement**, accepting **that world-designed items (from spawning pools or `.rec` files) are exempt**.

**Tracking:**
- `player_dropped` boolean on `entity_instances`
- Set to `TRUE` when `effects.drop()` is called
- Set to `FALSE` for spawning pool instances and initial world placement
- Only instances with `player_dropped=TRUE` count toward limit

**Behavior:**
- On drop attempt: Count `player_dropped=TRUE` instances in room
- If >= 5: "The floor is too cluttered. Pick something up first."
- Otherwise: Proceed with drop

## Recutils Authoring Format

The `.rec` format is optimized for ease of authorship. These definitions are converted to PostgreSQL during sync.

### Item Prototype

Pickupable items should use the `item` prototype, which provides sensible defaults:

```rec
Id: item
Name: item
Prototype: object
Rarity: common
OnTake: {{ effects.pickup() }}You pick up the {{ name }}.
OnDrop: {% if container %}You put the {{ name }} into the *{{ container.name }}*.{% else %}You drop the {{ name }}.{% endif %}{{ effects.drop() }}{{ effects.broadcast(user.name ~ " drops " ~ e.display_name ~ ".") }}
```

**Key benefits:**
- Items default to `common` rarity (displays ⚪ suffix, eligible for spawn pools)
- Calls `effects.pickup()` to actually pick up the item
- Standard take/drop handlers with room broadcast on drop
- Override any field as needed (e.g., `Rarity: rare` or custom `OnDrop`)

**When to use `item` vs `object`:**
- Use `item` for anything players can pick up and carry
- Use `object` for static world fixtures (furniture, decorations, interactables that stay in place)
- Items without `OnTake` calling `effects.pickup()` cannot be picked up
- Items without `OnDrop` calling `effects.drop()` cannot be dropped

### Entity Tags and Rarity

```rec
%rec: Entity
%allowed: ... Tags Rarity OnDrop

Id: beer
Name: Beer
Prototype: item
Tags: beverage alcoholic

Id: white_monster
Name: White Monster
Prototype: item
Tags: beverage energy
Rarity: uncommon

Id: white_claw
Name: White Claw
Prototype: item
Tags: beverage alcoholic
Rarity: rare

Id: mansion_map
Name: Map of the Mansion
Prototype: item
Rarity: quest
```

- `Rarity`: One of `none`, `common`, `uncommon`, `rare`, `epic`, `legendary`, `mythic`, `quest` (default from prototype)
- Quest items (`rarity=quest`) automatically clone on pickup - original stays in room

### Spawning Pools

```rec
%rec: SpawningPool
%key: Id
%mandatory: Id Room TagQuery
%allowed: Id Room Container TagQuery MaxCount RespawnIntervalMinutes

Id: fridge-beverages
Room: lounge
Container: fridge
TagQuery: beverage
MaxCount: 3
RespawnIntervalMinutes: 30
```

## PostgreSQL Schema

```sql
-- Entity rarity for weighted spawn selection (weights sum to 1000)
-- none=0 (static world items, default), common=600, uncommon=250, rare=100, epic=40,
-- legendary=9, mythic=1, quest=0 (never spawns from pools)
CREATE TYPE rarity AS ENUM ('none', 'common', 'uncommon', 'rare', 'epic', 'legendary', 'mythic', 'quest');
ALTER TABLE entities ADD COLUMN rarity rarity NOT NULL DEFAULT 'none';

-- Entity tags for categorization
CREATE TABLE entity_tags (
    entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (entity_id, tag)
);
CREATE INDEX idx_entity_tags_tag ON entity_tags(tag);

-- Spawning pools for respawning items
CREATE TABLE spawning_pools (
    id TEXT PRIMARY KEY,
    room TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    container_id TEXT REFERENCES entities(id) ON DELETE CASCADE,
    tag_query TEXT NOT NULL,
    max_count INTEGER NOT NULL DEFAULT 1,
    respawn_interval_minutes INTEGER NOT NULL DEFAULT 30
);

-- Track spawning pool origin
ALTER TABLE entity_instances ADD COLUMN spawning_pool_id TEXT REFERENCES spawning_pools(id) ON DELETE SET NULL;

-- Track player-dropped items for clutter limit
ALTER TABLE entity_instances ADD COLUMN player_dropped BOOLEAN NOT NULL DEFAULT FALSE;

-- New handler column
ALTER TABLE entities ADD COLUMN on_drop TEXT;
```

## Consequences

### Positive

- Quest items work intuitively (everyone can take once, item stays visible)
- Spawning pools create a dynamic world (beverages respawn in fridge)
- Tag system enables flexible entity categorization for content creators
- Rarity system creates interesting loot distribution
- Drop system is extensible via templates with full scripting support
- Granting enables complex interactions (puzzles, rewards, NPC gifts)
- Clutter limit prevents griefing without restricting legitimate gameplay

### Negative

- New tables: `entity_tags`, `spawning_pools`
- New columns: `rarity`, `on_drop` on entities; `spawning_pool_id`, `player_dropped` on entity_instances
- Background task required for spawning pool respawn checks
- More complex instance lifecycle (spawned vs. dropped vs. granted)
- Tag management overhead for content creators

### Future Considerations

- Item decay (dropped items disappear after configurable time)
- Conditional binding (can't drop key until door is unlocked)
- Spawning pool depletion (limited total spawns before pool exhausts)
- Complex tag queries (AND/OR logic: `beverage AND alcoholic`)
- Per-spawning-pool rarity weight overrides
- Inventory capacity limits

### Drop Autocomplete Context Detection

In the context of **dropping items from inventory**, facing **the mismatch between autocomplete (shows room items) and drop action (uses inventory items)**, we decided to **add context-aware autocomplete that detects inventory threads and supports an "i." prefix shortcut**, to achieve **seamless drop workflow from inventory threads and explicit inventory access from any channel**, accepting **additional autocomplete logic and the "i." prefix convention**.

**Inventory Thread Context:**
- When `/interact` is run from an inventory item's forum thread, autocomplete shows only that item
- Detection via `InventoryService.get_thread_item(channel)` which queries `entity_instances.discord_thread_id`
- This is the preferred workflow for dropping items

**"i." Prefix Shortcut:**
- Typing `i.` in the target field switches autocomplete to inventory search
- Example: `i.beer` shows inventory items matching "beer"
- Case-insensitive prefix detection
- Works from any room channel

**Display Format:**
- Inventory items shown with `[Inventory]` prefix: `[Inventory] Beer ⚪`
- Distinguishes from room items in mixed contexts
- Rarity emoji preserved via `display_name`

**Behavior Matrix:**

| Context | Query | Autocomplete Source |
|---------|-------|---------------------|
| Inventory thread | Any | That thread's item only |
| Room channel | `i.beer` | User's inventory filtered by "beer" |
| Room channel | `beer` | Room entities filtered by "beer" |

**No Droppability Filtering:**
- All inventory items shown, not just those with `on_drop` handler
- Items without `on_drop` return "Nothing happens." when drop attempted
- Users see full inventory context

### Container-Aware Drop Targets

In the context of **dropping items into containers**, facing **the need to support transferring items between containers**, we decided to **use the focus context to determine drop targets**, to achieve **intuitive item placement into currently-focused containers**, accepting **that players must open a container to drop items into it**.

**Behavior:**
- If user has active focus on a container (`focus_mode=container`), dropped items go into that container
- If no container focus, dropped items go to the room floor
- Items dropped into containers do not count toward floor clutter limit
- Template has access to `{{ container }}` variable for customized drop messages

**Template Context:**
- `container`: The ResolvedEntity of the focused container (or `None` if dropping to floor)
- Used in the `item` prototype's OnDrop template:
  ```jinja
  {% if container %}You put the {{ name }} into the *{{ container.name }}*.{% else %}You drop the {{ name }}.{% endif %}{{ effects.drop() }}
  ```

**Behavior Matrix:**

| Action Sequence | Drop Target |
|-----------------|-------------|
| Take from box A, close A, drop | Room floor |
| Take from box A, open box B, drop | Into box B |
| Take from floor, open box, drop | Into box |
| Take from anywhere, no container open, drop | Room floor |

**Clutter Limit:**
- Only items dropped on the floor count toward the 5-item clutter limit
- Items in containers are exempt from this limit
- Players can drop unlimited items into containers
