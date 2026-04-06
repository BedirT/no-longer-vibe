---
name: read-status
description: Display current reading progress across all files and layers
triggers:
  - /read-status
---

# /read-status

Print the current reading progress.

## Prerequisites

- `.codebase-guide/map.json` must exist
- The `no-longer-vibe` MCP server must be connected

## Behavior

1. Call the `get_read_status` MCP tool (no parameters).
2. If the result has `"status": "error"`, display the error message.
3. Format and display the progress report:
   ```
   Progress: <confirmed+flagged+skimmed>/<total> files (<pct>%)
     confirmed: <n>
     flagged: <n>
     skimmed: <n>
     unread: <n>

   Current layer: <current_layer> (<current_layer_pct>% complete)
   Next file: <next_file>
   Flagged files awaiting second pass: <flagged_count>

   Sessions: <sessions>
   ```

## IMPORTANT: Do NOT Read JSON Files Directly

Do NOT read `.codebase-guide/map.json` or `.codebase-guide/progress.json`
into the conversation. All data comes from the `get_read_status` MCP tool.

## Edge Cases

- If `progress.json` does not exist, tell the user to start reading
  with `/read-next`.
- If `map.json` does not exist, tell the user to run `/read-index`.
