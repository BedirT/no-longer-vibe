---
name: read-overview
description: Show a high-level orientation of the project before diving into file-by-file reading
triggers:
  - /read-overview
---

# /read-overview

Show a high-level project orientation — folder structure, tech stack,
architecture, and patterns — so the reader has a mental map before
diving into individual files with `/read-next`.

## Prerequisites

- `.codebase-guide/map.json` must exist (run `/read-index` first)

## Behavior

1. Load `.codebase-guide/map.json`.
2. Gather and present the following sections in order:

### Section 1: Project Structure

Show a high-level folder tree (max 3 levels deep, collapse
`node_modules`, `__pycache__`, `.git`, `dist`, `build`, and similar).
Use `tree` or a manual walk. Group by purpose, not alphabetically.

### Section 2: Tech Stack

Detect from project files:
- **Language(s)**: infer from file extensions in `map.json`
- **Package manager**: `package.json` (npm/yarn/pnpm), `pyproject.toml`
  (uv/pip), `go.mod`, `Cargo.toml`, etc.
- **Frameworks**: scan top-level config and dependency files
- **Key dependencies**: list the 5-10 most important (not devDeps/test
  deps) — the ones that define what this project *does*

### Section 3: Architecture Layers

From `map.json` layers, show:
```
Layer breakdown:
  foundation:  <n> files — <description from map.json>
  core:        <n> files — <description>
  features:    <n> files — <description>
  integration: <n> files — <description>
  entry:       <n> files — <description>

Total: <N> files in reading order
```

### Section 4: Entry Points

List the entry point files (from the `entry` layer) with a one-line
description of each. These are where execution starts — the reader
should know they exist even though they are read last.

### Section 5: Key Contracts

List the top 5-10 most-imported files from the dependency graph (the
files with the longest `imported_by` lists). These are the backbone
of the codebase — the interfaces and types everything else depends on.
Show each with its export list and import count.

### Section 6: Patterns Detected

Scan the reading order and dependency graph for recognizable patterns:
- Domain-driven design (domain/, entities/, value_objects/)
- MVC / MVVM / component-based architecture
- Plugin/registry patterns
- Layered architecture (the layers themselves)
- Monorepo structure (packages/, apps/, libs/)
- Any other structural patterns visible from the file tree

Keep this factual — report what you see, do not speculate.

## Output Format

Present each section with a clear heading. Keep the total output
concise — this is orientation, not documentation. The reader should
finish this in under 2 minutes.

End with:
```
Overview complete. Run /read-next to begin file-by-file reading.
```

## VS Code Extension Integration (MCP Tools)

When MCP tools are available, call `update_progress_tree()` after
displaying the overview so the sidebar reflects the current state.

No file opening or highlighting — this is a summary view.

## Edge Cases

- If `map.json` is missing, prompt the user to run `/read-index`.
- If `progress.json` exists and shows prior progress, mention it:
  "Resuming: <n>/<total> files already read (<percent>%)."
- Can be re-run anytime — it always shows current state.
