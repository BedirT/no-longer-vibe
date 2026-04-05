# No Longer Vibe

Deterministic codebase reading tool: a Python parser builds dependency
graphs and smart reading order, a Claude Code skill sequences files and
tracks comprehension sessions, and an optional VS Code extension adds
visual context.

## Tech Stack

- Parser: Python 3.11+ (uv)
- Skill: Claude Code skill (Markdown + shell)
- Extension: TypeScript (VS Code API + MCP stdio)
- Monorepo: packages/parser, packages/skill, packages/extension

## Commands

- Install: `uv sync`
- Test: `./scripts/run-check.sh uv run pytest -x`
- Lint: `./scripts/run-check.sh uv run ruff check .`
- Typecheck: `./scripts/run-check.sh uv run pyright`
- Single test: `uv run pytest -x -k "test_name"`

## Workflow

1. Agent receives a Linear issue ID as input. The issue description
   IS the spec — read it fully before writing any code.
2. TDD: write failing tests from the issue requirements first,
   then implement until they pass.
3. After implementation, spawn a code-reviewer agent. Fix all
   findings. Re-review until the reviewer passes clean. Do not
   skip this loop.
4. Stop and ask the user for: architectural decisions not covered
   by the issue, ambiguous or incomplete specs, and anything
   requiring manual validation (CLI output, visual behavior).
5. Create a detailed PR: link the Linear issue, summarize changes
   and rationale, include review agent findings, and list a
   test plan.

## Session Start

1. Run `./scripts/init.sh` to verify environment
2. Read `agent-progress.json` for context from previous sessions
3. Resume from where the last session left off, or pick the next
   unblocked Linear issue — **always check issue statuses in Linear
   before picking**. Issues marked "In Progress" are claimed by
   another agent — do not pick them.
4. When you start working on an issue, **set its Linear status to
   "In Progress" immediately** so other agents know it's claimed
5. Update `agent-progress.json` before ending the session

## Project Docs

- @SPEC.md
- @docs/ARCHITECTURE.md
- @docs/TESTING.md
