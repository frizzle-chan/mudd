# Loaders

This package contains functions for loading/syncing data from source files (rec files, text files) to the database.

Loaders are **not services** - they are pure functions or functions that take a database pool as an argument. They handle batch synchronization of static game data.

## What belongs here
- Functions that read from data files (rec, txt, etc.)
- Functions that sync file data to database tables
- Dataclasses representing the data being loaded

## What does NOT belong here
- Runtime entity/state management (use services/)
- Query functions for runtime lookups (use services/)
