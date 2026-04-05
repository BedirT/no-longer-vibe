# No Longer Vibe

**Read your entire AI-generated codebase, fast, in smart order, with deterministic progress tracking.**

You vibe-coded your app. You designed the architecture, wrote the foundation, then AI grew it massively. The project works. But there's a gap between "my project" and "my code." You want to close that gap by reading everything --- not searching, not skipping --- the way you would have understood it if you'd written it manually.

**The math**: Vibe-code in 1x. Read and understand in 2x. Total 3x. Still ~7x faster than writing it yourself. This tool compresses that 2x.

Built as a Python parser + Claude Code skill + optional VS Code extension. Zero infrastructure.

---

## Features

- **Deterministic parsing** --- walks your file tree, parses ASTs, builds a dependency graph, and outputs `.codebase-guide/map.json`. Same repo = same output.
- **Three-pass reading order** --- contract surfaces first (types, interfaces), then data flow paths, then utility code. Topologically sorted so you never read a file before its dependencies.
- **Five architectural layers** --- foundation, core, features, integration, entry. Files classified by their position in the dependency graph.
- **Three-tier completion tracking** --- mark files as confirmed (understood), flagged (needs revisit), or skimmed (shallow pass). Progress persists across sessions.
- **Multi-language support** --- Python (ast module), TypeScript/JavaScript (tree-sitter), Go (tree-sitter). Plugin architecture for adding more.
- **Incremental refresh** --- re-parse after changes, preserve progress on unchanged files, transitively invalidate downstream dependencies via SHA-256 content hashes.
- **Session priming** --- compressed summaries of previously read files are fed to Claude at session start, so context carries across conversations.
- **VS Code extension** --- file status colors, caller count gutter, CodeLens annotations, highlight ranges, progress sidebar, blast radius visualization. All controlled by Claude Code via MCP.

---

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI
- Node.js 18+ (only for the VS Code extension)

### Install

```bash
git clone https://github.com/BedirT/no-longer-vibe.git
cd no-longer-vibe
./install.sh
```

That's it. The installer sets up:
- `nlv` CLI on your PATH
- Claude Code skills (`/read-index`, `/read-next`, etc.)
- VS Code extension (if VS Code is installed)

You can also install components individually:
```bash
./install.sh --parser-only     # just the CLI
./install.sh --skill-only      # just Claude Code skills
./install.sh --extension-only  # just VS Code extension
```

To uninstall everything: `./uninstall.sh`

### Start reading

```bash
nlv /path/to/your/project    # generate the codebase map
```

Open Claude Code and start reading:
```
/read-next           # get the next file with structural briefing
                     # read the code, ask Claude questions inline
done                 # mark as confirmed, move to next
flag dual token store seems unnecessary   # flag for revisit
/read-status         # check your progress
```

---

## Parser CLI

```
nlv [path] [--verbose]
```

- `path` defaults to the current directory
- `--verbose` enables debug logging
- Output goes to `.codebase-guide/map.json`

### Language Support

| Language | AST Parser | Import Resolution |
|----------|-----------|-------------------|
| Python | Built-in `ast` module | Relative/absolute import path resolution |
| TypeScript / JavaScript | tree-sitter | Module path resolution with index file detection |
| Go | tree-sitter | Package-based import resolution |

The parser uses a plugin architecture. Each language implements the `LanguagePlugin` protocol: `parse_file()` for AST extraction and `resolve_import()` for dependency resolution.

### Output: `.codebase-guide/map.json`

```json
{
  "version": "1.0.0",
  "repo_root": "/path/to/repo",
  "generated_at": "2026-04-04T10:00:00Z",
  "total_files": 387,
  "content_hashes": {
    "src/config.ts": "a3f2b8c1..."
  },
  "layers": {
    "foundation": { "description": "No or minimal internal dependencies", "files": ["..."] },
    "core":       { "description": "Depends only on foundation", "files": ["..."] },
    "features":   { "description": "Business logic, depends on core", "files": ["..."] },
    "integration":{ "description": "Composes features, middleware, API routes", "files": ["..."] },
    "entry":      { "description": "App entry points, page-level composition", "files": ["..."] }
  },
  "reading_order": [
    {
      "index": 0,
      "path": "src/config.ts",
      "layer": "foundation",
      "pass": "contracts",
      "reason": "No dependencies. Defines core configuration used by 23 files.",
      "complexity": "low",
      "line_count": 45,
      "imports": [],
      "imported_by": ["src/models/user.ts", "src/services/db.ts"],
      "exports": ["AppConfig", "getConfig", "DEFAULT_CONFIG"]
    }
  ],
  "dependency_graph": {
    "src/config.ts": {
      "imports": [],
      "imported_by": ["src/models/user.ts", "src/services/db.ts"]
    }
  }
}
```

---

## Claude Code Skill

Five slash commands that sequence files and track progress. The skill's job is to sequence and track. Claude Code handles understanding.

### `/read-index [path]`

Run the parser on the given path (defaults to `.`). Generates `.codebase-guide/map.json`.

```
Indexed 387 files across 5 layers:
  foundation: 12 files (config, constants, types)
  core: 48 files (models, services, data)
  features: 189 files (components, routes, hooks)
  integration: 97 files (api, middleware, pipeline)
  entry: 41 files (pages, app, main)
Reading order computed. Run /read-next to start.
```

### `/read-next`

Shows the next unread file with structural context --- what layer it's in, what it imports (that you've already read), what imports it (that you'll read later), exports, and callers. Then reads the file content into the conversation.

```
-- Next: src/middleware/auth.ts --------------------------
Layer: integration | Lines: 142 | Complexity: medium

Why now: All dependencies read.
  [ok] src/config.ts (confirmed)
  [ok] src/models/user.ts (confirmed)

Exports: authMiddleware, requireRole, refreshToken
Used by: src/api/routes.ts, src/app.ts (unread, later)
---------------------------------------------------------
```

Three responses after reading:

| Response | Effect |
|----------|--------|
| `done` / `confirmed` | Marks as confirmed. You understand it. |
| `flag <reason>` | Marks as flagged with your note. Needs a second pass. |
| `skim` / `skimmed` | Marks as skimmed. Shallow pass, revisit later. |

Any other message is treated as a question about the current file.

### `/read-status`

```
Progress: 214/387 files (55%)
  confirmed: 189
  flagged: 18
  skimmed: 7
  unread: 173

Current layer: features (41% complete)
Next file: src/components/Dashboard.tsx
Flagged files awaiting second pass: 18

Sessions: 6 | Avg pace: ~35 files/session
```

### `/read-flagged`

Second pass through flagged files only. Shows your original note for each file so you remember why you flagged it.

### `/read-refresh`

Re-runs the parser, diffs against the existing map. Unchanged files keep their progress. Modified files reset to unread. New files are added. Deleted files are removed. Downstream dependents of changed files are marked "potentially stale" via transitive invalidation.

```
Refreshed: /path/to/project
  Unchanged: 380 files (progress preserved)
  Modified: 3 files (reset to unread)
  New: 2 files (added as unread)
  Deleted: 1 file (removed)
  Potentially stale: 7 files (dependency changed)
```

### Session Workflow

```
You:     /read-next
Claude:  [structural briefing for src/middleware/auth.ts]
         [file content loaded into conversation]

You:     why is there a dual token store? lines 47 and 52
Claude:  [reads those lines, explains the pattern]

You:     flag - dual token store seems unnecessary
Claude:  Marked as flagged. Ready for next?

You:     next
Claude:  [briefing for next file...]
```

---

## VS Code Extension

Optional enhancement layer. The extension reads `map.json` locally for responsive UI. Claude Code sends commands via MCP tools to orchestrate the visual narrative during reading sessions.

**Principle: Decoration, not puppeteering.** The extension adds visual context to what you're already looking at. It never moves your cursor, switches your tabs, or demands your attention.

### Visual Features

**File status decorations** --- green (confirmed), orange (flagged), blue (current file), no decoration (unread) in the VS Code explorer tree.

**Caller count gutter** --- small number next to each function showing how many places call it. The single highest-value feature. "The moment I glance at a function and see 'called by: 0' and realize the AI generated dead code without me having to grep --- that's when this tool becomes non-negotiable."

**CodeLens annotations** --- "Called by: auth.ts, routes.ts | Calls: db.query, logger.info" above each function. Clickable to navigate.

**Highlight ranges** --- four styles: `focus` (subtle blue), `context` (light grey), `warning` (yellow), `blast-radius` (orange). Claude applies these during reading sessions to draw attention to relevant code.

**Progress sidebar** --- tree view organized by layer, showing files with status icons and completion percentage per layer.

**Blast radius** --- select a function, see all transitively affected files tint orange in the explorer. Claude explains the impact chain.

### MCP Tools

The extension exposes these tools via stdio MCP transport:

| Tool | Description |
|------|-------------|
| `highlight_range(file, startLine, endLine, style)` | Highlight lines with focus/context/warning/blast-radius style |
| `clear_highlights(file?)` | Clear highlights from a file (or all files) |
| `open_file(path, line?)` | Open a file, optionally at a specific line |
| `mark_read(path)` | Mark a file as read in the explorer |
| `mark_flagged(path, reason)` | Mark a file as flagged with a reason |
| `set_codelens(file, entries)` | Set CodeLens annotations on a file |
| `show_blast_radius(symbol)` | Visualize all files affected by changing a symbol |
| `clear_blast_radius()` | Clear blast radius visualization |
| `update_progress_tree()` | Refresh the progress sidebar |
| `clear_all()` | Clear all decorations and highlights |

### Install

```bash
cd packages/extension
npm install
npm run build
npx @vscode/vsce package --no-dependencies
```

Then install the `.vsix` file in VS Code: Extensions > "..." menu > "Install from VSIX..."

The extension activates automatically when it detects `.codebase-guide/map.json` in the workspace.

---

## Configuration

Place a `config.toml` or `config.json` in `.codebase-guide/` to customize reading order behavior. All options have sensible defaults.

### `.codebase-guide/config.toml`

```toml
# Skip test files entirely from reading order
skip_tests = false

# Where to place unpaired test files: "contracts", "data_flow", "utility", "separate", "skip"
test_pass = "utility"

# Tie-breaking in topological sort: "alphabetical", "file_size", "complexity"
tie_breaking = "alphabetical"

# Minimum fan_in for depth 3+ files to qualify as integration layer
integration_fan_in_threshold = 3

# Override which pass specific files or globs go into
[custom_pass_overrides]
"src/types/**" = "contracts"
"src/generated/**" = "utility"

# Override layer depth thresholds
[layer_thresholds]
foundation = 0
core = 1
features = 2
integration = 3
```

### Test File Handling Modes

| Mode | Behavior |
|------|----------|
| `utility` (default) | Unpaired test files go in Pass 3 (utility). Paired tests follow their implementation file. |
| `contracts` / `data_flow` | Place unpaired tests in the specified pass. |
| `separate` | All tests go in a separate fourth pass after all non-test files. |
| `skip` | Exclude test files from the reading order entirely. |

### Custom Pass Overrides

Force specific files or glob patterns into a particular pass, regardless of heuristic classification:

```toml
[custom_pass_overrides]
"src/types/**" = "contracts"          # all type definitions -> Pass 1
"src/generated/**" = "utility"        # generated code -> Pass 3
"src/core/registry.ts" = "contracts"  # specific file -> Pass 1
```

---

## Architecture

```
                  +-----------+
                  |  Parser   |   Python CLI (deterministic)
                  |  (nlv)    |   AST parsing, dependency graph,
                  +-----+-----+   layer classification, reading order
                        |
                        v
                  map.json + progress.json
                        |
              +---------+---------+
              |                   |
        +-----v-----+     +------v------+
        |   Skill    |     |  Extension  |
        | (Claude    |     |  (VS Code)  |
        |  Code)     +----->             |
        +------------+ MCP +-------------+
         Sequences        Display driver:
         files, tracks    file decorations,
         progress,        caller count,
         provides         CodeLens, blast
         context          radius, sidebar
```

**Parser** = source of truth. Deterministic. No LLM.

**Skill** = director. Decides what to show and when. Manages reading sessions.

**Extension** = display driver. Reads `map.json` locally. Responds to user clicks instantly. Claude sends MCP commands to orchestrate visuals.

**MCP** = control channel, not data channel. Claude sends `show_blast_radius("validateToken")`, the extension resolves it against its local copy of the graph.

### Design Constraints

- **Max 3-4 simultaneous visual channels** --- beyond this, clutter blindness kicks in (Yeh & Wickens, 2001).
- **No animated decorations.** No shimmer, no fading, no pulsing.
- **No persistent inline AI explanations.** "If every function gets a ghosted comment, I will turn it off within an hour."
- **No AI-written vs human-written markers.** "After I've reviewed and approved code, it's MY code."

---

## Project Structure

```
packages/
  parser/          Python CLI --- AST parsing, dependency graph, reading order
    src/nlv/
      cli.py         CLI entry point (nlv command)
      index.py       Pipeline orchestrator (/read-index)
      walker.py      File tree walker with .gitignore support
      plugins/       Language plugins (Python, TypeScript, Go)
      graph/         Dependency graph builder with cycle detection
      layers.py      Architectural layer classifier
      reading_order.py  Three-pass reading order computation
      config.py      Configuration loading (TOML/JSON)
      hashing.py     SHA-256 content hashing
      analysis.py    Entry point detection, complexity scoring
      output/        map.json generation
      progress.py    progress.json management
      refresh.py     Incremental refresh with transitive invalidation
      read_next.py   /read-next structural briefing logic
      read_status.py /read-status formatting
      flagged.py     /read-flagged logic
      session_priming.py  Compressed context for session starts
  skill/           Claude Code skill definitions
    install.sh       Skill installer (global or project-local)
    read-index/      /read-index skill definition
    read-next/       /read-next skill definition
    read-status/     /read-status skill definition
    read-flagged/    /read-flagged skill definition
    read-refresh/    /read-refresh skill definition
  extension/       VS Code extension (TypeScript)
    src/
      extension.ts       Activation, wiring
      mcpServer.ts       MCP stdio server with tool registrations
      mapData.ts         map.json loading and watching
      fileDecorationProvider.ts  File status colors
      callerCount.ts     Gutter decorations
      codeLensProvider.ts  Caller/callee CodeLens
      progressTree.ts    Sidebar tree view
      blastRadius.ts     Blast radius visualization
```

---

## Development

### Parser (Python)

```bash
uv sync                        # install dependencies
uv run pytest -x               # run tests (fail-fast)
uv run ruff check .            # lint
uv run pyright                 # type check
uv run pytest -x -k "test_name"  # run a single test
```

### Extension (TypeScript)

```bash
cd packages/extension
npm install
npm run build                  # esbuild bundle
npm test                       # vitest
npm run lint                   # eslint
npm run watch                  # dev mode with auto-rebuild
```

### Full Check

```bash
./scripts/run-check.sh uv run pytest -x
./scripts/run-check.sh uv run ruff check .
./scripts/run-check.sh uv run pyright
```

---

## Reading Order: The Three Passes

Based on Dr. Park's research on architect-verifying-implementation:

**Pass 1: Contract Surfaces** --- interfaces, type definitions, public APIs, module boundaries. Fast reading. You're pattern-matching against your own design intent.

**Pass 2: Data Flow Paths** --- primary execution flows end-to-end. Not file-by-file but flow-by-flow. Detects where AI's approach diverged from yours.

**Pass 3: Utility and Edge-Case Code** --- helper functions, error handlers, fallback logic. Where the AI made the most autonomous decisions.

Within each pass, files are topologically sorted so you never read a file before its dependencies. Ties are broken by layer (foundation first), then fan-in (most-imported first), then alphabetical.

Test files are co-located with their implementation: after an implementation file, its paired test files appear immediately.

---

## Design References

- [SPEC.md](SPEC.md) --- full technical specification
- [ROUNDTABLE.md](ROUNDTABLE.md) --- design rationale and research backing

## Roadmap

Tracked in [Linear](https://linear.app/bedirt/project/no-longer-vibe-26858b33c0f7).

| Phase | Scope | Status |
|-------|-------|--------|
| Phase 1: Core | Parser + Skill (BED-57 -- BED-79) | Complete |
| Phase 2: Extension Tier 1 | VS Code basics (BED-80 -- BED-86) | Complete |
| Phase 3: Iterate & Polish | CodeLens, blast radius, more languages (BED-87 -- BED-92) | Complete |

## License

Personal tool. Not a product.
