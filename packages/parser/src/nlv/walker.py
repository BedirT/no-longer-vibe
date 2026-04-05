"""File tree walker — .gitignore-aware source file collection."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pathspec

logger = logging.getLogger(__name__)

SKIP_DIRS: frozenset[str] = frozenset({
    "node_modules",
    "dist",
    "build",
    ".git",
    "__pycache__",
    "venv",
    ".venv",
    ".tox",
})

_TEST_DIR_NAMES: frozenset[str] = frozenset({"tests", "test"})


@dataclass(frozen=True, slots=True)
class SourceFile:
    """A discovered source file with metadata."""

    path: str
    is_test: bool


def _load_gitignore(directory: Path) -> pathspec.PathSpec | None:
    """Load .gitignore from a directory, returning None if absent."""
    gitignore = directory / ".gitignore"
    if not gitignore.is_file():
        return None
    try:
        patterns = gitignore.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Could not read %s", gitignore)
        return None
    return pathspec.PathSpec.from_lines("gitignore", patterns.splitlines())


def _is_test_file(rel_path: str) -> bool:
    """Determine if a file is a test file based on naming conventions."""
    parts = rel_path.split("/")
    name = parts[-1]

    # conftest.py
    if name == "conftest.py":
        return True

    # test_*.py or *_test.py
    stem = Path(name).stem
    if stem.startswith("test_") or stem.endswith("_test"):
        return True

    # Inside a tests/ or test/ directory
    return any(part in _TEST_DIR_NAMES for part in parts[:-1])


def walk_tree(
    root: Path,
    extensions: set[str],
) -> list[SourceFile]:
    """Walk a file tree collecting source files.

    Args:
        root: Root directory to walk.
        extensions: Set of file extensions to include (e.g. {".py"}).

    Returns:
        Sorted list of SourceFile objects with relative paths.
    """
    root = root.resolve()
    # Collect gitignore specs keyed by directory (relative to root)
    gitignore_specs: list[tuple[str, pathspec.PathSpec]] = []

    root_spec = _load_gitignore(root)
    if root_spec is not None:
        gitignore_specs.append(("", root_spec))

    results: list[SourceFile] = []
    _walk_dir(root, root, extensions, gitignore_specs, results)
    results.sort(key=lambda f: f.path)
    return results


def _is_ignored(
    rel_path: str,
    gitignore_specs: list[tuple[str, pathspec.PathSpec]],
) -> bool:
    """Check if a relative path matches any accumulated gitignore spec."""
    for prefix, spec in gitignore_specs:
        if prefix:
            # Nested gitignore — match relative to its directory
            if rel_path.startswith(prefix):
                sub_path = rel_path[len(prefix):]
                if spec.match_file(sub_path):
                    return True
        else:
            if spec.match_file(rel_path):
                return True
    return False


def _walk_dir(
    current: Path,
    root: Path,
    extensions: set[str],
    gitignore_specs: list[tuple[str, pathspec.PathSpec]],
    results: list[SourceFile],
) -> None:
    """Recursively walk a directory, collecting matching files."""
    try:
        entries = sorted(current.iterdir(), key=lambda p: p.name)
    except PermissionError:
        logger.warning("Permission denied: %s", current)
        return

    for entry in entries:
        # Skip symlinks
        if entry.is_symlink():
            continue

        rel = entry.relative_to(root).as_posix()

        if entry.is_dir():
            # Skip well-known non-source directories
            if entry.name in SKIP_DIRS:
                continue
            # Skip gitignored directories
            if _is_ignored(rel + "/", gitignore_specs):
                continue
            # Load nested .gitignore if present
            nested_spec = _load_gitignore(entry)
            if nested_spec is not None:
                gitignore_specs.append((rel + "/", nested_spec))
                _walk_dir(entry, root, extensions, gitignore_specs, results)
                gitignore_specs.pop()
            else:
                _walk_dir(entry, root, extensions, gitignore_specs, results)
        elif entry.is_file():
            # Filter by extension
            if entry.suffix not in extensions:
                continue
            # Skip gitignored files
            if _is_ignored(rel, gitignore_specs):
                continue
            results.append(SourceFile(path=rel, is_test=_is_test_file(rel)))
