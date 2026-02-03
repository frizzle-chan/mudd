# Services

> **⚠️ DEPRECATED**: This directory is being phased out. Do not add new services here.
>
> We are migrating to an MVC + events architecture:
> - **Models** (`mudd/models/`): Domain objects with async DB access
> - **Events** (`mudd/events/`): Event types and observer protocol
> - **Observers** (`mudd/observers/`): React to events after command execution
> - **Scene** (`mudd/scene.py`): Command execution context
>
> See `mudd/cogs/look.py` and `mudd/cogs/interact.py` for example implementations.

This package contains **legacy DI service classes** that manage runtime state, caching, and database access. These are being migrated to the models/events/observers pattern.

## What makes a service
A service is a class that:
- Receives dependencies (database pool, other services) via constructor injection
- Manages state or caching
- Provides methods for data access or business logic
- Is instantiated once and passed to components that need it

## What belongs here
- EntityService - entity resolution with caching
- FocusContextService - user focus state management
- VisibilityService - user location and Discord visibility
- RenderingService - template rendering with caching

## What does NOT belong here
- Module-level functions (use mudd/database.py or dedicated modules)
- Data loading/sync functions (use loaders/)
- Pure matching functions (use matching/)
- Type definitions (use mudd/types.py)
