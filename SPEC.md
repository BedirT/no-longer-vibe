# No Longer Vibe — Spec

**Codebase comprehension tool for after vibe-coding.**

Read your entire AI-generated codebase, fast, in smart order, with deterministic progress tracking. Built as a Claude Code skill + parser. Zero infrastructure.

---

## The Problem

You vibe-coded your app. You designed the architecture, wrote the foundation, then AI grew it massively. The project works. But there's a gap between "my project" and "my code." You want to close that gap by reading everything — not searching, not skipping — the way you would have understood it if you'd written it manually in 20x the time.

**The math**: Vibe-code in 1x. Read and understand in 2x. Total 3x. Still ~7x faster than writing it yourself. The tool compresses that 2x.

---

## Architecture

Two components. Zero infrastructure.

### Component 1: Parser Script (Deterministic, No LLM)

A standalone CLI (~300 lines) that:
- Walks the file tree, parses ASTs
- Resolves imports, builds a dependency graph
- Computes reading order (topological sort by dependency depth)
- Detects entry points, measures file complexity
- Outputs `.codebase-guide/map.json`

Same repo = same output. This is the source of truth for completeness.

### Component 2: Claude Code Skill (Slash Commands)

A skill that reads the parser's JSON, sequences files, tracks progress. Claude Code itself is the annotation layer — you ask questions live as you read. No batch annotation pipeline. No pre-generated summaries.

**The skill's job is to sequence and track. Claude Code handles understanding.**

### Why This Split

| Concern | Who handles it |
|---------|---------------|
| "What files exist?" | Parser (deterministic) |
| "What order to read?" | Parser (topological sort) |
| "Who calls what?" | Parser (AST + import resolution) |
| "What does this code do?" | Claude Code (live conversation) |
| "Why was this pattern chosen?" | Claude Code (live conversation) |
| "Have I read everything?" | Progress JSON (deterministic) |

Pre-computed structural data supports fast navigation. Live conversation supports actual comprehension. No batch annotations — they're expensive, go stale, and research shows they create passive learning instead of active engagement (Chi's ICAP framework, 2014; Kalyuga's redundancy effect, 2007).

---

## Slash Commands

### `/read-index [path]`

Runs the parser on the given path (defaults to `.`). Generates/regenerates `map.json`. Run once per project, re-run after major changes.

**Output**: Summary of what was found.
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

Shows the next unread file in reading order. Provides structural context from `map.json`:
- What layer this file is in and why it's next
- What it imports (that you've already read)
- What imports it (that you'll read later)
- Callers and callees

Then reads the actual file content into the conversation. You read the code, ask Claude questions inline, and when done say "done", "next", or "flag".

**Three-tier completion**:
- `confirmed` — Matches your design intent. You understand it.
- `flagged` — Needs a second pass. Something surprised you, deviated from expectations, or you want to revisit.
- `skimmed` — You read it but want deeper review later (utility code, boilerplate).

### `/read-status`

Prints current progress.
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

Starts a second pass through flagged files only. Shows what you noted when you flagged each one.

### `/read-refresh`

Re-runs the parser, diffs against the existing map, marks new/modified files as unread while preserving progress on unchanged files. Uses content hashes (SHA-256) for staleness detection.

**Transitive invalidation**: When a file changes, its reverse dependencies (files that import it) get their annotations marked "potentially stale" even if their own content hasn't changed. The dependency graph handles this — walk reverse edges from changed files, mark downstream files for re-review. Don't try to determine if the change actually affects consumers; just flag them.

---

## Reading Order

Based on Dr. Park's research on architect-verifying-implementation:

### Pass 1: Contract Surfaces
Interfaces, type definitions, public APIs, module boundaries. Fast reading — you're pattern-matching against your own design intent.

### Pass 2: Data Flow Paths
Primary execution flows end-to-end. Not file-by-file but flow-by-flow. Detects where AI's approach diverged from yours.

### Pass 3: Utility and Edge-Case Code
Helper functions, error handlers, fallback logic. Where the AI made the most autonomous decisions.

Within each pass, files are topologically sorted so you never read a file before its dependencies.

---

## JSON Schemas

### `.codebase-guide/map.json`

```json
{
  "version": "1.0.0",
  "repo_root": "/path/to/repo",
  "generated_at": "2026-04-04T10:00:00Z",
  "content_hashes": {
    "src/config.ts": "a3f2b8c1",
    "src/models/user.ts": "d4e5f6a7"
  },
  "total_files": 387,
  "layers": {
    "foundation": {
      "description": "No or minimal internal dependencies",
      "files": ["src/config.ts", "src/constants.ts", "src/types/index.ts"]
    },
    "core": {
      "description": "Depends only on foundation",
      "files": ["src/models/user.ts", "src/services/db.ts"]
    },
    "features": {
      "description": "Business logic, depends on core",
      "files": ["src/components/Dashboard.tsx"]
    },
    "integration": {
      "description": "Composes features, middleware, API routes",
      "files": ["src/api/routes.ts", "src/middleware/auth.ts"]
    },
    "entry": {
      "description": "App entry points, page-level composition",
      "files": ["src/app.ts", "src/main.ts"]
    }
  },
  "reading_order": [
    {
      "index": 0,
      "path": "src/config.ts",
      "layer": "foundation",
      "reason": "No dependencies. Defines core configuration used by 23 files.",
      "complexity": "low",
      "line_count": 45,
      "imports": [],
      "imported_by": ["src/models/user.ts", "src/services/db.ts", "..."],
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

### `.codebase-guide/progress.json`

```json
{
  "version": "1.0.0",
  "map_hash": "sha256-of-map-json",
  "started_at": "2026-04-04T10:30:00Z",
  "last_session": "2026-04-06T14:20:00Z",
  "sessions": 6,
  "files": {
    "src/config.ts": {
      "status": "confirmed",
      "read_at": "2026-04-04T10:35:00Z",
      "note": null,
      "summary": "App configuration with env-based overrides. As designed."
    },
    "src/middleware/auth.ts": {
      "status": "flagged",
      "read_at": "2026-04-05T11:20:00Z",
      "note": "JWT refresh logic seems overly complex. Why two token stores?",
      "summary": "Auth middleware with JWT verification and dual-store refresh."
    }
  },
  "stats": {
    "total": 387,
    "confirmed": 189,
    "flagged": 18,
    "skimmed": 7,
    "unread": 173
  }
}
```

---

## Context Window Strategy

After 15-20 files in one session, context fills up. The skill handles this by:

1. **Accumulated summaries**: When you mark a file done, your one-line summary (or Claude's if you don't write one) is stored in `progress.json`.
2. **Session priming**: At the start of `/read-next`, the skill feeds Claude a compressed context: "You've previously read these files: [list with one-line summaries]. The current file is X, which imports Y and Z (already read)."
3. **Map context**: Structural data from `map.json` (imports, callers, layer) is always provided — it's small and deterministic.

This means each reading session starts with orientation, even if Claude doesn't remember the previous session's conversation.

---

## Parser: Language Support

Start with the language of the target codebase. Use a plugin architecture per language:

| Language | AST Tool | Import Resolution |
|----------|----------|-------------------|
| TypeScript/JavaScript | tree-sitter or ts-morph | TypeScript Compiler API (`resolveModuleName`) |
| Python | Python `ast` module | `jedi` or regex-based |
| Go | `go/packages` | Built-in to Go tooling |

Start with one. Add others as needed.

---

## Workflow: How You Actually Read

### Setup
- VS Code open with your project
- Claude Code in the VS Code sidebar panel (or terminal alongside)

### Session Flow

```
You:     /read-next
Claude:  ── Next: src/middleware/auth.ts ──────────────────
         Layer: integration | Lines: 142 | Complexity: medium

         Why now: All dependencies read.
           ✅ src/config.ts (confirmed)
           ✅ src/models/user.ts (confirmed)

         Exports: authMiddleware, requireRole, refreshToken
         Used by: src/api/routes.ts, src/app.ts (unread, later)
         ────────────────────────────────────────────────────

         [If VS Code extension active: opens file, applies decorations]

You:     [read the code in the editor — full IDE tools available]
You:     why is there a dual token store? lines 47 and 52

Claude:  [reads those lines, explains the pattern]

You:     flag - dual token store seems unnecessary
Claude:  Marked as flagged. Ready for next?

You:     next
Claude:  [briefing for next file...]
```

### With VS Code Extension (Optional Enhancement)

The reading experience can be enhanced with a lightweight VS Code extension that Claude Code controls via MCP. The extension reads `map.json` directly for responsive UI, and Claude Code sends commands via MCP tools to orchestrate the visual narrative.

**Principle: Decoration, not puppeteering.** The extension adds visual context to what you're already looking at. It never moves your cursor, switches your tabs, or demands your attention. "If it changes what I'm looking at, it's puppeteering. If it changes how what I'm already looking at appears, it's decoration."

**Max 3-4 simultaneous visual channels** (research-backed: Yeh & Wickens, 2001 — beyond this threshold, clutter blindness kicks in and users ignore everything).

---

## VS Code Extension (Enhancement Layer)

### Architecture

```
Claude Code ──MCP tools──▶ VS Code Extension ──reads──▶ map.json
   (director)               (display driver)              (data)
```

- **Extension = display driver.** Reads `map.json` on activation, watches for changes. Handles rendering: CodeLens, decorations, sidebar tree. Responds to user clicks instantly (no round-trip through Claude).
- **Claude Code = director.** Decides what to show and when. Sends MCP commands during reading sessions. Orchestrates the narrative.
- **MCP = control channel, not data channel.** Claude sends `show_blast_radius("validateToken")`, the extension resolves it against its local copy of the graph.

### MCP Tools

```
highlight_range(file, startLine, endLine, style: "focus"|"context"|"warning"|"blast-radius")
clear_highlights(file?)
open_file(path, line?)
mark_read(path)
mark_flagged(path, reason)
set_codelens(file, entries: [{line, text, command?}])
show_blast_radius(symbol)
update_progress_tree()
clear_all()
```

Transport: stdio (local tool, no need for SSE/HTTP).

### Visual Features

#### Tier 1 — Weekend Build (~300 lines TS)

| Feature | VS Code API | What it does |
|---------|------------|--------------|
| File status in explorer | `FileDecorationProvider` | Green = read, orange = flagged, blue = current, no decoration = unread |
| Open & focus file | `window.showTextDocument` | Claude can point at specific code |
| Highlight ranges | `createTextEditorDecorationType` + `setDecorations` | Subtle background wash on function bodies, focus highlights |
| Caller count gutter | `createTextEditorDecorationType` with `gutterIconPath` | Small number showing how many places call this function — the single highest-value feature |

**Why caller count is the killer feature:** "The moment I glance at a function and see 'called by: 0' and realize the AI generated dead code without me having to grep — that's when this tool becomes non-negotiable."

#### Tier 2 — Week Build (~800-1200 lines TS)

| Feature | VS Code API | What it does |
|---------|------------|--------------|
| Caller/callee CodeLens | `CodeLensProvider` | "Called by: auth.ts, routes.ts \| Calls: db.query, logger.info" above each function. Clickable. |
| Progress sidebar | `TreeDataProvider` | Tree view: layers → files → functions, each with status icon |
| Blast radius | `FileDecorationProvider` + dependency graph | Select a function, see all affected files tint orange in explorer |

#### Tier 3 — Multi-week (Maybe Never)

| Feature | VS Code API | What it does |
|---------|------------|--------------|
| Inline data flow hints | `InlayHintProvider` | `← from config.getDB()` on variables. Noisy — needs toggle. |
| Interactive dep graph | `WebviewPanel` + D3 | Visual dependency overlay. Major UI project. |
| Live file watching | `FileSystemWatcher` | Auto-update decorations on file changes. Cache invalidation complexity. |

### What NOT to Build

Research-backed constraints (Dr. Park):
- **No animated decorations.** No shimmer, no fading, no pulsing.
- **No multi-color complexity gradients.** Speculative, high clutter risk.
- **No persistent inline AI explanations.** "If every function gets a ghosted comment saying 'this handles retry logic,' I will turn it off within an hour."
- **No permanent AI-written vs human-written markers.** "After I've reviewed and approved code, it's MY code."
- **No importance heatmaps.** No consensus definition of "importance" in research. Caller count is more actionable.

### What a Session Looks Like (With Extension)

```
You:     /read-next
Claude:  [briefing for src/auth/middleware.ts]
         MCP → open_file("src/auth/middleware.ts", 42)
         MCP → highlight_range(file, 42, 68, "focus")

[VS Code: file opens, scrolled to validateToken(). Subtle blue
 background on the function body. Gutter shows "12" (caller count).
 CodeLens reads: "Called by: router.ts, api.ts, ws.ts | Calls:
 jwt.verify, db.findUser, cache.get"]

You:     what happens if I change this function's signature?
Claude:  MCP → show_blast_radius("validateToken")

[Explorer: 12 files tint orange. Sidebar tree highlights every
 transitive dependent. Claude explains the impact chain.]

You:     flag - dual token store seems over-engineered
Claude:  MCP → mark_flagged("src/auth/middleware.ts", "dual token store")
         MCP → clear_highlights()

[Explorer: file shifts to orange. Progress bar updates. Ready
 for next file.]
```

---

## What This Is NOT

- Not a product. Personal tool.
- Not a batch annotation pipeline. Claude provides context live.
- Not a testing/linting/security tool. It's reading infrastructure.
- Not an AI quiz or comprehension verifier. You trust yourself.
- Not a replacement for good tests, types, or linting.

---

## Build Plan

### Phase 1: Core (Build in an afternoon)
1. **Parser script** — Single file, ~300 lines. AST parsing, import resolution, dependency graph, topological sort, JSON output. Target one language.
2. **Claude Code skill** — Skill definition with slash commands. Reads `map.json`, manages `progress.json`, sequences files, provides structural context to Claude.
3. **Use it** — Run parser on your actual codebase. Start reading.

### Phase 2: VS Code Extension Tier 1 (Weekend)
4. **Basic extension** — ~300 lines TS. File decorations, open_file, highlight_range, caller count gutter. MCP server via stdio.
5. **Connect to Claude Code** — Add MCP server config. Claude Code gains visual superpowers.

### Phase 3: Iterate Based on Use
6. **CodeLens** — Caller/callee annotations above functions. First Tier 2 feature you'll reach for.
7. **Sidebar progress tree** — Visual layer/file/function tree with status.
8. **Blast radius** — The showstopper. "What breaks if I change this?"
9. **Refine** — Adjust reading order heuristics, prompt tuning, `/read-refresh` for incremental updates.
