---
name: read-index
description: Run the parser on a codebase path to generate .codebase-guide/map.json
triggers:
  - /read-index
---

# /read-index [path]

Run the parser on the given path (defaults to `.`) to generate or
regenerate `.codebase-guide/map.json`. This is the first command to run
on a new project.

## Arguments

- `path` (optional): Root directory to index. Defaults to current
  working directory.

## Behavior

1. Run the parser CLI on the target path:
   ```
   uv run no-longer-vibe index <path>
   ```
2. Wait for the parser to complete. It will:
   - Walk the file tree (respecting .gitignore)
   - Parse ASTs for supported languages
   - Build the dependency graph
   - Compute reading order (three-pass: contracts, data flow, utility)
   - Write `.codebase-guide/map.json`
3. Read the generated `map.json` and display a summary:
   ```
   Indexed <N> files across <M> layers:
     foundation: <n> files (config, constants, types)
     core: <n> files (models, services, data)
     features: <n> files (components, routes, hooks)
     integration: <n> files (api, middleware, pipeline)
     entry: <n> files (pages, app, main)
   Reading order computed. Run /read-next to start.
   ```
4. If `progress.json` already exists, preserve it (only `/read-refresh`
   should touch progress).

## Error Handling

- If the parser is not installed, tell the user to run `uv sync`.
- If the path does not exist, report the error clearly.
- If no supported source files are found, say so and suggest checking
  the path.
