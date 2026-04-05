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

## VS Code Extension Integration (MCP Tools)

When the No Longer Vibe VS Code extension is installed and connected,
MCP tools are available to enhance the reading experience. Use them
conditionally — **always check if a tool is available before calling it**.
The skill must work without MCP (text-only fallback is the default).

### Tool Detection

Before using any MCP tool, check whether it exists in the current
tool set. If the `open_file` tool is not available, the extension is
not connected — skip all MCP calls and proceed in text-only mode.

### MCP-Enhanced Flow

When MCP tools **are** available, augment the reading flow:

1. **Open the file** in VS Code after displaying the briefing:
   - Call `open_file` with the file path and the first significant
     line number (e.g., first export or function definition).

2. **Highlight the current section** as the user reads:
   - Call `highlight_range` with style `"focus"` on the primary
     function or export body.
   - Call `highlight_range` with style `"context"` on import blocks
     or setup code the user has already read.

3. **Update decorations** when the user marks a file:
   - On `confirmed` / `done` / `next`: call `mark_read` with the
     file path, then call `clear_highlights` for that file.
   - On `flag <reason>`: call `mark_flagged` with the file path and
     reason, then call `clear_highlights` for that file.
   - On `skim` / `skimmed`: call `clear_highlights` for that file.

4. **Clear highlights** before moving to the next file:
   - Call `clear_highlights` (no argument) to reset all visual state
     before showing the next file briefing.

### Fallback Without MCP

When MCP tools are **not available** (extension not installed or not
connected), the skill works identically to the base flow described
above — text-only briefings, inline file reading, and progress
tracking via `progress.json`. No MCP calls are made, and no errors
are shown. The user experience is fully functional without the
extension.

### Setup

To enable the VS Code extension integration:

1. Build the extension: `cd packages/extension && npm run build`
2. Install the extension in VS Code
3. The MCP config in `.claude/mcp.json` tells Claude Code how to
   connect to the extension's MCP server (stdio transport)
4. Restart Claude Code to pick up the MCP configuration

## Edge Cases

- If all files are read, congratulate the user and show final stats.
- If `map.json` is missing, prompt the user to run `/read-index`.
