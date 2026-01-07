---
name: add-verb
description: Add synonyms to verb word lists. Use when adding verbs/synonyms for MUD actions like look, touch, attack, use, or take.
---

# Adding Verbs to Word Lists

Verb word lists map player input to entity handlers (`OnLook`, `OnTouch`, etc.).

## Adding a Verb

Run the script from the project root:

```bash
./scripts/add_verb.py --action ACTION --verb VERB
```

**Valid actions**: `on_look`, `on_touch`, `on_attack`, `on_use`, `on_take`

**Example**: `./scripts/add_verb.py --action on_attack --verb pummel`

## Rules

1. **No duplicates**: A verb can only exist in ONE file across all word lists
2. **Lowercase**: All verbs are stored lowercase
3. **Auto-sorted**: Files are automatically kept alphabetically sorted
4. **One per line**: Each verb on its own line

## Files

Word lists are in `data/verbs/`:
- `on_look.txt` - examine, inspect, look, peer, etc.
- `on_touch.txt` - feel, poke, prod, touch, etc.
- `on_attack.txt` - attack, hit, smash, strike, etc.
- `on_use.txt` - activate, operate, use, etc.
- `on_take.txt` - grab, pick, take, etc.

## Validation

Run `just verbs` to check for duplicates across all files.
