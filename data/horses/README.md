# Horse Data

Horse definitions for the MUDD racing minigame.

Each horse is a [GNU recutils](https://www.gnu.org/software/recutils/) record with four stats (speed, stamina, consistency, luck), optional narrative fields (description, lore), and three image assets (profile, race sprite, victory).

## Files

- `00_horse.rec` — Record descriptor (schema). Do not add horse data here.
- `<id>.rec` — One file per horse containing a single bare record.
- `<id>_profile.png` — Portrait shown on the betting board (64×64 PNG).
- `<id>_race.png` — Sprite used in race playback frames (16×16 PNG).
- `<id>_victory.png` — Image shown when the horse wins (recommended 128×128 PNG, flexible).

## Art guidelines

All horse image assets must be hand-drawn. AI-generated artwork will not be accepted.

## Adding a horse

1. Create `<id>.rec`:

    ```rec
    Id: my-horse
    Name: My Horse
    Speed: 70
    Stamina: 60
    Consistency: 50
    Luck: 40
    Description: A brief description of the horse's appearance and notable characteristics.
    + 
    Lore: Background story and narrative about the horse. This can span multiple
    + paragraphs using the continuation syntax with '+' at the start of each line.
    + Tell the horse's story, their origins, motivations, or interesting history.
    ```

2. Add the three image assets with matching `<id>` prefix.
3. Run `just horses` to validate.

## Field Reference

### Required Fields
- **Id**: Unique identifier (lowercase, alphanumeric with hyphens)
- **Name**: Display name shown to players
- **Speed**: Integer 1-100 (dominant in middle stretch)
- **Stamina**: Integer 1-100 (dominant in final stretch)
- **Consistency**: Integer 1-100 (controls variance)
- **Luck**: Integer 1-100 (dominant at start)

### Optional Fields
- **Active**: Boolean (defaults to TRUE if omitted)
- **Description**: Short description of appearance and characteristics
- **Lore**: Background story and narrative (supports multi-line with `+` continuation)

## Validation

```bash
just horses        # validate horse recfiles
cat *.rec | recsel -t Horse   # list all horses
```
