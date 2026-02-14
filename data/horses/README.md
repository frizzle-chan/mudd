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

## Attributes

Each horse has four stats (integers from 1–100) that determine how it performs during a race:

- **Luck** — Dominant at the start of the race. High-luck horses get an outsized early boost and often outperform their odds in practice.
- **Speed** — Dominant in the middle stretch of the race. High-speed horses pull ahead during the main straightaway but pay for it elsewhere.
- **Stamina** — Dominant in the final stretch. High-stamina horses close strong and overtake faders near the finish line.
- **Consistency** — Controls variance. A high-consistency horse finishes near its expected position reliably; a low-consistency horse is volatile and can wildly over- or under-perform.

### How stats affect odds

The betting odds formula weights the stats unevenly:

| Stat | Odds weight |
|------|-------------|
| Speed | 0.35 |
| Stamina | 0.35 |
| Luck | 0.25 |
| Consistency | 0.05 |

This creates hidden value for bettors. High-Consistency horses look weak on the odds board but finish predictably, good value for place bets. High-Luck horses routinely outperform their listed odds. High-Speed/Stamina horses are favorites but priced accordingly with no hidden edge.

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
