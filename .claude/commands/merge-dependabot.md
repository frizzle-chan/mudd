---
allowed-tools: Bash(gh:*)
description: Rebase and merge all open Dependabot PRs
---

# Merge Dependabot PRs

Rebase and merge all open Dependabot pull requests, processing them from oldest to newest to minimize rebase conflicts.

## Context

Open Dependabot PRs: !`gh pr list --author "app/dependabot" --state open --json number,title,createdAt --jq 'sort_by(.createdAt) | .[] | "#\(.number): \(.title)"'`

## Process

For each open Dependabot PR (oldest first):

1. **Get current commit SHA** to detect when rebase completes:
   ```
   gh pr view <number> --json headRefOid --jq '.headRefOid'
   ```

2. **Comment to trigger rebase**:
   ```
   gh pr comment <number> --body "@dependabot rebase"
   ```

3. **Wait for rebase to complete** by polling until the commit SHA changes:
   ```bash
   old_sha="<original_sha>"
   while true; do
     new_sha=$(gh pr view <number> --json headRefOid --jq '.headRefOid')
     if [ "$new_sha" != "$old_sha" ]; then
       echo "Rebase complete"
       break
     fi
     sleep 10
   done
   ```

4. **Wait for CI checks to pass**:
   ```
   gh pr checks <number> --watch
   ```

5. **Merge the PR** (use --admin if branch protection requires it):
   ```
   gh pr merge <number> --squash --delete-branch --admin
   ```

6. Move to the next PR.

## Verification

After all PRs are merged, confirm no Dependabot PRs remain:
```
gh pr list --author "app/dependabot" --state open --json number
```

The result should be an empty array `[]`.
