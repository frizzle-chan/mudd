# ADR 0007: Horse Racing Minigame

## Status

Proposed

## Context

MUDD needs a currency sink and social event system. The economy (ADR 0005) currently has player-to-player transfers but no structured way to spend or risk currency. Horse racing serves both goals: it drains currency via a house edge and creates a shared spectator experience in Discord.

Key requirements:
- **Currency sink**: The house edge ensures net currency leaves the economy over time
- **Social event**: Races are public, shared experiences — players watch together and react in real time
- **Betting engagement**: Players risk currency on uncertain outcomes, creating stakes and excitement
- **Spectator drama**: Races should have lead changes, burst moments, and close finishes to keep viewers engaged
- **Fairness transparency**: Players need enough information to make informed bets without exposing raw internals
- **Discord-native delivery**: Races play out within Discord, working within rate limits and channel conventions

### Relationship to Existing Systems

- **Currency (ADR 0005)**: Bets and payouts flow through the double-entry ledger. The race pool is an intermediate account. House take is credited to the house account.
- **Sync cog**: Horse data, race scheduling, and Discord channel/thread management will need to integrate with the existing sync infrastructure.

## Decisions

### Horse Data Format

In the context of **authoring horse definitions**, facing **the need for a structured, validatable data format**, we decided to **use GNU recutils with a shared external descriptor**, to achieve **schema validation (range-checked stats, mandatory fields) and consistency with the existing world data pipeline**, accepting **that recutils tooling is less familiar than JSON or YAML to most contributors**.

Each horse is a separate recfile containing a single record. A shared descriptor file defines the Horse record type (field types, constraints, allowed fields). Individual horse files are plain records with no embedded schema — the descriptor sorts first lexically and is concatenated ahead of data files for validation and bulk operations.

### Horse ID Type

In the context of **database schema for horse definitions**, facing **the choice between auto-incrementing integer IDs and text IDs**, we decided to **use TEXT primary keys matching the recfile `Id` field**, to achieve **consistency with the existing zone/room/entity convention where all file-sourced tables use text PKs**, accepting **that text PKs are slightly less efficient for joins than integers**.

### Horse Image Storage

In the context of **serving horse images for betting boards and race playback**, facing **the need to access images at runtime without filesystem dependencies**, we decided to **store images as BYTEA columns directly on the horses table**, to achieve **atomic sync of horse data and images in a single upsert, with no filesystem coupling at runtime**, accepting **that large images increase row size and backup volume**.

### Racing Tables Grouping

In the context of **database schema for the racing system**, facing **the question of how to organize migrations**, we decided to **create all four tables (horses, races, race_results, bets) in a single migration**, to achieve **atomic schema creation matching the currency system pattern**, accepting **that the migration file is larger than single-table migrations**.

### Race Status Enum

In the context of **tracking race lifecycle state**, facing **the choice between plain TEXT and a PostgreSQL enum**, we decided to **use a `race_status` enum type**, to achieve **database-level validation of status transitions matching the existing `verb_action` enum pattern**, accepting **that adding new statuses requires a migration**.

### Horse Attributes

In the context of **determining race outcomes**, facing **the need to balance determinism with variety**, we decided to **use four integer attributes (speed, stamina, consistency, luck) ranging 1–100**, to achieve **a simple model where each attribute dominates a different race phase (luck at start, speed in the middle, stamina in the final stretch) and consistency controls variance**, accepting **that four attributes may not capture every desired personality trait**.

Attributes are fixed at creation and never change. What changes over time is a horse's dynamic odds, which blend attributes with recent performance history.

### Visual Assets

In the context of **horse visual identity**, facing **the need for profile images, racing sprites, and victory images**, we decided to **colocate image assets alongside recfiles in a flat directory, named by convention (`<id>_profile`, `<id>_race`, `<id>_victory`)**, to achieve **a predictable, convention-over-configuration asset pipeline where adding a horse means adding one recfile and three images**, accepting **that asset format and dimension constraints are enforced by the loader rather than the recfile schema**.

### Image Dimensions

In the context of **displaying horse profiles on the betting board**, facing **the need for a consistent, small portrait that works as an inline element in Discord embeds**, we decided to **standardize horse portraits at 64×64 pixels (PNG)**, to achieve **a pixel-art-friendly size that renders crisply at 1× and 2× and fits naturally alongside odds and form data**, accepting **that detailed artwork won't be possible at this resolution**.

In the context of **rendering race playback frames**, facing **the need for a small sprite that scales up cleanly on the race track canvas**, we decided to **standardize racing sprites at 16×16 pixels (PNG)**, to achieve **a minimal pixel-art sprite that the renderer can scale with nearest-neighbor interpolation for a retro aesthetic**, accepting **that animation detail is limited to a few pixels of change between states**.

Victory images have no strict size constraint — they are displayed standalone in the win announcement embed. For pixel art, 128×128 is the recommended size.

## Consequences

### Positive

- One file per horse keeps authoring simple and diff-friendly
- External descriptor ensures all horses validate against the same schema
- Range types catch stat errors at validation time rather than runtime
- Flat directory with naming convention makes assets discoverable without a manifest

### Negative

- Adding a horse requires creating four files (rec + three images) rather than one
- Image validation (dimensions, format, existence) must happen outside recutils

### Future Considerations

- Racing sprite may need separate surge/stumble visual states — could be composited by the renderer or require additional assets
- If the horse roster grows large, the flat directory could get noisy — subdirectories per horse would be a natural evolution

## Open Questions

- Racing sprite and victory image dimensions depend on the renderer design
- Whether the racing sprite needs separate frames or states for surge/stumble events
