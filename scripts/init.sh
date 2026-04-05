#!/bin/bash
set -euo pipefail

echo "=== No Longer Vibe — Session Init ==="

# 1. Dependencies
if [ -f pyproject.toml ]; then
  uv sync --quiet || { echo "FAIL: uv sync"; exit 1; }
  echo "✓ Dependencies installed"
else
  echo "⚠ No pyproject.toml — project not yet scaffolded"
fi

# 2. Build check
if [ -f pyproject.toml ]; then
  ./scripts/run-check.sh uv run pyright 2>/dev/null && echo "✓ Types clean" || echo "⚠ Type errors present"
fi

# 3. Test check
if [ -f pyproject.toml ]; then
  ./scripts/run-check.sh uv run pytest -x 2>/dev/null && echo "✓ Tests pass" || echo "⚠ Test failures present"
fi

# 4. Progress
if [ -f agent-progress.json ]; then
  echo "=== Previous Progress ==="
  cat agent-progress.json
  echo ""
fi

# 5. Git status
echo "=== Git Status ==="
git status --short
echo ""
echo "=== Recent Commits ==="
git log --oneline -5 2>/dev/null || echo "(no commits yet)"

echo ""
echo "=== Ready ==="
