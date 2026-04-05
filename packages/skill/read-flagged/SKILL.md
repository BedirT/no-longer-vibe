---
name: read-flagged
description: Start a second pass through files previously marked as flagged
triggers:
  - /read-flagged
---

# /read-flagged

Start a second pass through flagged files only. Shows what the user
noted when they originally flagged each file.

## Prerequisites

- `.codebase-guide/progress.json` must exist with at least one flagged
  file

## Behavior

1. Load `map.json` and `progress.json`.
2. Collect all files with status `flagged`, ordered by their position
   in the original reading order.
3. For each flagged file, display:
   ```
   -- Flagged: <filepath> -----------------------------
   Layer: <layer> | Lines: <n>
   Original note: "<the note from when it was flagged>"
   Original summary: "<the summary from first read>"
   --------------------------------------------------
   ```
4. Read the file content into the conversation.
5. The user reviews and either:
   - `confirmed` -> update status to `confirmed`, clear the flag
   - `flag <new_reason>` -> keep flagged with updated note
   - `skim` / `skimmed` -> mark as `skimmed`
   - Ask questions -> answer and wait
6. Update `progress.json` atomically after each change.
7. Continue to the next flagged file until all are resolved.

## Edge Cases

- If no files are flagged, tell the user: "No flagged files. All clear."
- If `progress.json` does not exist, tell the user to start reading
  with `/read-next`.
