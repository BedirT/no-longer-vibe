# Verification Rules

## Pre-Completion Checklist

Before completing any task:
- [ ] All tests pass: `./scripts/run-check.sh uv run pytest -x`
- [ ] No lint errors: `./scripts/run-check.sh uv run ruff check .`
- [ ] No type errors: `./scripts/run-check.sh uv run pyright`
- [ ] Changes address the original Linear issue — re-read the issue description
- [ ] No unrelated files modified — check `git diff --stat`
- [ ] For parser changes: run on a test fixture, verify valid map.json output
- [ ] For extension changes: stop and ask user to validate visual behavior

## Loop Detection

If you have edited the same file 3+ times for the same issue, stop and:
1. Summarize what you have tried
2. Explain why each attempt failed
3. Ask for guidance before continuing

## Stuck Detection

If 3 consecutive fix attempts have not resolved the issue:
1. Do not try a 4th time
2. Present the problem, your attempts, and your best theory
3. Wait for user guidance before proceeding
