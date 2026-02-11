# Horse Data

Horse definitions for the MUDD racing minigame.

Each horse is a [GNU recutils](https://www.gnu.org/software/recutils/) record with four stats (speed, stamina, consistency, luck) and three image assets (profile, race sprite, victory).

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
    ```

2. Add the three image assets with matching `<id>` prefix.
3. Run `just horses` to validate.

## Validation

```bash
just horses        # validate horse recfiles
cat *.rec | recsel -t Horse   # list all horses
```
