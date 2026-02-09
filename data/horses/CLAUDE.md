# Horse Data

Horse definitions for the racing minigame in GNU recutils format. See [ADR 0007](../../docs/adr/0007-horse-racing-minigame.md) for design decisions.

## Structure

```
data/horses/
├── 00_horse.rec        # Shared descriptor (schema only)
├── <id>.rec            # One recfile per horse (bare record, no %rec line)
├── <id>_profile.png    # Portrait for the betting board (64×64 PNG)
├── <id>_race.png       # Sprite for race playback frames (16×16 PNG)
└── <id>_victory.png    # Image shown on win announcement (recommended 128×128 PNG)
```

The `00_horse.rec` file defines the Horse record type and sorts first lexically. Individual horse files contain bare records — no `%rec` line — and are concatenated after the descriptor for validation.

## Validation

```bash
just horses
```

## Adding a Horse

1. Create `<id>.rec` with the required fields (see schema below)
2. Add three images: `<id>_profile.png`, `<id>_race.png`, `<id>_victory.png`
3. Run `just horses` to validate

## Schema

```rec
%rec: Horse
%key: Id
%type: Speed range 1 100
%type: Stamina range 1 100
%type: Consistency range 1 100
%type: Luck range 1 100
%type: Active bool
%mandatory: Id Name Speed Stamina Consistency Luck
%allowed: Id Name Speed Stamina Consistency Luck Active
```

### Fields

- `Id` (required) - Unique identifier, lowercase, used as filename prefix for assets
- `Name` (required) - Display name shown to players
- `Speed` (required) - 1–100. Dominant in the middle stretch
- `Stamina` (required) - 1–100. Dominant in the final stretch
- `Consistency` (required) - 1–100. Controls variance. High = reliable, low = volatile
- `Luck` (required) - 1–100. Dominant at the start
- `Active` (optional) - Boolean. Inactive horses are excluded from races. Default: true

### Example

```rec
Id: flash
Name: Flash
Speed: 90
Stamina: 70
Consistency: 75
Luck: 55
```

Stats are fixed at creation. Dynamic odds are computed at runtime from attributes and recent race performance.
