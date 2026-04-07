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
- The `no-longer-vibe` MCP server must be connected

## Behavior

1. Call the `get_flagged_files` MCP tool (no parameters).
2. If the result has `"status": "none_flagged"`, tell the user:
   "No flagged files. All clear."
3. If the result has `"status": "error"`, display the error message.
4. Display the list of flagged files with a summary count:
   "Found <n> flagged files for second pass."
5. For each flagged file, display:
   ```
   -- Flagged: <path> -----------------------------
   Layer: <layer> | Lines: <line_count>
   Original note: "<note>"
   Original summary: "<summary>"
   --------------------------------------------------
   ```
6. Read the file content into the conversation.
7. The user reviews and either:
   - `confirmed` -> call `complete_file` with `status: "confirmed"`
     and an updated summary
   - `flag <new_reason>` -> call `complete_file` with
     `status: "flagged"` and `note: <new_reason>`
   - `skim` / `skimmed` -> call `complete_file` with
     `status: "skimmed"`
   - Ask questions -> answer and wait
8. Continue to the next flagged file until all are resolved.

## IMPORTANT: Do NOT Read JSON Files Directly

Do NOT read `.codebase-guide/map.json` or `.codebase-guide/progress.json`
into the conversation. All data comes from MCP tools:
- `get_flagged_files` for the flagged file list
- `complete_file` for status updates

## VS Code Extension Integration (MCP Tools)

When visual MCP tools are available:

1. **Open the flagged file**: call `open_file` with the file path.
2. **Highlight flagged area**: call `highlight_range` with
   style `"warning"` if the note references specific lines.
3. **Clear highlights** on resolution and before the next file.

If a visual tool returns `isError: true` with "not connected", the
extension is not available. Fallback: skip visual MCP calls and
continue with text-only review. The flagged review works fully
without visual tools.

## Edge Cases

- If no files are flagged, tell the user: "No flagged files. All clear."
- If `progress.json` does not exist, tell the user to start reading
  with `/read-next`.
