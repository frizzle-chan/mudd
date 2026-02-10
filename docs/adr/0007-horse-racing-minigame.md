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

### Simulation Engine Placement

In the context of **building a race simulation for both CLI tuning and Discord playback**, facing **the choice between embedding simulation logic in a script or a cog**, we decided to **place the simulation engine in a reusable `mudd/racing/` package**, to achieve **shared logic between the CLI tuning tool and the Discord cog without duplication**, accepting **an additional package boundary to maintain**.

### Rolling-Window Counter Strategy

In the context of **maintaining per-horse performance counters for dynamic odds**, facing **the choice between incremental counter updates and full recomputation from race results**, we decided to **recompute rolling-window counters from `race_results` after each race using batch SQL with window functions**, to achieve **simplicity and guaranteed correctness regardless of race deletions or counter drift**, accepting **slightly higher query cost per update compared to incremental maintenance**.

### Simulation Determinism

In the context of **tuning race balance and writing reproducible tests**, facing **the need to control randomness in the simulation**, we decided to **accept a `Random` instance as an explicit parameter to the simulation function**, to achieve **fully reproducible race outcomes for any given seed while keeping the simulation pure and testable**, accepting **that callers must construct and pass the RNG explicitly**.

### Rubber-Banding Placement

In the context of **keeping races visually competitive**, facing **the choice of whether to apply rubber-banding before or after progress scaling**, we decided to **apply rubber-banding after the `progress_scale / num_ticks` multiplication**, to achieve **rubber-band forces that are proportional to actual position gaps rather than being diluted by the scaling step**, accepting **that the rubber-band factor needed recalibration from the original spec value**.

With the original placement (before scaling), rubber-band forces computed from positions in the 0–1 range were added to unscaled progress values in the 0.3–0.8 range, then divided by ~30. The effect was negligible. After the fix, the rubber-band force and the progress value are in the same coordinate space.

### Per-Phase Form Factors

In the context of **creating spectator drama with lead changes**, facing **the problem that per-tick gaussian noise averages out over 60 ticks via the law of large numbers**, we decided to **draw three independent additive form bonuses per horse (one per race phase) from a uniform variance distribution**, to achieve **natural lead changes when phase transitions shift which horse has the best effective speed**, accepting **an additional tuning constant (`form_variance`) and a departure from the spec's noise-only variance model**.

Key design choices:
- Form variance is **uniform across horses** (not scaled by consistency). Consistency only controls per-tick noise. This prevents volatile horses from gaining a structural advantage in multi-horse races where wide variance distributions produce more extreme positive outcomes.
- Form bonuses are **additive** to per-tick base progress, not multiplicative. This helps weaker horses more in absolute terms, giving even the weakest horse a realistic (if small) chance of winning.
- Three **independent** draws per race (start, middle, final) create the dramatic arcs the spec calls for: a horse can surge early and fade, or come from behind in the final stretch.

### Odds Formula Calibration

In the context of **setting displayed betting odds that reflect actual win probabilities**, facing **a mismatch between the spec's base strength formula and the simulation's phase-weighted physics**, we decided to **calibrate the odds formula weights to match empirical simulation outcomes**, to achieve **displayed odds that are within 2% of actual win rates, well within the 10% house edge buffer**, accepting **that the odds weights differ from the original spec values**.

The spec's original formula (`speed*0.5 + stamina*0.3 + luck*0.1 + consistency*0.1`) implied a simulation where speed dominates. The actual simulation weights luck heavily in the start phase (0.6 weight for 20% of ticks) and stamina in the final stretch (0.6 weight for 30% of ticks), producing effective weights closer to `speed*0.35 + stamina*0.35 + luck*0.25 + consistency*0.05`.

### Odds Exponentiation

In the context of **generating meaningful odds spreads between horses**, facing **the problem that linear base strengths produce compressed probability ranges where even large stat differences result in similar odds**, we decided to **raise base strengths to a configurable power (default 2.5) before computing probabilities**, to achieve **wider odds spreads that give strong horses clearly shorter odds and weak horses clearly longer odds, matching player intuition about favorites vs. longshots**, accepting **that the exponent is an additional tuning constant and that the performance modifier now operates on exponentiated values rather than raw base strengths**.

### Progress Floor

In the context of **preventing horses from visually freezing mid-race**, facing **two independent stalling sources — negative form bonuses zeroing out base progress and rubber-banding erasing the floored progress afterward**, we decided to **apply the progress floor after all modifiers (fatigue, bursts, scaling, and rubber-banding) rather than on the intermediate base+noise value**, to achieve **guaranteed forward movement every tick regardless of rubber-band forces**, accepting **that the absolute worst-case deceleration is now bounded rather than unlimited**.

The floor in position-space is `progress_floor * progress_scale / num_ticks`. With default values this produces clearly visible movement per rendered frame. A separate zero-clamp on `base + noise` prevents negative values from multiplying through fatigue and burst modifiers.

### Form Variance Reduction

In the context of **horse stats being overshadowed by random form draws**, facing **the problem that `form_variance=1.0` regularly produced form bonuses that dominated stat contributions (0.3–0.9), making horse attributes nearly meaningless**, we decided to **reduce `form_variance` from 1.0 to 0.3**, to achieve **form draws that create lead changes and drama without routinely overwhelming horse stats**, accepting **slightly less variance between phases compared to the original setting**.

With σ=0.3, a 3σ draw is ±0.9 — still significant but unable to dominate a strong horse's stats. Form differences between horses still exceed 0.3 roughly half the time, preserving frequent lead changes.

### Noise Floor

In the context of **preventing high-consistency horses from having zero variance**, facing **the problem that a consistency-100 horse would have zero noise and thus perfectly deterministic results**, we decided to **clamp the noise scale to a minimum of 0.2**, to achieve **some baseline unpredictability for all horses while preserving the relative advantage of high consistency**, accepting **that even the most consistent horse will occasionally stumble or surge**.

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

### Pre-Computed Message Queue

In the context of **delivering race events to Discord over time**, facing **the need for crash resilience and rate-limit safety**, we decided to **pre-compute all race messages and images with future timestamps, storing them in a database queue that a polling loop drains**, to achieve **full restart resilience (the poller resumes where it left off) and natural rate-limit backpressure (the 10-second poll interval stays well under Discord's rate limits)**, accepting **a small delay (up to 10 seconds) between scheduled and actual post times**.

### Thread-Based Race Delivery

In the context of **presenting a multi-message race in a Discord channel**, facing **the risk of flooding the channel with dozens of messages**, we decided to **post a single announcement message to the channel and create a thread from it for all subsequent race messages**, to achieve **a clean channel timeline where each race is a single entry that expands into a thread**, accepting **that users must open the thread to follow the race in real time**.

### Prefix Command for Race Triggering

In the context of **triggering races for development and testing**, facing **the convention that all player-facing commands use slash commands**, we decided to **use a `!horse` text command with role-based access control**, to achieve **a low-friction trigger for authorized testers that doesn't pollute the slash command namespace**, accepting **a departure from the slash-command-only convention**.

### Polling-Based Message Delivery

In the context of **posting pre-computed race messages at scheduled times**, facing **the choice between scheduler-based delivery and polling**, we decided to **use a 10-second polling loop that fetches all due messages and posts them in order**, to achieve **simplicity and natural batching of the starting sequence (messages sharing the same timestamp fire in rapid succession within one poll cycle)**, accepting **up to 10 seconds of jitter on scheduled post times**.

### Delete-After-Post Message Queue

In the context of **managing pre-computed race messages that include large image data**, facing **the risk of BYTEA image data accumulating in the database**, we decided to **delete each message row immediately after successful posting**, to achieve **bounded storage usage where only the current in-flight race's images exist in the database at any time**, accepting **that message delivery is at-most-once (a crash between posting and deletion could skip that message on restart)**.

### Animated GIF Race Progress

In the context of **showing race progress in Discord threads**, facing **the choice between static tiled images and animated content**, we decided to **group sampled race frames into short animated GIFs (3-4 frames each, ~800ms per frame) that Discord auto-plays inline**, to achieve **a natural animation of the race progressing without requiring any client-side player or embed**, accepting **larger file sizes compared to static PNGs and the limitation of GIF's 256-color palette**.

## Consequences

### Positive

- One file per horse keeps authoring simple and diff-friendly
- External descriptor ensures all horses validate against the same schema
- Range types catch stat errors at validation time rather than runtime
- Flat directory with naming convention makes assets discoverable without a manifest
- Race delivery survives bot restarts — the message queue in the database acts as a durable task queue
- Thread-based delivery keeps channels clean while allowing full race detail in threads

### Negative

- Adding a horse requires creating four files (rec + three images) rather than one
- Image validation (dimensions, format, existence) must happen outside recutils
- Pre-computing all messages upfront means the race outcome is determined before it starts (no live interaction possible)

### Future Considerations

- Racing sprite may need separate surge/stumble visual states — could be composited by the renderer or require additional assets
- If the horse roster grows large, the flat directory could get noisy — subdirectories per horse would be a natural evolution
- Betting integration will add messages to the starting sequence and payout messages after results
