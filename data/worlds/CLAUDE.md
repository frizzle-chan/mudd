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
%mandatory: Id Name Description Zone
%allowed: Id Name Description Zone HasVoice

Id: foyer
Name: Grand Foyer
Zone: floor-1
HasVoice: yes
Description: A grand foyer with marble floors. To your right is a #hallway.
```

- `Id` (required) - Matches Discord channel name
- `Name` (required) - Display name for the room
- `Description` (required) - Room description (synced to Discord channel topic)
- `Zone` (required) - Parent zone ID (must reference a valid Zone)
- `HasVoice` (optional) - Set to `yes` to create a paired voice channel (default: `no`)

**Room connections**: Embed Discord channel mentions (e.g., `#hallway`) in the description. Discord renders these as clickable links, providing implicit navigation.

**Channel creation**: The bot creates missing text channels and voice channels (if `HasVoice: yes`) automatically on startup.

### Entity Records

```rec
%rec: Entity
%key: Id
%type: Prototype rec Entity
%type: Container rec Entity
%type: Room rec Room
%type: ContentsVisible bool
%type: SpawnMode enum none move clone
%mandatory: Id Name
%allowed: Id Name Prototype Container Room ContentsVisible SpawnMode DescriptionShort DescriptionLong
%allowed: OnLook OnTouch OnAttack OnUse OnTake

Id: foyer_table
Name: Wooden Table
Prototype: furniture
Room: foyer
DescriptionShort: a {name} sits in the middle of the room
ContentsVisible: yes
```

**Schema Fields** (PascalCase):

- `Id` (required) - Unique identifier
- `Name` (required) - Display name
- `Prototype` - Parent entity for inheritance
- `Room` - Room where this entity spawns (omit for prototypes)
- `Container` - Parent entity for containment (e.g., lamp on table)
- `ContentsVisible` - Whether children auto-list (`yes` for tables, `no` for chests)
- `SpawnMode` - Take behavior: `none` (default), `move` (one-time pickup), `clone` (infinite copies)
- `DescriptionShort` - One-line description for `/look`
- `DescriptionLong` - Detailed description
- `On*` - Action handlers: `OnLook`, `OnTouch`, `OnAttack`, `OnUse`, `OnTake`

Text fields support `{name}` interpolation.

## Prototypes vs Instances

- **Prototypes**: Entities without a `Room` field are templates (e.g., `object`, `furniture`)
- **Instances**: Entities with a `Room` field spawn in that room
