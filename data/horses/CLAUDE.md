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

### Design Guidelines

Every horse should feel like a distinct character with clear strengths and liabilities:

- **Spike and dump**: At least one stat ≥ 75 (the identity) and at least one stat ≤ 35 (the weakness). Well-rounded generalists produce flat odds boards where every horse looks the same.
- **Stat budget**: Target ~230 total stat points (sum of all four). Genuine longshots can go as low as 195; strong favorites can go up to 250. Avoid exceeding 250 — it crowds out tradeoffs.
- **Distinct archetype**: Each horse should fill a unique competitive niche (sprinter, closer, wildcard, reliable plodder, etc.). Avoid duplicating an existing horse's spike/dump profile.

#### How stats map to odds vs race performance

The odds formula weights Speed and Stamina heavily (0.35 each), Luck moderately (0.25), and Consistency barely (0.05). This is intentional — it creates hidden value:

- A **high-Consistency** horse will have mediocre odds but finish reliably near its expected position. Good betting value for place bets.
- A **high-Luck** horse gets an outsized boost at the race start, often outperforming its odds in practice.
- A **high-Speed/Stamina** horse will be the odds-board favorite but is priced accordingly — no hidden edge.

Use `scripts/simulate_race.py --dry-run --count 100` to verify a new horse doesn't collapse the odds spread into a flat field.

### Example

```rec
Id: flash
Name: Flash
Speed: 90
Stamina: 60
Consistency: 55
Luck: 35
```

**Trailing blank line**: Each `.rec` file must end with a blank line after the last field. Without it, `cat *.rec | recfix --check` merges adjacent records and fails with "multiple key fields."

Stats are fixed at creation. Dynamic odds are computed at runtime from attributes and recent race performance.
