---
name: read-next
description: Show the next unread file in reading order with structural context
triggers:
  - /read-next
---

# /read-next

Show the next unread file in reading order. Provide structural context,
then read the actual file content into the conversation.

## Prerequisites

- `.codebase-guide/map.json` must exist (run `/read-index` first)
- The `no-longer-vibe` MCP server must be connected (configured in
  `.claude/mcp.json`)

## Behavior

1. Call the `get_next_briefing` MCP tool (no parameters). This returns
   all context needed without loading map.json or progress.json into
   the conversation.
2. If the result has `"status": "all_read"`, congratulate the user and
   show final stats from the `progress` field.
3. If the result has `"status": "error"`, display the error message
   and suggest running `/read-index`.
4. Display the structural briefing from the tool response:
   ```
   -- Next: <path> ---------------------------------
   Layer: <layer> | Lines: <line_count> | Complexity: <complexity>

   Why now: <reason>
     <status_icon> <import.path> (<import.status>)
     ...

   Exports: <exports joined>
   Used by: <imported_by joined>
   --------------------------------------------------
   ```
   Where `<status_icon>` is: confirmed=check, flagged=warning,
   skimmed=eye-closed, unread=circle.
   Include import summaries inline when available.
5. Read the actual file content into the conversation.
6. Wait for the user's response:
   - `done` / `next` / `confirmed` -> call `complete_file` MCP tool
     with `status: "confirmed"` and a one-line summary
   - `flag <reason>` -> call `complete_file` with `status: "flagged"`,
     `note: <reason>`, and a one-line summary
   - `skim` / `skimmed` -> call `complete_file` with
     `status: "skimmed"`
   - Any other message -> treat as a question about the current file,
     answer it, then wait again
7. If the user does not provide a summary, generate a one-line summary
   when marking the file done.
8. After completing a file, immediately call `get_next_briefing` again
   and show the next file (loop).

## IMPORTANT: Do NOT Read JSON Files Directly

Do NOT read `.codebase-guide/map.json` or `.codebase-guide/progress.json`
into the conversation. These files can be very large and waste context
window tokens. All data needed for briefings comes from the
`get_next_briefing` MCP tool, and all status updates go through the
`complete_file` MCP tool.

## VS Code Extension Integration (MCP Tools)

When the No Longer Vibe VS Code extension is installed and connected,
additional visual MCP tools are available. Use them conditionally —
**always check if a tool is available before calling it**.

### MCP-Enhanced Flow

When visual MCP tools are available:

1. **Open the file** in VS Code after displaying the briefing:
   - Call `open_file` with the file path and the first significant
     line number.

2. **Highlight the current section** with importance-weighted visuals:
   - Call `highlight_range` with style `"focus"` on each function or
     export body. Include the `importance` parameter (0.0-1.0).
   - Call `highlight_range` with style `"context"` on import blocks.

3. **Clear highlights** before moving to the next file:
   - Call `clear_highlights` (no argument) to reset all visual state.

## Edge Cases

- If all files are read, congratulate the user and show final stats.
- If `map.json` is missing, prompt the user to run `/read-index`.
