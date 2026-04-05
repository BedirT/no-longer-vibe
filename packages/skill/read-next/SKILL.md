---
name: read-next
description: Show the next unread file in reading order with structural context
triggers:
  - /read-next
---

# /read-next

Show the next unread file in reading order. Provide structural context
from `map.json`, then read the actual file content into the conversation.

## Prerequisites

- `.codebase-guide/map.json` must exist (run `/read-index` first)
- `.codebase-guide/progress.json` is created automatically on first use

## Behavior

1. Load `map.json` and `progress.json` (create `progress.json` if it
   does not exist).
2. Find the next file in `reading_order` whose status is `unread`.
3. Display the structural briefing:
   ```
   -- Next: <filepath> ---------------------------------
   Layer: <layer> | Lines: <n> | Complexity: <level>

   Why now: All dependencies read.
     <status_icon> <dep_path> (<status>)
     ...

   Exports: <export1>, <export2>, ...
   Used by: <path1>, <path2> (unread, later)
   --------------------------------------------------
   ```
4. Build session priming context: compressed summaries of previously
   read files that this file imports.
5. Read the actual file content into the conversation.
6. Wait for the user's response:
   - `done` / `next` / `confirmed` -> mark file as `confirmed`
   - `flag <reason>` -> mark file as `flagged` with the reason
   - `skim` / `skimmed` -> mark file as `skimmed`
   - Any other message -> treat as a question about the current file,
     answer it, then wait again
7. Update `progress.json` atomically after each status change.
8. When the user confirms/flags/skims, immediately show the briefing
   for the next file (loop).

## Context Window Strategy

- At session start, feed compressed context: list of previously read
  files with their one-line summaries.
- Always include structural data from `map.json` (imports, callers,
  layer) — it is small and deterministic.
- If the user does not provide a summary, generate a one-line summary
  when marking the file done.

## Edge Cases

- If all files are read, congratulate the user and show final stats.
- If `map.json` is missing, prompt the user to run `/read-index`.
