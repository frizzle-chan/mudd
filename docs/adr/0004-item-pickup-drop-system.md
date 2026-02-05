# ADR 0004: Item Pickup and Drop System

## Status

Accepted

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

In the context of **controlling whether items can be picked up**, facing **the need for flexible, template-driven pickup behavior**, we decided to **use an effect function in take templates to signal pickup intent**, to achieve **full template control over pickup logic**, accepting **that all pickable items must explicitly call the pickup effect**.

**Behavior:**
- If the take template calls the pickup effect: item is picked up
- If the take template doesn't call the pickup effect: only the message is shown, item stays in room
- All items (including quest rarity) move to inventory on pickup; use spawning pools for respawn

### Entity Tags and Rarity

In the context of **categorizing entities for spawning pools**, facing **the need to group items by type and control spawn frequency**, we decided to **add a tags system and rarity enum to entities**, to achieve **flexible categorization and weighted random selection**, accepting **additional schema complexity and content authoring overhead**.

**Tags:**
- Many-to-many relationship between entities and tags
- Enable queries like "all beverages" or "all weapons"

**Rarity Tiers:**

| Emoji | Tier | Description |
|-------|------|-------------|
| (none) | None | Static world items, not spawned |
| ⚪ | Common | Most frequent spawns |
| 🟢 | Uncommon | Less frequent |
| 🔵 | Rare | Infrequent |
| 🟣 | Epic | Very infrequent |
| 🟠 | Legendary | Extremely rare |
| ㊙️ | Mythic | Rarest tier |
| 🔷 | Quest | Spawns via dedicated quest pools |

- **None**: Default for all entities. Static world items that cannot be picked up and shouldn't appear in spawning pools.
- Rarity indicates discovery difficulty only, not power level
- No zone-based weight modifiers (same odds everywhere)

**Display Names:**
- Item names are displayed with their rarity icon suffix when applicable
- Format: `{name} {rarity_icon}` (e.g., "Beer ⚪", "Rusty Key 🔷")
- Items with "none" rarity display just the name with no emoji suffix

### Spawning Pool System

In the context of **respawning items in the world**, facing **the need for items to reappear after being taken, with randomized variety**, we decided to **introduce spawning pools that query entities by tag and select randomly weighted by rarity**, to achieve **dynamic, varied item respawning without manual placement**, accepting **a background task for respawn processing and additional schema tables**.

**Spawning pool definition:**
- Unique identifier
- Room where items spawn
- Optional parent container (e.g., fridge, chest)
- Tag query to filter eligible entities
- Maximum concurrent instances from this pool
- Respawn interval

**Respawn algorithm:**
1. Background task runs periodically
2. For each spawning pool, count current instances
3. If below max count and respawn interval elapsed since last spawn:
   - Query entities matching the tag (excluding "none" rarity)
   - Perform weighted random selection using rarity weights
   - Create instance linked to spawning pool

### On-Drop Handler Pattern

In the context of **allowing players to drop items from inventory**, facing **the need to control which items can be dropped and customize drop behavior**, we decided to **add an on_drop handler field following the existing handler pattern**, to achieve **template-driven drop behavior with side effects**, accepting **that items without an on_drop handler cannot be dropped**.

**Behavior:**
- No on_drop defined: "You can't drop that."
- on_drop defined: Execute template, which must call the drop effect to perform the drop

**Template side effects:**
- Drop effect: Moves instance from inventory to current room, marks as player-dropped
- Broadcast effect: Announces the drop to the room

### Item Granting via Templates

In the context of **rewarding players for interactions**, facing **the need to give items as outcomes of actions (puzzles, combat, exploration)**, we decided to **add grant effect functions available in templates**, to achieve **scriptable item rewards without custom code**, accepting **that granted items bypass spawn mode restrictions**.

**Grant specific item:**
- Creates new instance of entity in user's inventory
- Creates inventory thread via existing inventory system

**Grant random item by tag:**
- Queries entities matching the tag, excluding "none" rarity
- Weighted random selection using rarity weights
- Creates instance in user's inventory
- Broadcasts result to channel
- If no matching entities, nothing happens

### Floor Clutter Limits

In the context of **preventing griefing via item spam**, facing **the risk of players flooding rooms with dropped items**, we decided to **limit player-dropped items per room to a fixed number**, to achieve **clean room states while allowing meaningful item placement**, accepting **that world-designed items (from spawning pools or world files) are exempt**.

**Tracking:**
- Boolean flag on instances indicates whether player-dropped
- Set to true when drop effect is called
- Set to false for spawning pool instances and initial world placement
- Only player-dropped instances count toward limit

**Behavior:**
- On drop attempt: Count player-dropped instances in room
- If at limit: "The floor is too cluttered. Pick something up first."
- Otherwise: Proceed with drop

### Drop Autocomplete Context Detection

In the context of **dropping items from inventory**, facing **the mismatch between autocomplete (shows room items) and drop action (uses inventory items)**, we decided to **add context-aware autocomplete that detects inventory threads and supports a prefix shortcut**, to achieve **seamless drop workflow from inventory threads and explicit inventory access from any channel**, accepting **additional autocomplete logic and the prefix convention**.

**Inventory Thread Context:**
- When interacting from an inventory item's forum thread, autocomplete shows only that item
- This is the preferred workflow for dropping items

**Prefix Shortcut:**
- Typing a special prefix in the target field switches autocomplete to inventory search
- Works from any room channel

**Display Format:**
- Inventory items shown with a distinct prefix to distinguish from room items
- Rarity emoji preserved

### Container-Aware Drop Targets

In the context of **dropping items into containers**, facing **the need to support transferring items between containers**, we decided to **use the focus context to determine drop targets**, to achieve **intuitive item placement into currently-focused containers**, accepting **that players must open a container to drop items into it**.

**Behavior:**
- If user has active focus on a container, dropped items go into that container
- If no container focus, dropped items go to the room floor
- Items dropped into containers do not count toward floor clutter limit
- Template has access to the container variable for customized drop messages

**Behavior Matrix:**

| Action Sequence | Drop Target |
|-----------------|-------------|
| Take from box A, close A, drop | Room floor |
| Take from box A, open box B, drop | Into box B |
| Take from floor, open box, drop | Into box |
| Take from anywhere, no container open, drop | Room floor |

**Clutter Limit:**
- Only items dropped on the floor count toward the clutter limit
- Items in containers are exempt
- Players can drop unlimited items into containers

### Recursive Container Pickup and Drop

In the context of **picking up and dropping containers with contents**, facing **the need for intuitive behavior where container contents move with the container**, we decided to **recursively move all container contents when the container is picked up or dropped**, to achieve **natural container behavior without manual item-by-item transfers**, accepting **additional database queries during pickup/drop operations**.

**Pickup Behavior:**
- When picking up a container, all items inside move to the player's inventory
- Contents retain their logical container relationship
- Contents are accessible via the container's inventory thread

**Drop Behavior:**
- When dropping a container, all contents move to the room with it
- Contents retain their container relationship
- Contents appear inside the container in the room

### Entity Resolution Unification

In the context of **entity resolution for autocomplete and command execution**, facing **scattered resolution logic across multiple cogs with separate context detection mechanisms**, we decided to **create a unified entity resolution service with source-prefixed autocomplete values**, to achieve **consistent, unambiguous entity resolution across all interaction contexts**, accepting **a new encoding scheme for autocomplete values**.

**Unified Service:**
The entity resolution service consolidates entity visibility, focus context, and autocomplete logic into a unified API with three key operations:
- Build context: Determines the current interaction context (room, inventory, focused container)
- Get autocomplete choices: Returns appropriate choices based on context
- Resolve target: Resolves an encoded autocomplete value to the actual entity

**Source-Prefixed Autocomplete Values:**
Autocomplete choices use source-prefixed values for unambiguous resolution:
- Room entities
- Inventory items
- Container contents (items inside focused container)
- Escape option (close focus, show room)

**Resolution Strategy:**
1. Parse source prefix to scope the search
2. Try exact name match within that scope
3. Fallback to prefix matching if exact fails (handles user edits)

**Implicit Focus in Container Threads:**
When a player is in an inventory thread for a container with focus mode enabled, the system implicitly focuses on that container's contents without requiring an explicit "open" action.

## Consequences

### Positive

- Quest items work intuitively (everyone can take once, item stays visible)
- Spawning pools create a dynamic world (beverages respawn in fridge)
- Tag system enables flexible entity categorization for content creators
- Rarity system creates interesting loot distribution
- Drop system is extensible via templates with full scripting support
- Granting enables complex interactions (puzzles, rewards, NPC gifts)
- Clutter limit prevents griefing without restricting legitimate gameplay
- Unified entity resolution provides consistent behavior across all contexts

### Negative

- New tables required for tags and spawning pools
- New fields required on entities and instances
- Background task required for spawning pool respawn checks
- More complex instance lifecycle (spawned vs. dropped vs. granted)
- Tag management overhead for content creators

### Future Considerations

- Item decay (dropped items disappear after configurable time)
- Conditional binding (can't drop key until door is unlocked)
- Spawning pool depletion (limited total spawns before pool exhausts)
- Complex tag queries (AND/OR logic)
- Per-spawning-pool rarity weight overrides
- Inventory capacity limits
