---
name: implement
description: Implement a Linear issue end-to-end with TDD, code review loop, and PR creation
triggers:
  - /implement
---

# Implement from Linear Issue

You are implementing a feature from a Linear issue. Follow this pipeline
exactly. Do not skip steps.

## Input

The user provides a Linear issue ID (e.g., BED-60). If no ID is given,
ask for one.

## Pipeline

### Step 1: Read the Issue

Use the Linear MCP to read the full issue: title, description,
acceptance criteria, labels, milestone, and blocking/blocked-by
relations. The issue description IS the spec.

If the issue description is ambiguous or incomplete, stop and ask the
user for clarification before proceeding.

### Step 2: Create Branch

Create a feature branch: `feat/<issue-id>-<short-description>`
Example: `feat/bed-60-project-scaffolding`

### Step 3: TDD — Write Tests First

Read the issue requirements carefully. Write failing tests that encode
the acceptance criteria BEFORE writing any implementation code.

- Place tests in the appropriate `tests/` directory
- Name test files to match: `test_<module>.py`
- Run tests to confirm they fail: `uv run pytest -x`
- Commit the failing tests: `test: add failing tests for <issue-id>`

### Step 4: Implement

Write the minimum code to make the tests pass. Follow the project's
coding standards (type hints, no print(), logging module, etc.).

- Run tests after each significant change
- Commit incrementally with descriptive messages
- If you hit an architectural decision not covered by the issue, stop
  and ask the user

### Step 5: Code Review Loop

Spawn a code-reviewer agent to review your changes:

```
git diff main...HEAD
```

The reviewer checks against `.claude/rules/code-review.md` criteria.

**Loop protocol:**
1. Spawn code-reviewer agent with the diff
2. Receive findings
3. Fix all findings
4. Re-run tests to confirm fixes don't break anything
5. Re-spawn code-reviewer agent
6. Repeat until the reviewer returns a clean pass
7. Do NOT skip this loop or declare it "good enough"

### Step 6: Validate

- Run the full test suite: `uv run pytest`
- Run lint: `uv run ruff check .`
- Run typecheck: `uv run pyright`
- For parser changes: run on a test fixture, verify valid JSON output
- For extension changes: ask the user to validate visual behavior
- Verify the diff only contains changes relevant to the issue

### Step 7: Update Linear

Update the Linear issue status to reflect progress. Add a comment
summarizing what was implemented.

### Step 8: Create PR

Create a detailed pull request using `gh pr create`:

- Title: `<type>(<scope>): <description> [<issue-id>]`
- Body must include:
  - **Summary**: What changed and why (2-3 bullets)
  - **Linear Issue**: Link to the issue
  - **Changes**: File-by-file summary of significant changes
  - **Review Agent Findings**: Summary of what the review loop caught
  - **Test Plan**: How to verify the changes work
  - **Checklist**: All tests pass, lint clean, types clean

### Step 9: Report

Tell the user:
- PR URL
- Summary of what was implemented
- Any review findings that were fixed
- Any open questions or follow-up items
