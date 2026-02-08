# 05: Deduplicate redundant database queries in SkillsReconciler

**Severity**: Major
**Files**: `mudd/observers/skills_reconciler.py`

## Problem

`SkillsReconciler` makes redundant database calls:

1. `_update_skills_channel()` calls both `UserSkill.get_all()` and `UserSkill.get_total_level()`. Total level is just `sum(s.level for s in skills)` — the second query is unnecessary.

2. `flush()` calls `_update_skills_channel()`, `_update_nickname()`, and `_update_milestone_role()` for each affected user. Both `_update_nickname()` and `_update_milestone_role()` independently call `get_total_level()`.

3. `sync_user()` calls all three methods, each independently querying the database.

Each `get_total_level()` call triggers `ensure_all_skills()` (5 queries before work item 02, 1 query after). For a single user's flush, this is 3-4 redundant total-level lookups.

## Fix

Fetch skills data once per user and pass it through:

```python
async def flush(self) -> None:
    for user_id in user_ids:
        skills = await UserSkill.get_all(self._pool, user_id)
        total = sum(s.level for s in skills)
        await self._update_skills_channel(user_id, skills, total)
        await self._update_nickname(user_id, total)
        await self._update_milestone_role(user_id, total)
```

Update method signatures to accept pre-fetched data:
- `_update_skills_channel(self, user_id, skills, total_level)`
- `_update_nickname(self, user_id, total_level)`
- `_update_milestone_role(self, user_id, total_level)`

Apply the same pattern to `sync_user()`.

Remove `UserSkill.get_total_level()` if it has no other callers after this refactor, or keep it as a convenience method that computes from `get_all()` rather than a separate query.

## Acceptance Criteria

- Each user's skills data is fetched at most once per flush/sync cycle
- `_update_skills_channel`, `_update_nickname`, `_update_milestone_role` accept pre-fetched data
- No functional behavior changes
- Existing tests pass
