# Entity Data

Entity definitions in GNU recutils format. See [ADR 0001](../docs/adr/0001-static-entity-system.md) for full specification.

## Validation

```bash
just entities
```

## Schema Fields

Field names use PascalCase (e.g., `DescriptionShort`, not `Description_short`).

- `Id` (required) - Unique identifier
- `Name` (required) - Display name
- `Prototype` - Parent entity for inheritance
- `Container` - Parent entity for containment (e.g., lamp on table)
- `ContentsVisible` - Whether children auto-list (`yes` for tables, `no` for chests)
- `SpawnMode` - Take behavior: `none` (can't take, default), `move` (one-time pickup), `clone` (infinite copies)
- `DescriptionShort` - One-line description for `/look`
- `DescriptionLong` - Detailed description
- `On*` - Action handlers: `OnLook`, `OnTouch`, `OnAttack`, `OnUse`, `OnTake`

Text fields support `{name}` interpolation.
