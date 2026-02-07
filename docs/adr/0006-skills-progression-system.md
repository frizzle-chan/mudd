# ADR 0006: Skills Progression System

## Status

Proposed

## Context

MUDD needs a player progression system to give long-term goals and a sense of growth. Players currently interact with the world (moving rooms, picking up items, destroying objects, chatting) but these actions don't accumulate into any visible progress.

Key requirements:
- **Progression feel**: Players should see tangible growth from repeated gameplay actions
- **Passive training**: Skills level up as a side effect of normal gameplay, not through dedicated "training" commands
- **Visibility**: Players need a persistent, always-accessible view of their skills
- **Social signaling**: Other players should be able to see a player's overall progression at a glance
- **Extensibility**: New skills can be added over time as new game systems come online

## Decisions

### RuneScape-Style Geometric XP Curve

In the context of **designing a leveling formula**, facing **the need for a curve that feels rewarding early but provides long-term depth**, we decided to **use the exact OSRS experience formula**, to achieve **a proven curve with decades of balancing behind it**, accepting **that high levels require exponentially more effort and some players may never reach the cap**.

**The Formula:**

The cumulative XP required to reach level L is:

> XP(L) = floor( sum( floor(i + 300 * 2^(i/7)) for i in 1..L-1 ) / 4 )

**Progression Properties:**
- XP required between levels increases geometrically (~10% more per level)
- Total XP approximately doubles every 7 levels
- Level 2 requires 83 XP; level 50 requires ~100K XP; level 99 requires ~13M XP
- Level 92 is the halfway point to 99 in terms of total XP
- **Level cap is 99** per skill, matching OSRS
- **XP cap is 200,000,000** per skill (XP continues to accumulate after 99 but grants no further levels)
- All skills share the same XP curve
- All skills start at level 1 with 0 XP

### Skills as Event-Driven Passive Training

In the context of **determining how players gain experience**, facing **the choice between explicit training actions and implicit progression**, we decided to **award XP passively through a skills observer and a template effect**, to achieve **progression that feels organic and rewards normal gameplay without adding new commands or interrupting flow**, accepting **that XP rates are coupled to game event frequency and will need tuning**.

**XP Source Mechanisms:**

Skills gain XP through two distinct mechanisms:

1. **Implicit (event-driven)**: The skills observer listens to existing game events and awards XP automatically. No content authoring required — the mapping is hardcoded in the observer.

2. **Explicit (template effect)**: Content authors call a `grant_xp` effect from entity handlers to award XP for a named skill. This allows items to grant arbitrary XP as part of their behavior (e.g., a food item grants Vitality XP when used, then destroys itself).

**Skill-to-Source Mapping:**

| Skill | Source | Mechanism | XP per Event | First Level-Up After |
|-------|--------|-----------|-------------|---------------------|
| Agility | Room transitions | Implicit: skills observer listens to movement events | 28 | 3 moves |
| Attack | Attacking entities | Implicit: skills observer listens to entity destroyed events triggered by the attack verb | 100 | 1 action |
| Speech | Sending messages | Implicit: Discord event handler on messages in room channels | 17 | 5 messages |
| Vitality | Eating/drinking | Explicit: food/drink handlers call `grant_xp` effect, then destroy the item | 100 | 1 action |
| Fishing | Catching fish | TBD: future fishing minigame | TBD | TBD |

XP amounts are calibrated against the level 2 threshold of 83 XP. Combat-oriented skills (Attack, Vitality) are generous — a single action earns a level-up — to give immediate feedback. Passive skills (Agility, Speech) require a handful of actions, keeping early progression fast but not instant.

**Implicit vs. Explicit Trade-offs:**

Implicit XP is simpler for content authors (it just happens) but can't distinguish context — every entity destruction via attack grants the same Attack XP. Explicit XP requires content authors to add the effect call to handlers, but allows fine-grained control: different food items could grant different amounts of Vitality XP, or a special item could grant XP to an unexpected skill.

The `grant_xp` template effect follows the same pattern as existing effects (`grant_currency`, `broadcast`, etc.) — it emits an event that the skills observer processes during flush.

**Attack vs. Consume Distinction:**

Destroying an entity via the attack verb grants Attack XP. Consuming an entity (food/drink via use) grants Vitality XP through the explicit `grant_xp` effect, and the item is destroyed via the existing `destroy` effect. These are separate paths — attack-destroy and consume-destroy don't overlap.

**Speech as Discord Event:**

Unlike other skills, Speech XP is not driven by game events from the observer pattern. Instead, a Discord event handler listens for messages sent in room channels and awards Speech XP directly. This sits outside the normal command flow since chatting is not a slash command.

### Level-Up Announcements

In the context of **communicating progression milestones**, facing **the need to celebrate level-ups without spamming or adding UI complexity**, we decided to **announce level-ups as a message in the player's current room channel**, to achieve **public celebration that nearby players can see and react to**, accepting **that players in other rooms won't see the announcement**.

**Announcement Behavior:**
- When a player's XP crosses a level threshold, a congratulatory message is posted to the room channel they're currently in
- The message includes the player's name, the skill name, and the new level
- Multiple level-ups from a single action are consolidated into one announcement
- Announcements happen after the triggering command's response is sent (during observer flush)

### Per-User Skills Channel

In the context of **providing persistent skill visibility**, facing **the same design tension as inventory display (fog-of-war vs. accessibility)**, we decided to **give each player a read-only text channel in a dedicated Skills category, following the same pattern as inventory channels**, to achieve **an always-accessible skills overview that updates in real time**, accepting **one additional channel per player and a message that must be continuously edited**.

**Channel Structure:**
- A dedicated "Skills" category, hidden from @everyone by default
- Each player gets a text channel in this category
- The bot posts a single message containing a formatted skills overview
- This message is edited whenever the player gains XP or levels up
- The player can view their channel but cannot post in it

**Skills Overview Display:**
- Shows total level prominently (sum of all individual skill levels)
- Lists each skill with its current level, XP progress toward next level, and a visual progress indicator
- Skills are grouped or ordered consistently

**Permission Model:**
- Category hidden from @everyone
- Each user gets view-only access to their own channel
- Bot has full access for message management

### Total Level

In the context of **providing an at-a-glance measure of overall progression**, facing **the need for a single number that represents a player's combined advancement**, we decided to **display a total level equal to the sum of all individual skill levels**, to achieve **a simple, comparable metric that grows with every skill trained**, accepting **that total level is influenced by the number of skills in the game (which may grow over time)**.

**Total Level Properties:**
- Sum of all individual skill levels
- Minimum total level equals the number of skills (since all start at level 1)
- Displayed prominently in the skills channel overview, in the player's Discord nickname, and through milestone roles

### Nickname Level Display

In the context of **making total level visible at a glance**, facing **the need for progression to be socially visible without requiring players to inspect each other**, we decided to **append the total level to each player's Discord nickname**, to achieve **constant passive visibility of progression in every message and member list**, accepting **that the bot must manage nicknames and auto-heal manual changes**.

**Nickname Format:**
- `displayname (LVx)` where x is the player's total level (e.g., `frizzle (LV5)`)
- If the base display name is too long for Discord's nickname limit, it is truncated to make room for the suffix
- The suffix is always present — there is no way to opt out

**Sync Behavior:**
- Nickname is set during the periodic sync alongside permission and inventory sync
- If a player manually changes their nickname, the sync repairs it on the next cycle
- When a player's total level changes (XP gain triggers a level-up), the nickname is updated immediately during observer flush, in addition to periodic sync as a safety net

### Milestone Roles

In the context of **rewarding progression milestones**, facing **the desire for cosmetic recognition that scales with the geometric XP curve**, we decided to **grant Discord roles at total level thresholds**, to achieve **visible rank progression in the member list and a sense of achievement at key milestones**, accepting **that role thresholds will need adjustment as new skills are added**.

**Role Progression:**

Roles are cumulative — players keep all roles they've earned. The highest role determines their color in the member list.

| Role | Total Level | Milestone Meaning |
|------|------------|-------------------|
| Newbie | 5 | Starting out (all skills at level 1, with 5 skills) |
| Apprentice | 15 | First real progress across a few skills |
| Adventurer | 50 | Broad exploration of multiple skills |
| Journeyman | 100 | Committed player with depth in several skills |
| Expert | 200 | Serious investment across the board |
| Veteran | 300 | Deep dedication to most skills |
| Hero | 400 | Near mastery |
| Legend | 495 | All skills maxed (5 skills x 99) |

Thresholds are calibrated for the initial 5 skills (max total level 495). As new skills are added, the "Legend" threshold increases and intermediate thresholds may be adjusted to keep the progression feeling right.

**Role Management:**
- Roles are created by the sync cog if they don't exist
- Roles are granted automatically when a player crosses a threshold
- Roles are never removed (cumulative, not replaced)
- Role color ordering ensures the highest milestone is most prominent in Discord's member list

### No Retroactive XP

In the context of **adding new skills over time**, facing **the question of whether past actions should count toward newly introduced skills**, we decided to **not grant retroactive XP**, to achieve **simplicity and a fresh start for each new skill**, accepting **that veterans who already performed relevant actions won't get credit for them**.

When a new skill is added, all players start at level 1 with 0 XP regardless of their history. This avoids the complexity of replaying event logs and keeps the experience of discovering a new skill consistent for everyone.

### Extensible Skill Registry

In the context of **an evolving game with new content**, facing **the certainty that new skills will be added over time as new game systems are built**, we decided to **treat skills as a registry that can grow without requiring schema changes**, to achieve **easy addition of new skills by defining the skill name and its triggering events**, accepting **that adding a skill changes every player's total level**.

**Adding a New Skill:**
- Define the skill identifier and display name
- Map it to one or more game events with XP amounts
- All existing players receive the new skill at level 1 with zero XP
- Total level increases by 1 for all players when a new skill is added

## Consequences

### Positive

- Progression happens naturally through gameplay — no new commands to learn
- Reuses the observer pattern already established for effects and Discord reconciliation
- Per-user skills channel follows the proven inventory forum pattern
- Geometric XP curve provides both short-term and long-term goals
- Total level gives a single comparable metric across players
- Nickname suffix makes progression passively visible in every message and member list
- Milestone roles provide tangible rewards at key thresholds and visual distinction in the member list
- New skills can be added incrementally as game systems are developed

### Negative

- One additional Discord channel per player increases resource usage
- Continuous message editing for skills overview may hit Discord rate limits under heavy play
- XP tuning requires balancing event frequency against desired leveling speed
- Adding new skills retroactively changes total level for all players and may shift milestone thresholds
- Skills observer adds processing overhead to every game event
- Bot must manage nicknames, which requires the Manage Nicknames permission and conflicts with manual nickname changes
- Nickname truncation for long display names may produce awkward results

### Future Considerations

- Leaderboards and hiscores (total level rankings, per-skill rankings)
- Skill-gated content (doors that require a minimum Agility level, etc.)
- XP multiplier events or items
- Prestige/rebirth system for players who reach max level
- **Players as virtual entities**: Players in a room will eventually be represented as inspectable entities, allowing `/look player` to display their skill levels. This is out of scope for this ADR.
- Combat system integration (Attack and Vitality affecting PvE outcomes)
- Skill-based economy (crafting skills that produce tradeable items)
- Additional milestone rewards beyond roles (cosmetic titles, skill capes, etc.)

## Open Questions

- **XP for chat**: Speech XP from chatting could be exploitable (spam messages for XP). Should there be rate limiting or minimum message length?
- **Fishing XP**: The fishing minigame doesn't exist yet; XP amount will be decided when the minigame is designed.
