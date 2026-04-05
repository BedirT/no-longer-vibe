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
- `.codebase-guide/progress.json` must exist (run `/read-next` at least
  once)

## Behavior

1. Load `map.json` and `progress.json`.
2. Compute stats from `progress.json`:
   - Total files, confirmed, flagged, skimmed, unread counts
   - Current layer and its completion percentage
   - Next file in reading order
   - Number of flagged files awaiting second pass
   - Session count and average pace
3. Display the progress report:
   ```
   Progress: <confirmed+flagged+skimmed>/<total> files (<pct>%)
     confirmed: <n>
     flagged: <n>
     skimmed: <n>
     unread: <n>

   Current layer: <layer> (<pct>% complete)
   Next file: <filepath>
   Flagged files awaiting second pass: <n>

   Sessions: <n> | Avg pace: ~<n> files/session
   ```

## Implementation

Run the Python formatter via:

```bash
uv run python -c "from nlv.read_status import format_read_status; from pathlib import Path; print(format_read_status(Path('.codebase-guide')))"
```

The `format_read_status(guide_dir)` function handles all edge cases
and returns a formatted string ready to display.

## Edge Cases

- If `progress.json` does not exist, tell the user to start reading
  with `/read-next`.
- If `map.json` does not exist, tell the user to run `/read-index`.
