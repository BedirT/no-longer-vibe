"""Incremental re-parse with transitive invalidation (BED-78).

Diffs old and new map.json content hashes to detect changes, updates
progress.json accordingly, and walks reverse dependency edges to flag
downstream files as potentially stale.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nlv.progress import FileStatus, ProgressManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiffResult:
    """Result of comparing old and new content hashes.

    All lists are sorted for determinism.

    Attributes:
        new_files: Files present in new but not old.
        modified_files: Files present in both but with different hashes.
        removed_files: Files present in old but not new.
        unchanged_files: Files present in both with identical hashes.
    """

    new_files: list[str]
    modified_files: list[str]
    removed_files: list[str]
    unchanged_files: list[str]


@dataclass(frozen=True)
class RefreshResult:
    """Summary of a refresh operation.

    Attributes:
        new: Count of new files added.
        modified: Count of modified files reset to unread.
        removed: Count of removed files deleted from progress.
        unchanged: Count of unchanged files with preserved progress.
        transitively_invalidated: Count of downstream files marked stale.
        pruned: Count of progress entries removed for files not in
            reading_order (e.g. trivial __init__.py, config-excluded).
    """

    new: int
    modified: int
    removed: int
    unchanged: int
    transitively_invalidated: int
    pruned: int


# ---------------------------------------------------------------------------
# Hash diffing
# ---------------------------------------------------------------------------


def diff_content_hashes(
    old_hashes: dict[str, str],
    new_hashes: dict[str, str],
) -> DiffResult:
    """Compare old and new content hashes to categorize file changes.

    Args:
        old_hashes: Content hashes from the previous map.json.
        new_hashes: Content hashes from the newly generated map.json.

    Returns:
        A DiffResult with sorted lists of new, modified, removed,
        and unchanged files.
    """
    old_keys = set(old_hashes)
    new_keys = set(new_hashes)

    new_files = sorted(new_keys - old_keys)
    removed_files = sorted(old_keys - new_keys)

    modified_files: list[str] = []
    unchanged_files: list[str] = []

    for path in sorted(old_keys & new_keys):
        if old_hashes[path] != new_hashes[path]:
            modified_files.append(path)
        else:
            unchanged_files.append(path)

    return DiffResult(
        new_files=new_files,
        modified_files=modified_files,
        removed_files=removed_files,
        unchanged_files=unchanged_files,
    )


# ---------------------------------------------------------------------------
# Transitive invalidation
# ---------------------------------------------------------------------------


def _walk_reverse_dependencies(
    modified_files: list[str],
    dep_graph: dict[str, dict[str, list[str]]],
    *,
    exclude: set[str],
) -> dict[str, str]:
    """Walk reverse dependency edges from modified files.

    Uses BFS to find all transitive dependents of modified files.
    Files in the exclude set (e.g. already modified or new) are
    not included in the result.

    Args:
        modified_files: Files whose content changed.
        dep_graph: The dependency_graph from map.json. Each entry
            has ``imported_by`` listing reverse dependents.
        exclude: Set of file paths to skip (already handled).

    Returns:
        Mapping of stale file path to a note describing which
        dependency triggered the invalidation.
    """
    stale: dict[str, str] = {}
    queue: deque[tuple[str, str]] = deque()

    # Seed the queue with direct dependents of modified files
    for modified in modified_files:
        entry = dep_graph.get(modified, {})
        imported_by: list[str] = entry.get("imported_by", [])
        for dependent in imported_by:
            if dependent not in exclude:
                queue.append((dependent, modified))

    visited: set[str] = set()

    while queue:
        file_path, changed_dep = queue.popleft()
        if file_path in visited:
            continue
        visited.add(file_path)

        if file_path not in exclude:
            stale[file_path] = (
                f"Dependency changed: {changed_dep} was modified"
            )

        # Continue walking reverse edges
        entry = dep_graph.get(file_path, {})
        imported_by = entry.get("imported_by", [])
        for next_dep in imported_by:
            if next_dep not in visited and next_dep not in exclude:
                queue.append((next_dep, changed_dep))

    return stale


# ---------------------------------------------------------------------------
# Main refresh logic
# ---------------------------------------------------------------------------


def refresh_progress(
    guide_dir: Path,
    new_map: dict[str, Any],
    new_map_hash: str,
    *,
    old_content_hashes: dict[str, str] | None = None,
) -> RefreshResult:
    """Refresh progress.json after re-parsing the codebase.

    Compares old and new content hashes, updates file statuses,
    walks reverse dependency edges for transitive invalidation,
    and updates the map_hash.

    Args:
        guide_dir: Path to the ``.codebase-guide`` directory.
        new_map: The newly generated map.json data.
        new_map_hash: SHA-256 hex digest of the new map.json content.
        old_content_hashes: Content hashes from the previous map.json.
            If None, reads them from the map.json file currently on
            disk (which should be the old one, before re-writing).

    Returns:
        A RefreshResult summarizing what changed.

    Raises:
        FileNotFoundError: If progress.json does not exist.
    """
    mgr = ProgressManager(guide_dir)
    old_data = mgr.load()

    if old_content_hashes is not None:
        old_hashes = old_content_hashes
    else:
        old_hashes = _extract_old_hashes(guide_dir)
    new_hashes: dict[str, str] = new_map.get("content_hashes", {})
    dep_graph: dict[str, dict[str, list[str]]] = new_map.get(
        "dependency_graph", {},
    )

    diff = diff_content_hashes(old_hashes, new_hashes)

    files = old_data["files"]

    # 1. Remove deleted files
    for path in diff.removed_files:
        files.pop(path, None)

    # 2. Reset modified files to unread
    for path in diff.modified_files:
        files[path] = {
            "status": FileStatus.UNREAD.value,
            "read_at": None,
            "note": None,
            "summary": None,
        }

    # 3. Add new files as unread (preserve existing progress if already tracked)
    for path in diff.new_files:
        if path not in files:
            files[path] = {
                "status": FileStatus.UNREAD.value,
                "read_at": None,
                "note": None,
                "summary": None,
            }

    # 4. Transitive invalidation — exclude files that are already
    #    unread or were just modified/newly added
    already_handled = set(diff.modified_files) | set(diff.new_files)
    for path in diff.unchanged_files:
        if files.get(path, {}).get("status") == FileStatus.UNREAD.value:
            already_handled.add(path)

    stale_files = _walk_reverse_dependencies(
        diff.modified_files, dep_graph, exclude=already_handled,
    )

    invalidated_count = 0
    for path, note in stale_files.items():
        if path in files:
            files[path]["status"] = FileStatus.FLAGGED.value
            files[path]["note"] = note
            invalidated_count += 1

    # 5. Prune files not in reading_order (excluded by trivial init
    #    filter, config exclude_from_reading patterns, etc.)
    reading_order_paths = {
        e["path"] for e in new_map.get("reading_order", [])
    }
    pruned_paths = [p for p in list(files) if p not in reading_order_paths]
    for p in pruned_paths:
        del files[p]
    if pruned_paths:
        logger.debug(
            "Pruned %d file(s) not in reading_order", len(pruned_paths),
        )

    # 6. Update map_hash and recompute stats
    old_data["map_hash"] = new_map_hash
    old_data["stats"] = mgr.compute_stats()

    # 7. Save atomically
    mgr.save()

    return RefreshResult(
        new=len(diff.new_files),
        modified=len(diff.modified_files),
        removed=len(diff.removed_files),
        unchanged=len(diff.unchanged_files),
        transitively_invalidated=invalidated_count,
        pruned=len(pruned_paths),
    )


def _extract_old_hashes(guide_dir: Path) -> dict[str, str]:
    """Extract content hashes from the old map.json on disk.

    Reads the map.json that is currently on disk. In the normal
    workflow this should be called before the parser overwrites
    map.json with the new version.

    Args:
        guide_dir: Path to the .codebase-guide directory.

    Returns:
        Content hashes dict from the old map.json, or empty dict
        if the map cannot be read.
    """
    map_path = guide_dir / "map.json"
    if not map_path.exists():
        return {}
    try:
        raw = map_path.read_text()
        data: dict[str, Any] = json.loads(raw)
        result: dict[str, str] = data.get("content_hashes", {})
        return result
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read old map.json, treating all files as new")
        return {}


