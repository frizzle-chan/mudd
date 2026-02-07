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

In the context of **designing a leveling formula**, facing **the need for a curve that feels rewarding early but provides long-term depth**, we decided to **use a RuneScape-inspired geometric experience curve where XP between levels grows by a constant factor**, to achieve **fast early levels that hook players with frequent level-ups, tapering into a long tail that rewards dedication**, accepting **that high levels require exponentially more effort and some players may never reach the cap**.

**Progression Properties:**
- XP required between levels increases geometrically (each level requires roughly 10% more XP than the previous one)
- Total XP approximately doubles every 7 levels
- Early levels are achievable in a single session; later levels represent weeks or months of play
- All skills share the same XP curve
- All skills start at level 1

### Skills as Event-Driven Passive Training

In the context of **determining how players gain experience**, facing **the choice between explicit training actions and implicit progression**, we decided to **award XP passively through an observer that listens to existing game events**, to achieve **progression that feels organic and rewards normal gameplay without adding new commands or interrupting flow**, accepting **that XP rates are coupled to game event frequency and will need tuning**.

**Skill-to-Event Mapping:**

| Skill | Trained By | Triggering Events |
|-------|-----------|-------------------|
| Vitality | Eating food | Consuming food items |
| Attack | Destroying objects | Entity destruction |
| Agility | Moving between rooms | Room transitions |
| Speech | Sending messages in rooms | Chat messages |
| Fishing | Catching fish | Fishing minigame catches |

The skills observer sits alongside the existing effects and reconciler observers. It receives the same game events and updates skill XP in the background. XP awards are fixed amounts per event (e.g., one room transition = one XP grant to Agility), with the amount configurable per skill and event type.

### Level-Up Announcements

In the context of **communicating progression milestones**, facing **the need to celebrate level-ups without spamming or adding UI complexity**, we decided to **announce level-ups as a message in the player's current room channel**, to achieve **public celebration that nearby players can see and react to**, accepting **that players in other rooms won't see the announcement**.

**Announcement Behavior:**
- When a player's XP crosses a level threshold, a congratulatory message is posted to the room channel they're currently in
- The message includes the player's name, the skill name, and the new level
- Multiple level-ups from a single action are consolidated into one announcement
- Announcements happen after the triggering command's response is sent (during observer flush)

### Per-User Skills Channel

In the context of **providing persistent skill visibility**, facing **the same design tension as inventory display (fog-of-war vs. accessibility)**, we decided to **give each player a read-only channel in a dedicated Skills category, following the same pattern as inventory forums**, to achieve **an always-accessible skills overview that updates in real time**, accepting **one additional channel per player and a message that must be continuously edited**.

**Channel Structure:**
- A dedicated "Skills" category, hidden from @everyone by default
- Each player gets a text channel in this category (not a forum — a single channel with a single overview message)
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
- Displayed prominently in the skills channel overview
- Could be incorporated into player display name or status in the future

### Extensible Skill Registry

In the context of **an evolving game with new content**, facing **the certainty that new skills will be added over time as new game systems are built**, we decided to **treat skills as a registry that can grow without requiring schema changes**, to achieve **easy addition of new skills by defining the skill name and its triggering events**, accepting **that adding a skill changes every player's total level and may require backfill logic**.

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
- New skills can be added incrementally as game systems are developed

### Negative

- One additional Discord channel per player increases resource usage
- Continuous message editing for skills overview may hit Discord rate limits under heavy play
- XP tuning requires balancing event frequency against desired leveling speed
- Adding new skills retroactively changes total level for all players
- Skills observer adds processing overhead to every game event

### Future Considerations

- Leaderboards and hiscores (total level rankings, per-skill rankings)
- Skill-gated content (doors that require a minimum Agility level, etc.)
- Skill capes or cosmetic rewards at milestone levels
- XP multiplier events or items
- Prestige/rebirth system for players who reach max level
- Skill display in player profile or as part of the `/look` command when examining another player
- Combat system integration (Attack and Vitality affecting PvE outcomes)
- Skill-based economy (crafting skills that produce tradeable items)

## Open Questions

- **XP per event**: What are the right XP amounts for each event type? This likely requires playtesting.
- **Level cap**: Should there be a maximum level, and if so, what should it be?
- **Skills channel vs. forum thread**: Should skills use a dedicated text channel per user, or could it be a pinned thread in the inventory forum to reduce channel count?
- **XP for chat**: Speech XP from chatting could be exploitable (spam messages for XP). Should there be rate limiting or minimum message length?
- **Retroactive XP**: When a new skill is added, should past actions (e.g., rooms already visited) count retroactively, or does the skill start fresh?
- **Public visibility**: Should other players be able to inspect someone's skill levels (e.g., via `/look player`), or are skills private?
