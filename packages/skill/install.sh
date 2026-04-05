#!/usr/bin/env bash
# Note: prefer running ./install.sh from the repo root for full installation.
#
# Install No Longer Vibe skills for Claude Code.
#
# Usage:
#   ./install.sh           # Install to ~/.claude/skills/ (global)
#   ./install.sh --local   # Install to <repo>/.claude/skills/ (project)

set -euo pipefail

command -v python3 >/dev/null 2>&1 || { echo "Error: python3 required" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMMANDS=(read-index read-next read-overview read-status read-flagged read-refresh)

MODE="global"
TARGET_DIR="$HOME/.claude/skills"

if [[ "${1:-}" == "--local" ]]; then
    MODE="local"
    # Walk up to find repo root (.git)
    REPO_ROOT="$SCRIPT_DIR"
    while [[ "$REPO_ROOT" != "/" ]] && [[ ! -d "$REPO_ROOT/.git" ]] && [[ ! -f "$REPO_ROOT/.git" ]]; do
        REPO_ROOT="$(dirname "$REPO_ROOT")"
    done
    if [[ "$REPO_ROOT" == "/" ]]; then
        echo "Error: could not find repo root (no .git found)" >&2
        exit 1
    fi
    TARGET_DIR="$REPO_ROOT/.claude/skills"
fi

echo "Installing No Longer Vibe skills ($MODE) to $TARGET_DIR"
mkdir -p "$TARGET_DIR"

for cmd in "${COMMANDS[@]}"; do
    src="$SCRIPT_DIR/$cmd"
    dest="$TARGET_DIR/$cmd"

    if [[ ! -d "$src" ]]; then
        echo "Warning: source directory $src not found, skipping $cmd" >&2
        continue
    fi

    # Remove existing (symlink or directory)
    if [[ -L "$dest" ]] || [[ -d "$dest" ]]; then
        rm -rf "$dest"
    fi

    # Use relative symlink so it works across clones
    rel_src="$(python3 -c "import os.path,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))" "$src" "$(dirname "$dest")")"
    ln -s "$rel_src" "$dest"
    echo "  Linked: $cmd -> $rel_src"
done

echo "Done. Skills available: ${COMMANDS[*]}"
