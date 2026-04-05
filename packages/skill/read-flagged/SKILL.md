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

## VS Code Extension Integration (MCP Tools)

When the No Longer Vibe VS Code extension is connected, use MCP tools
to enhance the flagged-file review. **Always check if tools are
available before calling them** — the skill must work without MCP.

### MCP-Enhanced Flow

When MCP tools are available:

1. **Open the flagged file** after displaying the briefing:
   - Call `open_file` with the file path.

2. **Highlight the relevant section** if the original note references
   specific lines or functions:
   - Call `highlight_range` with style `"warning"` on the flagged area.

3. **Update decorations** on resolution:
   - On `confirmed`: call `mark_read` with the file path, then
     `clear_highlights` for that file.
   - On `flag <new_reason>`: call `mark_flagged` with the file path
     and updated reason, then `clear_highlights`.
   - On `skim` / `skimmed`: call `clear_highlights` for that file.

4. **Clear highlights** before moving to the next flagged file.

### Fallback Without MCP

When MCP tools are not available, the skill works in text-only mode.
Briefings are displayed inline, file content is read into the
conversation, and progress is tracked via `progress.json`. No errors
are shown when MCP tools are absent.

## Edge Cases

- If no files are flagged, tell the user: "No flagged files. All clear."
- If `progress.json` does not exist, tell the user to start reading
  with `/read-next`.
