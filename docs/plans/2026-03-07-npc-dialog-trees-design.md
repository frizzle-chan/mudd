# NPC Dialog Trees — Design Document

Companion to [ADR 0009](../adr/0009-npc-dialog-trees.md). This document includes concrete format examples, UX mockups, and implementation details that don't belong in the ADR.

## YAML Dialog Format

One file per dialog tree in `data/dialogs/{dialog-id}.yaml`.

```yaml
id: banker-dialog
root: greeting

nodes:
  greeting:
    text: >
      {{ "Ah, welcome back! Your loan is all squared away." if quest.completed("banker-loan")
         else "Welcome to the First National Bank of the Mansion." }}
      {{ "You're looking prosperous today." if user.balance >= 1000
         else "You look like you could use some financial advice." }}
    options:
      - label: Who are you?
        next: who_are_you
      - label: I need a loan.
        next: loan_offer
        condition: "{{ not quest.started('banker-loan') }}"
      - label: I've got your collateral.
        next: loan_collateral
        condition: "{{ quest.active('banker-loan') and user.has_item('golden-candlestick') }}"
        hidden: false
        hint: Requires golden candlestick
      - label: Tell me about the vault.
        next: vault_rumor
        condition: "{{ quest.completed('banker-loan') }}"
      - label: Goodbye.
        next: goodbye

  who_are_you:
    text: >
      I'm the head banker here. Been managing accounts since before
      the mansion got... strange.
    options:
      - label: What happened to this place?
        next: mansion_lore
      - label: Back to business.
        next: greeting

  loan_offer:
    text: >
      {{ effects.grant_currency(500) }}A loan, eh? I can offer you
      ¤500, but I'll need collateral. Bring me the golden candlestick
      from the drawing room.
    options:
      - label: Deal.
        next: loan_accepted
      - label: I'll think about it.
        next: greeting

  loan_accepted:
    text: >
      Pleasure doing business. ¤500 has been deposited. Don't
      forget — I need that candlestick.
    options:
      - label: Goodbye.
        next: goodbye

  loan_collateral:
    text: >
      {{ effects.grant_xp("speech", 200) }}Wonderful! The candlestick,
      as promised. Your debt is cleared.
    options:
      - label: What else can you tell me?
        next: greeting
      - label: Goodbye.
        next: goodbye

  vault_rumor:
    text: >
      Since you've proven trustworthy... there's a vault beneath the
      cellar. Nobody's been able to open it. But I've heard the key
      is somewhere in the attic.
    options:
      - label: Interesting...
        next: greeting
      - label: Goodbye.
        next: goodbye

  goodbye:
    text: Good day. Mind your ¤{{ user.balance }}.
    end: true
```

### Field Reference

**Top-level:**
- `id` — unique dialog identifier, referenced from entity `OnUse` via `effects.dialog("id")`
- `root` — node ID to start conversations at

**Node:**
- `text` — Jinja2 template rendered with standard context (`e`, `user`, `effects`)
- `options` — list of player choices (omit or empty for `end: true` nodes)
- `end` — if `true`, conversation ends after this node (thread deleted after short delay)

**Option:**
- `label` — button text shown to the player
- `next` — target node ID
- `condition` — Jinja2 template; option shown only when truthy (optional)
- `hidden` — if `false`, show a disabled button when condition fails (default: `true` = hide entirely)
- `hint` — text shown on the disabled button when `hidden: false` (optional)

## Entity Integration

Entity `.rec` entry references a dialog via `OnUse`:

```rec
Id: banker
Name: Banker
Prototype: npc
Room: bank
OnUse: {{ effects.dialog("banker-dialog") }}You approach the {{ e.name }}.
OnLook: {{ e.description_long or e.description_short }}
OnTouch: The {{ e.name }} adjusts his cufflinks.
OnAttack: The {{ e.name }} ducks behind the counter.
```

## Discord UX

### Thread Creation

Same pattern as shop trading threads:

1. Player runs `/interact use with banker`
2. `OnUse` template calls `effects.dialog("banker-dialog")`
3. `DialogSignal` emitted, handled by `DialogReconciler` (sub-reconciler of `DiscordReconciler`)
4. Any existing dialog/trading thread for the user is deleted
5. Private thread created in room channel
6. Root node rendered and posted with buttons

### Button Interaction

Each dialog message looks like:

```
┌──────────────────────────────────────────────┐
│ Welcome to the First National Bank of the    │
│ Mansion. You could use some financial advice. │
│                                              │
│ ┌──────────────┐ ┌────────────────┐          │
│ │ Who are you? │ │ I need a loan. │          │
│ └──────────────┘ └────────────────┘          │
│ ┌─────────┐                                  │
│ │ Goodbye │                                  │
│ └─────────┘                                  │
└──────────────────────────────────────────────┘
```

Disabled (condition failed, `hidden: false`):

```
┌─────────────────────────────────────┐
│ I've got your collateral.           │
│ (Requires golden candlestick)       │  ← greyed out
└─────────────────────────────────────┘
```

### Button custom_id

Format: `dialog:{dialog-id}:{node-id}`

Example: `dialog:banker-dialog:loan_offer`

The callback:
1. Parses dialog ID and node ID from `custom_id`
2. Validates `interaction.user.id` matches thread owner
3. Disables all buttons on the clicked message (edit)
4. Loads YAML, renders target node with Jinja2
5. Evaluates option conditions, builds button view
6. Posts new message with NPC text + buttons
7. If `end: true`, posts text with no buttons, then deletes thread after delay

### Thread Lifecycle

| Event | Behavior |
|---|---|
| `/interact use with NPC` | Delete existing thread, create new, post root |
| Button click | Disable old buttons, post next node |
| `end: true` node | Post final text, delete thread after delay |
| Player leaves room | Thread deleted via session cleanup event |
| Player starts new dialog/shop | Old thread deleted first |
| Bot restart | Orphan threads cleaned up on sync |

## Session Tracking

New `user_dialog_sessions` table:
- `user_id` — Discord user ID
- `dialog_id` — dialog tree ID
- `thread_id` — Discord thread ID
- `created_at` — timestamp

Used only for thread cleanup. No conversation state is persisted — the button `custom_id` carries all needed context.

When a user moves rooms or starts a new interaction, the session row is deleted and the thread is cleaned up (same event path as `TradingSessionEndedEvent`).

## Effects Pipeline

Dialog nodes go through the same `EffectsCollector` → `EffectsObserver` → `Scene` pipeline as entity handlers. No new effects infrastructure needed.

The `effects.dialog()` call is a new signal type (`DialogSignal`) analogous to `ShopSignal`, handled by a new `DialogReconciler` sub-reconciler.

## Quest Extensibility (Deferred)

The design accommodates a future quest system without requiring it now:

- Conditions can check any game state available in the Jinja2 context
- Currently: `user.balance`, `user.has_item()`, skill levels
- Future: `quest.started()`, `quest.active()`, `quest.completed()`
- Effects can trigger any game action via `EffectsCollector`
- Currently: `grant_currency`, `grant_xp`, `pickup`, `destroy`, etc.
- Future: `start_quest`, `complete_quest`, `set_flag`

No dialog YAML changes needed when the quest system is added — just new context variables and effect methods.
