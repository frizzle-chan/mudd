# World Data

World definitions in GNU recutils format. See [ADR 0001](../../docs/adr/0001-static-entity-system.md) for the full entity specification.

## Structure

Each world is a single `.rec` file containing zones, rooms, and entities:

```
data/worlds/
└── mansion.rec      # Zones + rooms + entities for the mansion world
```

## Validation

```bash
just entities
```

## File Format

A world file contains three record types: `Zone`, `Room`, and `Entity`.

### Zone Records

```rec
%rec: Zone
%key: Id
%mandatory: Id Name
%allowed: Id Name Description

Id: floor-1
Name: First Floor
Description: The ground floor of the mansion
```

- `Id` (required) - Matches Discord category name (lowercase, hyphenated)
- `Name` (required) - Display name for the zone
- `Description` (optional) - MUD flavor text for entering the zone

**Zone/Category mapping**: Zone IDs must match Discord category names exactly. The bot will create missing categories automatically.

### Room Records

```rec
%rec: Room
%key: Id
%type: Zone rec Zone
%type: HasVoice bool
%type: IsDefault bool
%mandatory: Id Name Description Zone
%allowed: Id Name Description Zone HasVoice IsDefault

Id: foyer
Name: Grand Foyer
Zone: floor-1
IsDefault: yes
Description: A grand foyer with marble floors. To your right is a #hallway.
```

- `Id` (required) - Matches Discord channel name
- `Name` (required) - Display name for the room
- `Description` (required) - Room description (synced to Discord channel topic)
- `Zone` (required) - Parent zone ID (must reference a valid Zone)
- `HasVoice` (optional) - Set to `yes` to create a paired voice channel (default: `no`)
- `IsDefault` (optional) - Set to `yes` to make this the default spawn room (exactly one room must be marked)

**Room connections**: Embed Discord channel mentions (e.g., `#hallway`) in the description. The `/move` command parses these mentions to determine valid exits.

**Channel creation**: The bot creates missing text channels and voice channels (if `HasVoice: yes`) automatically during sync.

**Default room**: Exactly one room across all world files must have `IsDefault: yes`. New players spawn here, and users in deleted rooms are relocated here.

### Entity Records

```rec
%rec: Entity
%key: Id
%type: Prototype rec Entity
%type: Container rec Entity
%type: Room rec Room
%type: ContentsVisible bool
%type: FocusMode enum none container
%type: Rarity enum none common uncommon rare epic legendary mythic quest
%mandatory: Id Name
%allowed: Id Name Prototype Container Room ContentsVisible FocusMode DescriptionShort DescriptionLong
%allowed: OnLook OnTouch OnAttack OnUse OnTake OnOpen OnClose OnDrop
%allowed: Tags Rarity

Id: foyer_table
Name: Wooden Table
Prototype: furniture
Room: foyer
DescriptionShort: a {{ name }} sits in the middle of the room
ContentsVisible: yes
```

**Schema Fields** (PascalCase):

- `Id` (required) - Unique identifier
- `Name` (required) - Display name
- `Prototype` - Parent entity for inheritance
- `Room` - Room where this entity spawns (omit for prototypes)
- `Container` - Parent entity for containment (e.g., lamp on table)
- `ContentsVisible` - Whether children auto-list (`yes` for tables, `no` for chests)
- `FocusMode` - Focus behavior on open: `none` (default), `container` (establishes focus, prioritizes contents in autocomplete)
- `Rarity` - Item rarity for loot pools: `none` (default, static items), `common`, `uncommon`, `rare`, `epic`, `legendary`, `mythic`, `quest`
- `Tags` - Space-separated tags for categorization (used by spawning pools)
- `DescriptionShort` - One-line description for `/look`
- `DescriptionLong` - Detailed description
- `On*` - Action handlers: `OnLook`, `OnTouch`, `OnAttack`, `OnUse`, `OnTake`, `OnOpen`, `OnClose`, `OnDrop`

**All text fields** (`DescriptionShort`, `DescriptionLong`, `On*`) are **Jinja2 templates** with access to:
- `e`: The resolved entity with all properties
- `name`: Entity name formatted with Discord italics (`*Name*`)
- `contents`: Bullet list of container contents (only for entities with `ContentsVisible: yes`)
- `user`: User context with `name` and `mention`
- `effects`: Side effects object for scripting (see Pickup/Drop Behavior)

**Pickup/Drop Behavior:**
- Items are picked up when `OnTake` calls `{{ effects.pickup() }}`
- Items are dropped when `OnDrop` calls `{{ effects.drop() }}`
- If the effect isn't called, only the message is shown (item doesn't move)
- Quest items (`Rarity: quest`) work like regular items; use spawning pools for respawn

### Templates

The base `object` prototype's `OnLook` template is:
```jinja
{{ e.description_long or e.description_short or "You see nothing special." }}{{ contents }}
```

This means entities inherit the behavior of showing their description when examined. Override `OnLook` for custom behavior:

```rec
Id: magic_orb
Name: Magic Orb
Prototype: object
Room: library
DescriptionShort: a glowing {{ name }}
DescriptionLong: A mysterious orb that pulses with arcane energy.
OnLook: The {{ name }} pulses softly. {{ e.description_long }}
```

### Container Contents

The `{{ contents }}` variable contains a bullet list of items inside a container. The format is `\n- item1\n- item2`. Use this to customize how containers display their contents:

```rec
{# Table - shows contents "on it" #}
Id: foyer_table
DescriptionShort: a {{ name }} sits here{% if contents %}. On it:{{ contents }}{% endif %}

{# Chest - shows contents "in it" #}
Id: treasure_chest
DescriptionShort: a {{ name }}{% if contents %}. In it:{{ contents }}{% endif %}
```

The `contents` variable uses each item's `DescriptionShort` template. For entities without `ContentsVisible: yes`, the `contents` variable is always empty.

### Template Examples

```jinja
{# Simple: just use description #}
{{ e.description_long or e.description_short }}

{# Custom text with entity reference #}
You touch the {{ name }}. It feels warm.

{# Conditional #}
{% if e.description_long %}{{ e.description_long }}{% else %}Nothing special.{% endif %}

{# Container with contents #}
A sturdy {{ name }}.{% if contents %} On it:{{ contents }}{% endif %}
```

### Template Errors

If a template has syntax errors or undefined variables, the system:
1. Falls back to `description_long` or `description_short`
2. Appends `-# (error rendering template)` to the output
3. Logs the error for debugging

## Prototypes vs Instances

- **Prototypes**: Entities without a `Room` field are templates (e.g., `object`, `furniture`)
- **Instances**: Entities with a `Room` field spawn in that room
