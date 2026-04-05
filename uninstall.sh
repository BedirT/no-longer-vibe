#!/usr/bin/env bash
# Uninstall No Longer Vibe — remove parser CLI, Claude Code skills, and VS Code extension.
#
# Usage:
#   ./uninstall.sh

set -euo pipefail

print_success() { echo "  ✓ $1"; }
print_skip()    { echo "  ⊘ $1"; }
print_error()   { echo "  ✗ $1" >&2; }
print_header()  { echo ""; echo "── $1 ──"; }

echo "Uninstalling No Longer Vibe"

# ── Parser CLI ──────────────────────────────────────────────────────────

print_header "Parser CLI (nlv)"

if command -v uv >/dev/null 2>&1; then
    if uv tool uninstall nlv 2>&1; then
        print_success "nlv CLI removed"
    else
        print_skip "nlv was not installed via uv tool"
    fi
else
    print_skip "uv not found — skipping CLI removal"
fi

# ── Claude Code Skills ──────────────────────────────────────────────────

print_header "Claude Code Skills"

SKILL_DIR="$HOME/.claude/skills"
COMMANDS=(read-index read-next read-status read-flagged read-refresh)
removed=0

for cmd in "${COMMANDS[@]}"; do
    dest="$SKILL_DIR/$cmd"
    if [[ -L "$dest" ]] || [[ -d "$dest" ]]; then
        rm -rf "$dest"
        removed=$((removed + 1))
    fi
done

if [[ "$removed" -gt 0 ]]; then
    print_success "Removed $removed skill symlinks from $SKILL_DIR"
else
    print_skip "No skill symlinks found in $SKILL_DIR"
fi

# ── VS Code Extension ──────────────────────────────────────────────────

print_header "VS Code Extension"

if command -v code >/dev/null 2>&1; then
    if code --uninstall-extension no-longer-vibe.no-longer-vibe 2>&1; then
        print_success "VS Code extension removed"
    else
        print_skip "VS Code extension was not installed"
    fi
else
    print_skip "VS Code not found — skipping extension removal"
fi

echo ""
echo "Done."
