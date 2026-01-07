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
