# Matching

This package contains functions for fuzzy matching user input to game entities and verbs.

These are **not services** - they are pure functions that implement matching algorithms. They may take protocols/interfaces as arguments for dependency injection but don't maintain state.

## What belongs here
- Entity matching functions (prefix matching, autocomplete)
- Verb matching functions
- Match result dataclasses

## What does NOT belong here
- Database access logic (use services/)
- State management (use services/)
