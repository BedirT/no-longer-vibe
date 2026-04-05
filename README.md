# No Longer Vibe

Codebase comprehension tool for after vibe-coding.

Read your entire AI-generated codebase, fast, in smart order, with deterministic progress tracking. Built as a Claude Code skill + parser. Zero infrastructure.

## The Problem

You vibe-coded your app. The project works. But there's a gap between "my project" and "my code." You want to close that gap by reading everything — not searching, not skipping — the way you would have understood it if you'd written it manually.

**The math**: Vibe-code in 1x. Read and understand in 2x. Total 3x. Still ~7x faster than writing it yourself. This tool compresses that 2x.

## Architecture

Two components. Zero infrastructure.

### Parser (Python CLI)

A deterministic CLI that:
- Walks the file tree, parses ASTs (Python first, more languages later)
- Resolves imports, builds a dependency graph
- Classifies files into layers (foundation → core → features → integration → entry)
- Computes a three-pass reading order (contract surfaces → data flow → utility code)
- Pairs test files with their implementation for co-located reading
- Outputs `.codebase-guide/map.json`

Same repo = same output.

### Claude Code Skill (Slash Commands)

- `/read-index [path]` — Run the parser, generate map.json
- `/read-next` — Next unread file with structural context + dependency briefing
- `/read-status` — Progress dashboard
- `/read-flagged` — Second pass through flagged files
- `/read-refresh` — Incremental re-parse with transitive invalidation

Three-tier completion: **confirmed** (understood), **flagged** (needs revisit), **skimmed** (shallow pass).

### VS Code Extension (Optional)

Visual layer controlled by Claude Code via MCP:
- File status colors in explorer (green/orange/blue)
- Caller count in gutter (the killer feature — dead code detection at a glance)
- Highlight ranges for focused reading
- Blast radius visualization

## Project Structure

```
packages/
  parser/          # Python CLI (uv)
  skill/           # Claude Code skill
  extension/       # VS Code extension (TypeScript)
scripts/
  run-check.sh     # Back-pressure wrapper for CI/hooks
  init.sh          # Agent session initialization
docs/
  ARCHITECTURE.md  # Component design (fill after scaffolding)
  TESTING.md       # Test strategy and conventions
```

## Development

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest -x

# Lint
uv run ruff check .

# Type check
uv run pyright
```

## Roadmap

Tracked in [Linear](https://linear.app/bedirt/project/no-longer-vibe-26858b33c0f7).

| Phase | Scope | Issues |
|-------|-------|--------|
| Phase 1: Core | Parser + Skill | BED-57 — BED-79 |
| Phase 2: Extension Tier 1 | VS Code basics | BED-80 — BED-86 |
| Phase 3: Iterate & Polish | CodeLens, blast radius, more languages | BED-87 — BED-92 |

## Design References

- See [SPEC.md](SPEC.md) for the full technical specification
- See [ROUNDTABLE.md](ROUNDTABLE.md) for the design rationale and research backing

## License

Personal tool. Not a product.
