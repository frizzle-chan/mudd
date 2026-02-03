# Loaders

This package contains functions for loading/syncing data from source files (rec files, text files) to the database.

Loaders are **not services** - they are async functions that take a database pool as an argument and sync file data to database tables. They have side effects (database mutations, logging, file I/O).

## What belongs here
- Functions that read from data files (rec, txt, etc.)
- Functions that sync file data to database tables
- Dataclasses representing the data being loaded

## What does NOT belong here
- Runtime entity/state management (use models/)
- Query functions for runtime lookups (use models/)
