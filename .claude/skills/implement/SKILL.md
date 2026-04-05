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

The user provides either:
- A Linear issue ID (e.g., `BED-60`): implement that specific issue
- The word `next`: automatically pick the next available issue

## Pipeline

### Step 1: Pick and Claim the Issue

**If a specific issue ID was given:**
Use the Linear MCP to read the full issue: title, description,
acceptance criteria, labels, milestone, and blocking/blocked-by
relations. The issue description IS the spec.

**If `next` was given:**
Use the Linear MCP to find the next available issue:
1. List issues in the "No Longer Vibe" project
2. Filter to issues with status **Todo** or **Backlog** only — skip
   any issue that is **In Progress**, **In Review**, **Done**, or
   **Cancelled**
3. Skip issues whose blocking dependencies are not yet **Done**
4. Respect priority ordering — pick the highest-priority unblocked
   issue
5. Tell the user which issue you picked and why before proceeding

**Claim the issue immediately:**
Once you have the issue, **set its Linear status to "In Progress"**
right away, before creating a branch or writing any code. This
prevents other agents from picking the same issue. Also update
`agent-progress.json` with the issue ID you are working on.

If the issue description is ambiguous or incomplete, stop and ask the
user for clarification before proceeding (but keep the status as
In Progress — you've claimed it).

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

Set the Linear issue status to **Done**. Add a comment summarizing
what was implemented, including a link to the PR.

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
