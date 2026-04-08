"""Tests for git-based progress tracking integration (BED-150).

Covers: git state in progress.json, git-diff-to-DiffResult conversion,
refresh_progress_from_git end-to-end, guide-dir filtering, and index
pipeline git recording.

The ``git_repo`` fixture is provided by conftest.py.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from nlv.git import get_head_commit
from nlv.progress import FileStatus, ProgressManager
from nlv.refresh import (
    _filter_guide_dir_entries,
    git_diff_to_diff_result,
    refresh_progress_from_git,
)


def _git_commit(repo: Path, msg: str) -> str:
    """Stage all and commit. Return the new commit hash."""
    subprocess.run(
        ["git", "add", "."],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=repo, capture_output=True, check=True,
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _make_map_data(
    files: list[str],
    *,
    hashes: dict[str, str] | None = None,
    dep_graph: dict[str, dict[str, list[str]]] | None = None,
) -> dict[str, Any]:
    """Build a map.json structure for testing."""
    if hashes is None:
        hashes = {
            f: hashlib.sha256(f.encode()).hexdigest()[:8]
            for f in files
        }
    if dep_graph is None:
        dep_graph = {
            f: {"imports": [], "imported_by": []} for f in files
        }
    return {
        "version": "1.0.0",
        "repo_root": "/tmp/test-repo",
        "generated_at": "2026-04-05T10:00:00Z",
        "content_hashes": hashes,
        "total_files": len(files),
        "layers": {
            "foundation": {"description": "No deps", "files": files},
        },
        "reading_order": [
            {"index": i, "path": f, "layer": "foundation"}
            for i, f in enumerate(files)
        ],
        "dependency_graph": dep_graph,
    }


def _write_map(guide_dir: Path, map_data: dict[str, Any]) -> str:
    """Write map.json and return its content hash."""
    guide_dir.mkdir(parents=True, exist_ok=True)
    content = json.dumps(map_data, indent=2)
    (guide_dir / "map.json").write_text(content)
    return hashlib.sha256(content.encode()).hexdigest()


def _setup_progress(
    guide_dir: Path,
    map_data: dict[str, Any],
    *,
    git_commit: str | None = None,
    git_branch: str | None = None,
    confirmed: list[str] | None = None,
    flagged: list[str] | None = None,
) -> str:
    """Create progress.json with optional git state and read files."""
    map_hash = _write_map(guide_dir, map_data)
    mgr = ProgressManager(guide_dir)
    mgr.create(map_data, map_hash)
    if git_commit is not None:
        mgr.set_git_state(git_commit, git_branch)
    for path in confirmed or []:
        mgr.update_file(
            path, status=FileStatus.CONFIRMED, summary=f"Read {path}.",
        )
    for path in flagged or []:
        mgr.update_file(
            path, status=FileStatus.FLAGGED, note=f"Flag {path}.",
        )
    return map_hash


# ---------------------------------------------------------------------------
# git_diff_to_diff_result
# ---------------------------------------------------------------------------


class TestGitDiffToDiffResult:
    """Converting git name-status output to DiffResult."""

    def test_added_files(self) -> None:
        name_status = [("A", "c.py")]
        tracked = {"a.py", "b.py"}
        result = git_diff_to_diff_result(name_status, tracked)
        assert result.new_files == ["c.py"]
        assert sorted(result.unchanged_files) == ["a.py", "b.py"]

    def test_modified_files(self) -> None:
        name_status = [("M", "a.py")]
        tracked = {"a.py", "b.py"}
        result = git_diff_to_diff_result(name_status, tracked)
        assert result.modified_files == ["a.py"]
        assert result.unchanged_files == ["b.py"]

    def test_deleted_files(self) -> None:
        name_status = [("D", "b.py")]
        tracked = {"a.py", "b.py"}
        result = git_diff_to_diff_result(name_status, tracked)
        assert result.removed_files == ["b.py"]
        assert result.unchanged_files == ["a.py"]

    def test_mixed_changes(self) -> None:
        name_status = [("M", "a.py"), ("D", "b.py"), ("A", "d.py")]
        tracked = {"a.py", "b.py", "c.py"}
        result = git_diff_to_diff_result(name_status, tracked)
        assert result.modified_files == ["a.py"]
        assert result.removed_files == ["b.py"]
        assert result.new_files == ["d.py"]
        assert result.unchanged_files == ["c.py"]

    def test_results_are_sorted(self) -> None:
        name_status = [("A", "z.py"), ("A", "a.py")]
        tracked: set[str] = set()
        result = git_diff_to_diff_result(name_status, tracked)
        assert result.new_files == ["a.py", "z.py"]

    def test_empty_diff_all_unchanged(self) -> None:
        name_status: list[tuple[str, str]] = []
        tracked = {"a.py", "b.py"}
        result = git_diff_to_diff_result(name_status, tracked)
        assert result.new_files == []
        assert result.modified_files == []
        assert result.removed_files == []
        assert sorted(result.unchanged_files) == ["a.py", "b.py"]

    def test_rename_treated_as_delete_plus_add(self) -> None:
        """R status (rename) becomes a removal + addition."""
        name_status = [("R", "old.py", "new.py")]
        tracked = {"old.py", "other.py"}
        result = git_diff_to_diff_result(name_status, tracked)
        assert result.removed_files == ["old.py"]
        assert result.new_files == ["new.py"]
        assert result.unchanged_files == ["other.py"]


# ---------------------------------------------------------------------------
# ProgressManager git state
# ---------------------------------------------------------------------------


class TestProgressGitState:
    """Storing and retrieving git state in progress.json."""

    def test_set_and_get_git_state(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data(["a.py"])
        map_hash = _write_map(guide_dir, map_data)
        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)

        mgr.set_git_state("abc123def456" * 3 + "abcd", "main")

        commit, branch = mgr.get_git_state()
        assert commit == "abc123def456" * 3 + "abcd"
        assert branch == "main"

    def test_git_state_persists_to_disk(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data(["a.py"])
        map_hash = _write_map(guide_dir, map_data)
        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        mgr.set_git_state("abc123", "main")

        mgr2 = ProgressManager(guide_dir)
        commit, branch = mgr2.get_git_state()
        assert commit == "abc123"
        assert branch == "main"

    def test_git_state_defaults_to_none(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data(["a.py"])
        map_hash = _write_map(guide_dir, map_data)
        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)

        commit, branch = mgr.get_git_state()
        assert commit is None
        assert branch is None

    def test_set_git_state_to_none_clears(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data(["a.py"])
        map_hash = _write_map(guide_dir, map_data)
        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        mgr.set_git_state("abc123", "main")
        mgr.set_git_state(None, None)

        commit, branch = mgr.get_git_state()
        assert commit is None
        assert branch is None


# ---------------------------------------------------------------------------
# refresh_progress_from_git — basic file status updates
# ---------------------------------------------------------------------------


class TestRefreshFromGitBasic:
    """Git-based refresh: modified, deleted, added, unchanged handling.

    The ``git_repo`` fixture provides a repo with a.py and b.py already
    committed. Tests use ``get_head_commit`` as the base commit.
    """

    def test_modified_files_marked_unread(self, git_repo: Path) -> None:
        guide_dir = git_repo / ".codebase-guide"
        commit = get_head_commit(git_repo)
        assert commit is not None

        files = ["a.py", "b.py"]
        map_data = _make_map_data(files)
        _setup_progress(
            guide_dir, map_data,
            git_commit=commit, git_branch="main",
            confirmed=["a.py", "b.py"],
        )

        (git_repo / "a.py").write_text("# modified\n")
        _git_commit(git_repo, "modify a.py")

        result = refresh_progress_from_git(guide_dir, git_repo)
        assert result is not None
        assert result.modified == 1

        mgr = ProgressManager(guide_dir)
        data = mgr.load()
        assert data["files"]["a.py"]["status"] == "unread"
        assert data["files"]["b.py"]["status"] == "confirmed"

    def test_deleted_files_removed(self, git_repo: Path) -> None:
        guide_dir = git_repo / ".codebase-guide"
        commit = get_head_commit(git_repo)
        assert commit is not None

        files = ["a.py", "b.py"]
        map_data = _make_map_data(files)
        _setup_progress(
            guide_dir, map_data,
            git_commit=commit, git_branch="main",
            confirmed=["a.py", "b.py"],
        )

        (git_repo / "b.py").unlink()
        _git_commit(git_repo, "delete b.py")

        result = refresh_progress_from_git(guide_dir, git_repo)
        assert result is not None
        assert result.removed == 1

        mgr = ProgressManager(guide_dir)
        data = mgr.load()
        assert "b.py" not in data["files"]

    def test_added_files_detected(self, git_repo: Path) -> None:
        guide_dir = git_repo / ".codebase-guide"
        commit = get_head_commit(git_repo)
        assert commit is not None

        files = ["a.py"]
        map_data = _make_map_data(files)
        _setup_progress(
            guide_dir, map_data,
            git_commit=commit, git_branch="main",
            confirmed=["a.py"],
        )

        (git_repo / "c.py").write_text("# new\n")
        _git_commit(git_repo, "add c.py")

        result = refresh_progress_from_git(guide_dir, git_repo)
        assert result is not None
        assert result.new == 1

    def test_unchanged_files_preserve_status(self, git_repo: Path) -> None:
        guide_dir = git_repo / ".codebase-guide"
        commit = get_head_commit(git_repo)
        assert commit is not None

        files = ["a.py", "b.py"]
        map_data = _make_map_data(files)
        _setup_progress(
            guide_dir, map_data,
            git_commit=commit, git_branch="main",
            confirmed=["a.py", "b.py"],
        )

        (git_repo / "a.py").write_text("# changed\n")
        _git_commit(git_repo, "modify a.py only")

        result = refresh_progress_from_git(guide_dir, git_repo)
        assert result is not None

        mgr = ProgressManager(guide_dir)
        data = mgr.load()
        assert data["files"]["b.py"]["status"] == "confirmed"
        assert data["files"]["b.py"]["summary"] == "Read b.py."

    def test_same_commit_no_changes(self, git_repo: Path) -> None:
        guide_dir = git_repo / ".codebase-guide"
        commit = get_head_commit(git_repo)
        assert commit is not None

        files = ["a.py"]
        map_data = _make_map_data(files)
        _setup_progress(
            guide_dir, map_data,
            git_commit=commit, git_branch="main",
            confirmed=["a.py"],
        )

        result = refresh_progress_from_git(guide_dir, git_repo)
        assert result is not None
        assert result.modified == 0
        assert result.new == 0
        assert result.removed == 0

        mgr = ProgressManager(guide_dir)
        data = mgr.load()
        assert data["files"]["a.py"]["status"] == "confirmed"


# ---------------------------------------------------------------------------
# refresh_progress_from_git — transitive invalidation
# ---------------------------------------------------------------------------


class TestRefreshFromGitTransitive:
    """Transitive invalidation via reverse dependency edges."""

    def test_direct_dependent_flagged(self, git_repo: Path) -> None:
        guide_dir = git_repo / ".codebase-guide"
        commit = get_head_commit(git_repo)
        assert commit is not None

        dep_graph = {
            "a.py": {"imports": [], "imported_by": ["b.py"]},
            "b.py": {"imports": ["a.py"], "imported_by": []},
        }
        files = ["a.py", "b.py"]
        map_data = _make_map_data(files, dep_graph=dep_graph)
        _setup_progress(
            guide_dir, map_data,
            git_commit=commit, git_branch="main",
            confirmed=["a.py", "b.py"],
        )

        (git_repo / "a.py").write_text("# changed\n")
        _git_commit(git_repo, "modify a.py")

        result = refresh_progress_from_git(guide_dir, git_repo)
        assert result is not None
        assert result.transitively_invalidated == 1

        mgr = ProgressManager(guide_dir)
        data = mgr.load()
        assert data["files"]["b.py"]["status"] == "flagged"
        assert "a.py" in data["files"]["b.py"]["note"]

    def test_transitive_chain_flagged(self, git_repo: Path) -> None:
        """a.py -> b.py -> c.py: modifying a.py flags both b and c."""
        guide_dir = git_repo / ".codebase-guide"
        commit = get_head_commit(git_repo)
        assert commit is not None
        # c.py doesn't exist in fixture — add it
        (git_repo / "c.py").write_text("# c\n")
        commit = _git_commit(git_repo, "add c.py")

        dep_graph = {
            "a.py": {"imports": [], "imported_by": ["b.py"]},
            "b.py": {"imports": ["a.py"], "imported_by": ["c.py"]},
            "c.py": {"imports": ["b.py"], "imported_by": []},
        }
        files = ["a.py", "b.py", "c.py"]
        map_data = _make_map_data(files, dep_graph=dep_graph)
        _setup_progress(
            guide_dir, map_data,
            git_commit=commit, git_branch="main",
            confirmed=["a.py", "b.py", "c.py"],
        )

        (git_repo / "a.py").write_text("# changed\n")
        _git_commit(git_repo, "modify a.py")

        result = refresh_progress_from_git(guide_dir, git_repo)
        assert result is not None
        assert result.transitively_invalidated == 2

        mgr = ProgressManager(guide_dir)
        data = mgr.load()
        assert data["files"]["b.py"]["status"] == "flagged"
        assert data["files"]["c.py"]["status"] == "flagged"


# ---------------------------------------------------------------------------
# refresh_progress_from_git — git state updates
# ---------------------------------------------------------------------------


class TestRefreshFromGitStateUpdates:
    """Git state in progress.json after refresh."""

    def test_updates_stored_git_commit(self, git_repo: Path) -> None:
        guide_dir = git_repo / ".codebase-guide"
        old_commit = get_head_commit(git_repo)
        assert old_commit is not None

        files = ["a.py"]
        map_data = _make_map_data(files)
        _setup_progress(
            guide_dir, map_data,
            git_commit=old_commit, git_branch="main",
        )

        (git_repo / "a.py").write_text("# changed\n")
        new_commit = _git_commit(git_repo, "modify")

        refresh_progress_from_git(guide_dir, git_repo)

        mgr = ProgressManager(guide_dir)
        commit, _branch = mgr.get_git_state()
        assert commit == new_commit

    def test_updates_stats_after_refresh(self, git_repo: Path) -> None:
        guide_dir = git_repo / ".codebase-guide"
        commit = get_head_commit(git_repo)
        assert commit is not None

        files = ["a.py", "b.py"]  # already in fixture
        map_data = _make_map_data(files)
        _setup_progress(
            guide_dir, map_data,
            git_commit=commit, git_branch="main",
            confirmed=["a.py", "b.py"],
        )

        (git_repo / "a.py").write_text("# changed\n")
        _git_commit(git_repo, "modify a.py")

        refresh_progress_from_git(guide_dir, git_repo)

        mgr = ProgressManager(guide_dir)
        data = mgr.load()
        assert data["stats"]["confirmed"] == 1  # b.py
        assert data["stats"]["unread"] == 1  # a.py reset


# ---------------------------------------------------------------------------
# refresh_progress_from_git — graceful fallbacks
# ---------------------------------------------------------------------------


class TestRefreshFromGitFallbacks:
    """Graceful fallback when git-based refresh isn't possible."""

    def test_returns_none_without_stored_commit(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py"]
        map_data = _make_map_data(files)
        _setup_progress(guide_dir, map_data)

        result = refresh_progress_from_git(guide_dir, tmp_path)
        assert result is None

    def test_returns_none_for_non_git_repo(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py"]
        map_data = _make_map_data(files)
        _setup_progress(
            guide_dir, map_data,
            git_commit="abc123", git_branch="main",
        )

        result = refresh_progress_from_git(guide_dir, tmp_path)
        assert result is None

    def test_returns_none_when_stored_commit_missing(
        self, git_repo: Path,
    ) -> None:
        guide_dir = git_repo / ".codebase-guide"

        files = ["a.py"]
        map_data = _make_map_data(files)
        _setup_progress(
            guide_dir, map_data,
            git_commit="0" * 40, git_branch="main",
        )

        result = refresh_progress_from_git(guide_dir, git_repo)
        assert result is None

    def test_returns_none_when_no_map_json(self, git_repo: Path) -> None:
        """If map.json is missing, can't get dep graph for invalidation."""
        guide_dir = git_repo / ".codebase-guide"
        commit = get_head_commit(git_repo)
        assert commit is not None

        files = ["a.py"]
        map_data = _make_map_data(files)
        map_hash = hashlib.sha256(
            json.dumps(map_data).encode(),
        ).hexdigest()
        guide_dir.mkdir(parents=True, exist_ok=True)
        # Create progress without map.json
        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        mgr.set_git_state(commit, "main")

        (git_repo / "a.py").write_text("# changed content\n")
        _git_commit(git_repo, "modify a.py")

        result = refresh_progress_from_git(guide_dir, git_repo)
        assert result is None


# ---------------------------------------------------------------------------
# _filter_guide_dir_entries
# ---------------------------------------------------------------------------


class TestFilterGuideDirEntries:
    """Filtering .codebase-guide paths from git diff entries."""

    def test_filters_entries_under_guide_dir(self, tmp_path: Path) -> None:
        guide = tmp_path / ".codebase-guide"
        entries: list[tuple[str, ...]] = [
            ("A", ".codebase-guide/map.json"),
            ("M", "a.py"),
            ("A", ".codebase-guide/progress.json"),
        ]
        result = _filter_guide_dir_entries(entries, guide, tmp_path)
        assert result == [("M", "a.py")]

    def test_preserves_source_entries(self, tmp_path: Path) -> None:
        guide = tmp_path / ".codebase-guide"
        entries: list[tuple[str, ...]] = [
            ("M", "src/a.py"),
            ("A", "src/b.py"),
        ]
        result = _filter_guide_dir_entries(entries, guide, tmp_path)
        assert result == entries

    def test_guide_dir_outside_repo_returns_all(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        guide = tmp_path / "other" / ".codebase-guide"
        entries: list[tuple[str, ...]] = [
            ("M", "a.py"),
            ("A", ".codebase-guide/map.json"),
        ]
        result = _filter_guide_dir_entries(entries, guide, repo)
        assert result == entries

    def test_empty_entries(self, tmp_path: Path) -> None:
        guide = tmp_path / ".codebase-guide"
        result = _filter_guide_dir_entries([], guide, tmp_path)
        assert result == []


class TestRefreshFromGitResetsPointer:
    """Git-based refresh resets next_unread_index (BED-97)."""

    def test_pointer_reset_to_zero_after_git_refresh(
        self, git_repo: Path,
    ) -> None:
        """After git-based refresh invalidates files, pointer resets."""
        guide_dir = git_repo / ".codebase-guide"
        commit = get_head_commit(git_repo)
        assert commit is not None

        files = ["a.py", "b.py"]
        map_data = _make_map_data(files)
        _setup_progress(
            guide_dir, map_data,
            git_commit=commit, git_branch="main",
            confirmed=["a.py", "b.py"],
        )

        # Advance pointer past both files
        mgr = ProgressManager(guide_dir)
        mgr.advance_pointer(files)
        data = mgr.load()
        assert data["next_unread_index"] == 2

        # Modify a.py and commit
        (git_repo / "a.py").write_text("# modified\n")
        _git_commit(git_repo, "modify a.py")

        result = refresh_progress_from_git(guide_dir, git_repo)
        assert result is not None

        data = mgr.load()
        assert data["next_unread_index"] == 0
