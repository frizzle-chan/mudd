# ADR Directory

Architecture Decision Records documenting significant design decisions for MUDD.

## ADR Format

### File Naming

```
NNNN-short-title.md
```

- 4-digit sequential number (0001, 0002, ...)
- Lowercase, hyphen-separated title

### Sections

1. **Title**: `# ADR NNNN: Title`
2. **Status**: Current state of the decision
   - `Proposed` - Under discussion
   - `Accepted` - Approved and active
   - `Deprecated` - No longer recommended
   - `Superseded by ADR NNNN` - Replaced by another ADR
3. **Context**: Problem or need being addressed
4. **Decisions**: One or more sub-decisions using Y-Statements style
5. **Consequences**: Positive, Negative, and Future Considerations
6. **Open Questions**: Unresolved items (optional, for proposed ADRs)

### Y-Statements Style

Each decision should follow this format:

> In the context of **[situation]**, facing **[problem]**, we decided to **[solution]**, to achieve **[benefit]**, accepting **[tradeoff]**.

Example:

> In the context of **runtime entity access**, facing **the need for fast lookups during gameplay**, we decided to **store entity data in PostgreSQL**, to achieve **persistent storage with reliable queries**, accepting **PostgreSQL as a runtime dependency**.

## Keeping ADRs Evergreen

ADRs document **architectural decisions** (the "what" and "why"), not implementation details (the "how"). Implementation details belong in code comments, docstrings, and separate documentation. This separation ensures ADRs remain useful as the codebase evolves.

### What to Include

- **Decisions**: The choice made and alternatives considered
- **Rationale**: Why this approach was chosen over others
- **Conceptual descriptions**: What tables/services exist and their purpose
- **Behavior rules**: How the system behaves in different scenarios
- **Design principles**: Guidelines that inform implementation choices
- **Conceptual tables**: Tables describing modes, tiers, or behavior matrices (game design, not schema)
- **Example output**: What users see (e.g., autocomplete displays, command responses)

### What to Exclude

- **SQL schemas**: Column definitions, CREATE TABLE statements, indexes
- **Code snippets**: Python classes, function signatures, dataclass definitions
- **File paths**: References to specific files like `entity_matcher.py` or `data/verbs/on_attack.txt`
- **Template syntax**: Jinja2 templates, recutils field definitions
- **Specific constants**: Magic numbers like "depth limit of 10" or "spawn weight of 600"
- **Command-line examples**: CLI invocations, script usage
- **Migration details**: How to upgrade from one version to another

### Examples

**Good** (conceptual):
> The storage layer consists of an entity definitions table and an entity instances table. Inheritance resolution happens via recursive queries.

**Bad** (implementation):
```sql
CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    prototype_id TEXT REFERENCES entities(id)
);
```

**Good** (behavior rule):
> Focus is cleared when the user interacts with an unrelated entity or changes rooms.

**Bad** (implementation):
> The `FocusContextService.clear_focus()` method is called with `reason="interaction"`.

### When Implementation Details Are Acceptable

Some implementation details may be included when they ARE the decision:

- Choosing a specific technology (PostgreSQL, Discord.py)
- Choosing a specific pattern (double-entry ledger, flyweight pattern)
- Choosing a specific algorithm approach (word-prefix matching vs. fuzzy search)

The key distinction: document the **choice** and **why**, not the **code**.
