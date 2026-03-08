# ADR 0009: NPC Dialog Trees

## Status

Accepted

## Context

MUDD's NPCs are currently static fixtures — merchants have shop interactions (ADR 0008), but all other NPCs are limited to one-shot flavor text on look, touch, and attack. There's no way for players to have multi-turn conversations with NPCs, which limits world-building, quest delivery, and character development.

Key requirements:
- **Authored dialog trees**: Content creators define branching conversations as structured data
- **Conditional branching**: Dialog options can be gated on game state (currency, inventory, skills) and future systems (quests, flags)
- **In-dialog effects**: NPCs can grant currency, items, XP, and trigger other game effects mid-conversation, reusing the existing effects pipeline
- **Familiar Discord UX**: Conversations happen in private threads (same lifecycle as shop trading), with Discord buttons for player choices
- **Stateless conversations**: No server-side tracking of which dialog node a player is on — conversations reset on completion or walk-away

## Decisions

### YAML Dialog Format

In the context of **authoring dialog trees**, facing **the need for a format that makes branching conversation structure visible to content creators**, we decided to **store dialog trees as YAML files with one file per dialog**, to achieve **a readable, reviewable authorship format where the conversation graph is apparent from the file structure**, accepting **a new file format alongside the existing recutils files**.

Dialog trees are graphs of nodes. Each file defines:
- A dialog ID and root node
- A map of named nodes, each containing NPC text and player options
- Options that link to other nodes, with optional conditions

Recutils was considered since it has precedent in the project (entities, shops, rooms). However, dialog trees are graph-structured — nodes reference other nodes, options branch and converge. In recutils, this becomes a flat list of records with ID cross-references, roughly 3x more verbose than the equivalent YAML and with the tree structure invisible. YAML's nesting preserves the conversational flow and keeps nodes, their text, and their options colocated.

Entities reference dialogs via the existing template effects pattern in their `OnUse` handler, keeping the entity definition in recutils and the conversation content in YAML.

### Jinja2 Node Text and Conditions

In the context of **making dialog dynamic**, facing **the need for NPC responses that react to game state and trigger effects**, we decided to **make node text fields Jinja2 templates with the same context as entity handlers**, to achieve **full consistency with the existing template system where dialog authors use the same tools as entity authors**, accepting **that template errors surface at runtime rather than load time**.

Node text has access to the standard template context: the entity, the user, and the effects collector. This means dialog nodes can:
- Reference player state: balance, inventory, skills
- Trigger effects inline: grant currency, grant XP, broadcast messages
- Use conditionals to vary NPC responses based on game state

Option conditions are also Jinja2 templates. When a condition evaluates to a falsy value, the option is hidden from the player by default.

### Visible Disabled Options (Author's Choice)

In the context of **gated dialog options**, facing **the tension between mystery (hidden options encourage exploration) and guidance (visible locked options give players goals)**, we decided to **hide conditional options by default, but let authors opt into showing a disabled button with a hint**, to achieve **maximum authoring flexibility where each option can be tuned for the desired player experience**, accepting **a small amount of additional per-option configuration**.

When an option has its hidden flag set to false and a hint provided, the button appears greyed out with the hint text, signaling to the player that something can be unlocked.

### Button-Based Dialog UX

In the context of **presenting dialog choices to players**, facing **the choice between emoji reactions, Discord buttons, and slash commands for option selection**, we decided to **use Discord buttons (discord.ui.View) with the full option label on each button**, to achieve **a polished interaction where players see and click their exact choice without mapping numbers to text**, accepting **introducing discord.ui.View as a new pattern in the codebase**.

Alternatives considered:
- **Emoji reactions** (1, 2, 3): Charming low-fi aesthetic, but players must map numbers to option text, and stale reactions on old messages require cleanup
- **Slash commands with autocomplete**: Consistent with existing patterns, but clunky for back-and-forth conversation

Buttons provide built-in disabled state (greyed out after clicking, no stale interaction possible), show the full option text, and are the direction Discord is pushing for interactive messages.

### Stateless Conversation Tracking

In the context of **tracking where a player is in a dialog tree**, facing **the choice between database state and encoding state in button metadata**, we decided to **encode the target node ID in each button's custom_id**, to achieve **a fully stateless dialog system that needs no database tracking of conversation progress**, accepting **that conversations always restart from the root node on a new interaction**.

Each button carries a custom_id encoding the dialog ID and target node (e.g., `dialog:banker-dialog:loan_offer`). When clicked, the callback loads the YAML file, looks up the target node, renders it, and posts the result. No database row tracks the "current node."

A session table (analogous to trading sessions) tracks only the thread ID and user, for cleanup when the player walks away or starts a new interaction.

### Thread Lifecycle (Matching Shop Pattern)

In the context of **managing the Discord thread for conversations**, facing **the existing shop thread lifecycle as a proven pattern**, we decided to **reuse the same lifecycle: create on interaction, delete on walk-away or new interaction, delete after conversation ends**, to achieve **consistent behavior that players already understand from trading**, accepting **thread creation/deletion API overhead per conversation**.

Lifecycle rules:
- Player interacts with a dialog NPC: any existing dialog/trading thread for that user is deleted, a new private thread is created, and the root node is posted with buttons
- Player clicks a button: the old message's buttons are disabled, the next node is posted with new buttons
- Player reaches an end node: the final NPC text is posted with no buttons, and the thread is deleted after a short delay
- Player leaves the room or starts a different interaction: the thread is deleted (same event path as trading session cleanup)
- Bot restart: orphan threads are cleaned up during sync

## Consequences

### Positive

- NPCs become conversational characters rather than flavor-text dispensers
- Dialog trees are human-readable and reviewable in PRs (YAML with visible structure)
- Full Jinja2 support means dialog can reference any game state and trigger any existing effect
- Button UX is polished and handles stale state automatically
- Stateless design avoids a new state-tracking table and simplifies the implementation
- Thread lifecycle is proven and consistent with shopping
- Conditional options with author-controlled visibility support both mystery and guidance
- Future quest system slots in naturally as new template context variables and effects

### Negative

- YAML is a new file format for the project (everything else uses recutils)
- discord.ui.View is a new Discord pattern (the codebase is currently slash-command-only)
- A reaction/button event listener must be registered (new event handling infrastructure)
- Template errors in dialog nodes surface at runtime, not load time
- Dialog YAML files are not validated by recutils tooling (recsel, recfix) — separate validation needed
- Thread creation per conversation adds Discord API calls

### Future Considerations

- Quest system: add a quest context object to Jinja2 templates with `started()`, `active()`, `completed()` methods for conditions and effects like `start_quest`, `complete_quest`
- NPC memory: persistent per-NPC-per-user flags for "remember what you told me" without a full quest system
- NPC schedules: entity `OnUse` template selects different dialog IDs based on time or game state
- Dialog validation tooling: a lint step that checks YAML structure, verifies node references form a connected graph, and catches Jinja2 syntax errors at load time
- Shared dialog fragments: common option sets (e.g., "Goodbye" → end) reusable across NPCs
- Speech skill integration: high Speech levels could unlock hidden dialog branches or improve NPC disposition
