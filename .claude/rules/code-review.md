# Code Review Criteria — No Longer Vibe

When reviewing code in this project (as a code-reviewer agent or during
self-review), check the following project-specific criteria:

## Parser (packages/parser/)
- AST parsing must be deterministic — same input always produces same output
- Dependency graph must handle circular imports without crashing
- Plugin interface contract must be honored (parseFile, resolveImport signatures)
- Content hashes must use SHA-256 on file content only, not metadata
- map.json output must match the schema defined in SPEC.md

## Skill (packages/skill/)
- All slash commands must read map.json and progress.json, never hardcode paths
- Progress updates must be atomic — no partial writes on crash
- Session priming must stay within context budget (compressed summaries)
- Three-tier completion (confirmed/flagged/skimmed) must be consistent

## Extension (packages/extension/)
- Max 3-4 simultaneous visual channels (research constraint)
- No animated decorations, no persistent AI explanations
- Extension reads map.json locally — MCP is control channel, not data channel
- Decoration, not puppeteering — never move cursor or switch tabs

## General
- Python files: type hints required, follow PEP 8
- Functions over 50 lines should be flagged for splitting
- No hardcoded file paths — all paths relative to repo root
- Tests must exist for every new function (TDD workflow)
- No print() statements — use logging module
