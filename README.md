<p align="center">
  <img src="docs/assets/nlv-logo.png" alt="No Longer Vibe" width="120" />
</p>

<h1 align="center">No Longer Vibe</h1>

<p align="center">
  <strong>Systematically read and understand your entire AI-generated codebase.</strong>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> &bull;
  <a href="#how-it-works">How It Works</a> &bull;
  <a href="#the-reading-experience">Reading Experience</a> &bull;
  <a href="#vs-code-extension">VS Code Extension</a> &bull;
  <a href="SPEC.md">Full Spec</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue?logo=python&logoColor=white" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/languages-Python%20%7C%20TypeScript%20%7C%20Go-green" alt="Languages" />
  <img src="https://img.shields.io/badge/Claude%20Code-skill-blueviolet?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0id2hpdGUiPjxwYXRoIGQ9Ik0xMiAyQzYuNDggMiAyIDYuNDggMiAxMnM0LjQ4IDEwIDEwIDEwIDEwLTQuNDggMTAtMTBTMTcuNTIgMiAxMiAyem0wIDE4Yy00LjQxIDAtOC0zLjU5LTgtOHMzLjU5LTggOC04IDggMy41OSA4IDgtMy41OSA4LTggNHoiLz48L3N2Zz4=" alt="Claude Code Skill" />
  <img src="https://img.shields.io/badge/VS%20Code-extension-007ACC?logo=visual-studio-code&logoColor=white" alt="VS Code Extension" />
  <img src="https://img.shields.io/badge/license-personal-lightgrey" alt="License" />
</p>

---

<p align="center">
  <a href="https://youtu.be/DEMO_VIDEO_ID">
    <img src="docs/assets/demo-thumbnail.png" alt="Demo Video" width="720" />
  </a>
  <br />
  <em>Watch: Reading a 400-file codebase in smart order with live AI context (2 min)</em>
</p>

---

## The Problem

You vibe-coded your app. You designed the architecture, wrote the foundation, then AI grew it massively. The project works. Ship it? Sure. But there's a gap between **"my project"** and **"my code."**

You don't want to search for things. You don't want summaries. You want to **read everything** --- the way you would have understood it if you'd written it yourself.

**The math:** Vibe-code in 1x. Read and understand in 2x. Total 3x. Still ~7x faster than writing it manually. **No Longer Vibe compresses that 2x.**

---

## How It Works

Three components. Zero infrastructure. No LLM needed for the analysis.

```
  ┌──────────────────┐
  │    nlv CLI        │  ← Deterministic Python parser
  │  AST → Graph →   │    Same repo = same output, every time
  │  → Reading Order  │
  └────────┬─────────┘
           │
     map.json + progress.json
           │
     ┌─────┴──────────────────────┐
     │                            │
  ┌──▼──────────────┐   ┌────────▼────────────┐
  │  Claude Code     │   │  VS Code Extension   │
  │  Skills          │──▶│  (optional)           │
  │                  │MCP│                       │
  │  Sequences files,│   │  File decorations,    │
  │  tracks progress,│   │  caller counts,       │
  │  provides context│   │  blast radius,        │
  └──────────────────┘   │  progress sidebar     │
                         └───────────────────────┘
```

| Step | What happens |
|------|-------------|
| **1. Parse** | `nlv /path/to/project` walks your file tree, parses ASTs, builds a dependency graph, and outputs `.codebase-guide/map.json`. Deterministic --- no LLM, no API calls. |
| **2. Read** | `/read-next` in Claude Code gives you the next file in smart order with full structural context. You read the code, ask Claude questions inline, mark it done. |
| **3. Track** | Progress persists in `progress.json`. Pick up where you left off across sessions. `/read-status` shows exactly how far you are. |

---

## Quick Start

### Prerequisites

- Python 3.11+ with [uv](https://docs.astral.sh/uv/)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI

### Install

```bash
git clone https://github.com/BedirT/no-longer-vibe.git
cd no-longer-vibe
./install.sh
```

This installs the `nlv` CLI, Claude Code skills, and (if VS Code is detected) the extension. You can also install components individually with `--parser-only`, `--skill-only`, or `--extension-only`.

### Start Reading

```bash
# 1. Parse your project
nlv /path/to/your/project

# 2. Open Claude Code in that project, then:
/read-next
```

That's it. You're reading.

---

## The Reading Experience

No Longer Vibe doesn't just hand you files alphabetically. It uses a **three-pass reading order** backed by research on how architects verify implementations:

| Pass | What you read | Why this order |
|------|--------------|----------------|
| **1. Contracts** | Types, interfaces, public APIs, module boundaries | Pattern-match against your own design intent. Fast. |
| **2. Data Flow** | Primary execution flows end-to-end | Spot where AI's approach diverged from yours. |
| **3. Utility** | Helpers, error handlers, fallback logic | Where AI made the most autonomous decisions. |

Within each pass, files are **topologically sorted** --- you never read a file before its dependencies. Test files appear right after their implementation file.

### A Session Looks Like This

```
You:     /read-next

Claude:  ── Next: src/middleware/auth.ts ──────────────────
         Layer: integration │ Lines: 142 │ Complexity: medium

         Why now: All dependencies read.
           ✅ src/config.ts (confirmed)
           ✅ src/models/user.ts (confirmed)

         Exports: authMiddleware, requireRole, refreshToken
         Used by: src/api/routes.ts, src/app.ts (unread, later)
         ────────────────────────────────────────────────────

         [reads file content into conversation]

You:     Why is there a dual token store? Lines 47 and 52.

Claude:  [explains the pattern, references config you already read]

You:     flag - dual token store seems over-engineered

Claude:  Flagged with note. Ready for next?

You:     next
Claude:  ── Next: src/services/cache.ts ─────────────────
         ...
```

### Three-Tier Completion

Every file gets one of three marks:

| Mark | Meaning | When to use |
|------|---------|-------------|
| **confirmed** | Understood. Matches your design intent. | `done` or `confirmed` |
| **flagged** | Needs a second pass. Something surprised you. | `flag <reason>` |
| **skimmed** | Read but want deeper review later. | `skim` |

Run `/read-flagged` later to revisit everything you flagged, with your original notes.

### Session Priming

Context doesn't die between sessions. When you start a new session, `/read-next` feeds Claude compressed summaries of everything you've already read. You get orientation even if Claude doesn't remember the last conversation.

---

## VS Code Extension

<p align="center">
  <img src="docs/assets/screenshot-extension-overview.png" alt="VS Code Extension Overview" width="720" />
  <br />
  <em>File status colors, caller count gutter, CodeLens annotations, and progress sidebar</em>
</p>

The optional VS Code extension adds visual context to your reading sessions. Claude Code controls it via MCP --- the extension is the display driver, Claude is the director.

**Principle: Decoration, not puppeteering.** It adds context to what you're looking at. It never moves your cursor, switches your tabs, or demands attention.

### Caller Count Gutter

<p align="center">
  <img src="docs/assets/screenshot-caller-count.png" alt="Caller Count Gutter" width="600" />
</p>

A small number next to each function showing how many places call it. The single highest-value feature.

> *"The moment I glance at a function and see 'called by: 0' and realize the AI generated dead code without me having to grep --- that's when this tool becomes non-negotiable."*

### File Status Decorations

<p align="center">
  <img src="docs/assets/screenshot-file-status.png" alt="File Status Decorations" width="360" />
</p>

Your explorer tree shows reading progress at a glance:
- 🟢 **Green** --- confirmed (understood)
- 🟠 **Orange** --- flagged (needs revisit)
- 🔵 **Blue** --- currently reading
- No decoration --- unread

### Blast Radius

<p align="center">
  <img src="docs/assets/screenshot-blast-radius.png" alt="Blast Radius" width="600" />
</p>

Select a function, see every file that would be affected if you changed it. All transitive dependents tint orange in the explorer. Claude explains the impact chain.

```
You:     What happens if I change validateToken's signature?
Claude:  → show_blast_radius("validateToken")

[Explorer: 12 files tint orange. Sidebar highlights every
 transitive dependent. Claude explains the impact chain.]
```

### CodeLens Annotations

Clickable "Called by" and "Calls" annotations above each function:

```
Called by: router.ts, api.ts, ws.ts │ Calls: jwt.verify, db.findUser
╭──────────────────────────────────────────────╮
│ export function validateToken(token: string) {│
│   ...                                         │
│ }                                             │
╰──────────────────────────────────────────────╯
```

### Progress Sidebar

A tree view organized by architectural layer, showing files with status icons and completion percentage per layer. Always know where you are.

---

## All Commands

| Command | What it does |
|---------|-------------|
| `nlv [path]` | Parse a codebase and generate `.codebase-guide/map.json` |
| `/read-index [path]` | Run the parser from Claude Code |
| `/read-next` | Next file in reading order with structural briefing |
| `/read-status` | Current progress across all files and layers |
| `/read-flagged` | Second pass through flagged files |
| `/read-refresh` | Re-parse, preserve progress on unchanged files, invalidate stale dependencies |
| `/read-overview` | High-level project orientation before diving in |

---

## Language Support

| Language | AST Parser | Import Resolution |
|----------|-----------|-------------------|
| Python | Built-in `ast` module | Relative/absolute import paths |
| TypeScript / JavaScript | tree-sitter | Module path resolution with index file detection |
| Go | tree-sitter | Package-based import resolution |

The parser uses a plugin architecture. Each language implements `parse_file()` and `resolve_import()`. Adding a new language means adding one file to `packages/parser/src/nlv/plugins/`.

---

## Five Architectural Layers

The parser classifies every file into one of five layers based on its position in the dependency graph:

```
┌─────────────────────────────────────────────────┐
│  entry          App entry points, page-level     │
│                 composition (main.ts, app.ts)    │
├─────────────────────────────────────────────────┤
│  integration    Composes features, middleware,    │
│                 API routes, pipelines            │
├─────────────────────────────────────────────────┤
│  features       Business logic, components,      │
│                 routes, hooks                    │
├─────────────────────────────────────────────────┤
│  core           Models, services, data access    │
│                 — depends only on foundation     │
├─────────────────────────────────────────────────┤
│  foundation     Config, constants, types — no    │
│                 or minimal internal dependencies │
└─────────────────────────────────────────────────┘
```

---

## Configuration

Place a `config.toml` or `config.json` in `.codebase-guide/` to customize behavior:

```toml
# Skip test files from reading order
skip_tests = false

# Where unpaired test files go: "contracts", "data_flow", "utility", "separate", "skip"
test_pass = "utility"

# Tie-breaking: "alphabetical", "file_size", "complexity"
tie_breaking = "alphabetical"

# Force specific files into a pass
[custom_pass_overrides]
"src/types/**" = "contracts"
"src/generated/**" = "utility"

# Exclude files from reading entirely
[exclude_from_reading]
patterns = ["**/*.generated.ts", "**/migrations/**"]
```

<details>
<summary>All configuration options</summary>

| Option | Default | Description |
|--------|---------|-------------|
| `skip_tests` | `false` | Exclude test files from reading order |
| `test_pass` | `"utility"` | Which pass unpaired test files go in |
| `tie_breaking` | `"alphabetical"` | How to break ties in topological sort |
| `integration_fan_in_threshold` | `3` | Minimum fan-in for integration layer |
| `custom_pass_overrides` | `{}` | Force files/globs into specific passes |
| `exclude_from_reading` | `{}` | Glob patterns to exclude entirely |
| `layer_thresholds` | see below | Override layer depth boundaries |

**Test file handling modes:**

| Mode | Behavior |
|------|----------|
| `utility` (default) | Unpaired tests go in Pass 3. Paired tests follow their implementation file. |
| `contracts` / `data_flow` | Unpaired tests go in the specified pass. |
| `separate` | All tests go in a fourth pass after non-test files. |
| `skip` | Exclude test files entirely. |

</details>

---

## Incremental Refresh

Codebases change while you're reading. `/read-refresh` handles this:

```
Refreshed: /path/to/project
  Unchanged: 380 files (progress preserved)
  Modified:  3 files (reset to unread)
  New:       2 files (added as unread)
  Deleted:   1 file (removed)
  Stale:     7 files (dependency changed upstream)
```

**Transitive invalidation:** When a file changes, its reverse dependencies get marked "potentially stale" even if their content hasn't changed. The dependency graph handles this automatically.

---

## Project Structure

```
packages/
  parser/           Python CLI — the deterministic engine
    src/nlv/
      cli.py          Entry point (nlv command)
      plugins/        Language plugins (Python, TypeScript, Go)
      graph/          Dependency graph with cycle detection
      layers.py       Architectural layer classifier
      reading_order.py  Three-pass reading order
      refresh.py      Incremental refresh + transitive invalidation
      ...

  skill/            Claude Code skill definitions
    read-index/       /read-index
    read-next/        /read-next
    read-status/      /read-status
    read-flagged/     /read-flagged
    read-refresh/     /read-refresh

  extension/        VS Code extension (TypeScript)
    src/
      extension.ts          Activation + wiring
      mcpServer.ts          MCP stdio server
      callerCount.ts        Gutter decorations
      codeLensProvider.ts   Caller/callee CodeLens
      blastRadius.ts        Blast radius visualization
      progressTree.ts       Sidebar tree view
      ...
```

---

## Development

```bash
# Parser
uv sync && uv run pytest -x          # test
uv run ruff check .                   # lint
uv run pyright                        # typecheck

# Extension
cd packages/extension
npm install && npm run build          # build
npm test                              # test
```

---

## The Research Behind It

No Longer Vibe isn't arbitrary. The reading order and tool design are informed by research on how developers actually comprehend code:

- **Three-pass order** is based on how architects verify implementations they didn't write (contracts → data flow → utility)
- **No batch AI annotations** --- pre-generated summaries create passive learning, not active engagement ([Chi's ICAP framework, 2014](https://doi.org/10.1177/2372732215624857); [Kalyuga's redundancy effect, 2007](https://doi.org/10.1007/978-0-387-35386-4_9))
- **Max 3-4 visual channels** in the extension --- beyond this threshold, clutter blindness makes users ignore everything ([Yeh & Wickens, 2001](https://doi.org/10.1177/001872080104300301))
- **No animated decorations, no importance heatmaps** --- no consensus definition of "importance" in the literature. Caller count is measurable and actionable.

See [SPEC.md](SPEC.md) for the full technical specification and [ROUNDTABLE.md](ROUNDTABLE.md) for the design rationale.

---

## Design Principles

1. **Deterministic foundation.** Parser output is pure function of source code. No LLM in the analysis pipeline.
2. **Live over batch.** Claude Code provides understanding in conversation. No pre-generated summaries that go stale.
3. **Decoration, not puppeteering.** The extension augments what you see. It never moves your cursor or switches your tabs.
4. **Completeness is measurable.** Progress tracking gives you an exit condition: you're done when all files are confirmed.
5. **After you review it, it's your code.** No permanent AI-written-vs-human markers.

---

## Roadmap

Tracked in [Linear](https://linear.app/bedirt/project/no-longer-vibe-26858b33c0f7).

| Phase | Scope | Status |
|-------|-------|--------|
| Phase 1: Core | Parser + Claude Code Skills | ✅ Complete |
| Phase 2: Extension Tier 1 | File decorations, caller count, highlights | ✅ Complete |
| Phase 3: Iterate & Polish | CodeLens, blast radius, sidebar, more languages | ✅ Complete |

---

## License

Personal tool. Not a product.

---

<p align="center">
  <em>Built for the gap between "my project" and "my code."</em>
</p>
