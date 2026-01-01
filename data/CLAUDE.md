# Entity Data

Entity definitions in GNU recutils format. See [ADR 0001](../docs/adr/0001-static-entity-system.md) for full specification.

## Validation

```bash
just entities
```

## Schema Fields

- `Id` (required) - Unique identifier
- `Name` (required) - Display name
- `Prototype` - Parent entity for inheritance
- `Description_short` - One-line description for `/look`
- `Description_long` - Detailed description
- `On_*` - Action handlers (look, touch, attack, use, take)

Text fields support `{name}` interpolation.
