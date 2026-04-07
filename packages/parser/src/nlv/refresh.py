"""Incremental re-parse with transitive invalidation (BED-78).

Diffs old and new map.json content hashes to detect changes, updates
progress.json accordingly, and walks reverse dependency edges to flag
downstream files as potentially stale.

Also provides git-based staleness detection (BED-150) as a lightweight
alternative that uses ``git diff`` between stored and current commits.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nlv.git import (
    commit_exists,
    diff_name_status,
    get_current_branch,
    get_head_commit,
    is_git_repo,
)
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


# ---------------------------------------------------------------------------
# Git-based staleness detection (BED-150)
# ---------------------------------------------------------------------------


def git_diff_to_diff_result(
    name_status: list[tuple[str, ...]],
    tracked_files: set[str],
) -> DiffResult:
    """Convert ``git diff --name-status`` output to a DiffResult.

    Maps git status codes to the same categories used by the
    hash-based diff:

    - **A** (added) → ``new_files``
    - **M** (modified) → ``modified_files``
    - **D** (deleted) → ``removed_files``
    - Everything not in the diff → ``unchanged_files``

    Renames (R) are treated as delete + add. With ``--no-renames``
    this shouldn't occur, but is handled for safety.

    Args:
        name_status: Tuples from ``diff_name_status()``.
        tracked_files: Set of file paths currently in progress.json
            or map.json — used to compute the unchanged set.

    Returns:
        A DiffResult with sorted lists.
    """
    new: list[str] = []
    modified: list[str] = []
    removed: list[str] = []
    changed_paths: set[str] = set()

    for entry in name_status:
        status = entry[0]
        path = entry[1]

        if status == "A":
            new.append(path)
            changed_paths.add(path)
        elif status == "M":
            modified.append(path)
            changed_paths.add(path)
        elif status == "D":
            removed.append(path)
            changed_paths.add(path)
        elif status.startswith("R") and len(entry) >= 3:
            old_path = entry[1]
            new_path = entry[2]
            removed.append(old_path)
            new.append(new_path)
            changed_paths.add(old_path)
            changed_paths.add(new_path)
        else:
            logger.debug("Unknown git status %r for %s", status, path)

    unchanged = sorted(tracked_files - changed_paths)

    return DiffResult(
        new_files=sorted(new),
        modified_files=sorted(modified),
        removed_files=sorted(removed),
        unchanged_files=unchanged,
    )


def _filter_guide_dir_entries(
    entries: list[tuple[str, ...]],
    guide_dir: Path,
    repo_root: Path,
) -> list[tuple[str, ...]]:
    """Remove entries under the .codebase-guide directory from git diff.

    The guide directory contains map.json, progress.json and other
    internal files that should not be treated as source file changes.
    """
    try:
        prefix = (
            guide_dir.resolve().relative_to(repo_root.resolve()).as_posix()
        )
    except ValueError:
        return entries

    return [
        entry for entry in entries
        if not entry[1].startswith(prefix + "/")
        and entry[1] != prefix
    ]


def refresh_progress_from_git(
    guide_dir: Path,
    repo_root: Path,
) -> RefreshResult | None:
    """Lightweight git-based staleness detection.

    Checks whether files have changed since the last recorded git
    commit. Uses ``git diff --name-status`` instead of content-hash
    comparison for efficiency.

    Returns ``None`` when git-based refresh is not possible (non-git
    repo, missing stored commit, no map.json). The caller should fall
    back to hash-based ``refresh_progress()`` in that case.

    Args:
        guide_dir: Path to the ``.codebase-guide`` directory.
        repo_root: Root of the git repository.

    Returns:
        A RefreshResult summarizing what changed, or None if
        git-based refresh cannot be performed.
    """
    # 1. Load progress
    mgr = ProgressManager(guide_dir)
    try:
        data = mgr.load()
    except FileNotFoundError:
        return None

    # 2. Check stored git state
    stored_commit, _stored_branch = mgr.get_git_state()
    if stored_commit is None:
        return None

    # 3. Verify git repo
    if not is_git_repo(repo_root):
        return None

    # 4. Verify stored commit exists
    if not commit_exists(repo_root, stored_commit):
        logger.debug(
            "Stored commit %s no longer exists, "
            "falling back to hash-based refresh",
            stored_commit[:12],
        )
        return None

    # 5. Get current HEAD
    current_commit = get_head_commit(repo_root)
    if current_commit is None:
        return None

    # 6. Load map.json for dependency graph
    map_path = guide_dir / "map.json"
    if not map_path.exists():
        return None
    try:
        map_data: dict[str, Any] = json.loads(map_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    dep_graph: dict[str, dict[str, list[str]]] = map_data.get(
        "dependency_graph", {},
    )

    # 7. Same commit — nothing changed
    if current_commit == stored_commit:
        current_branch = get_current_branch(repo_root)
        mgr.set_git_state(current_commit, current_branch)
        return RefreshResult(
            new=0,
            modified=0,
            removed=0,
            unchanged=len(data["files"]),
            transitively_invalidated=0,
            pruned=0,
        )

    # 8. Compute git diff
    diff_entries = diff_name_status(repo_root, stored_commit, current_commit)
    if diff_entries is None:
        return None

    # 8b. Filter out internal guide-dir files from the diff
    diff_entries = _filter_guide_dir_entries(
        diff_entries, guide_dir, repo_root,
    )

    # 9. Convert to DiffResult
    tracked_files = set(data["files"].keys())
    diff = git_diff_to_diff_result(diff_entries, tracked_files)

    files = data["files"]

    # 10. Apply changes (same logic as hash-based refresh)

    # Remove deleted files
    for path in diff.removed_files:
        files.pop(path, None)

    # Reset modified files to unread
    for path in diff.modified_files:
        if path in files:
            files[path] = {
                "status": FileStatus.UNREAD.value,
                "read_at": None,
                "note": None,
                "summary": None,
            }

    # Track new files (not added to reading order — needs re-index)
    for path in diff.new_files:
        if path not in files:
            files[path] = {
                "status": FileStatus.UNREAD.value,
                "read_at": None,
                "note": None,
                "summary": None,
            }

    # 11. Transitive invalidation
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

    # 12. Update stats and git state
    data["stats"] = mgr.compute_stats()
    current_branch = get_current_branch(repo_root)
    data["git_commit"] = current_commit
    data["git_branch"] = current_branch
    mgr.save()

    return RefreshResult(
        new=len(diff.new_files),
        modified=len(diff.modified_files),
        removed=len(diff.removed_files),
        unchanged=len(diff.unchanged_files),
        transitively_invalidated=invalidated_count,
        pruned=0,
    )


