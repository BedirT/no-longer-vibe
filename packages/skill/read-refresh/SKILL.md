---
name: read-refresh
description: Re-run the parser, diff against existing map, preserve progress on unchanged files
triggers:
  - /read-refresh
---

# /read-refresh

Re-run the parser and diff against the existing `map.json`. Preserve
reading progress on unchanged files. Mark new and modified files as
unread.

## Prerequisites

- `.codebase-guide/map.json` must exist (run `/read-index` first)
- `.codebase-guide/progress.json` should exist (otherwise this is just
  `/read-index`)

## Behavior

1. Save a copy of the current `map.json` content hashes.
2. Re-run the parser to generate a fresh `map.json`:
   ```
   uv run no-longer-vibe index <path>
   ```
3. Compare old and new content hashes (SHA-256):
   - **Unchanged files**: preserve their status in `progress.json`
   - **Modified files**: reset status to `unread`
   - **New files**: add as `unread`
   - **Deleted files**: remove from `progress.json`
4. **Transitive invalidation**: for each modified file, walk its reverse
   dependencies in the dependency graph. Mark downstream files as
   "potentially stale" — they keep their status but get an annotation
   that their dependency changed. Do not try to determine if the change
   actually affects consumers; just flag them.
5. Update `progress.json` with the new `map_hash`.
6. Display a summary:
   ```
   Refreshed: <path>
     Unchanged: <n> files (progress preserved)
     Modified: <n> files (reset to unread)
     New: <n> files (added as unread)
     Deleted: <n> files (removed)
     Potentially stale: <n> files (dependency changed)

   Run /read-next to continue.
   ```

## Edge Cases

- If `map.json` does not exist, fall back to `/read-index` behavior.
- If no files changed, say so and confirm progress is intact.
