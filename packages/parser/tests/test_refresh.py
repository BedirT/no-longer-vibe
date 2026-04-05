"""Tests for /read-refresh — incremental re-parse with transitive invalidation (BED-78).

Covers: hash diffing, new/modified/removed/unchanged detection, transitive
invalidation via reverse dependency edges, progress.json updates, and summary
generation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from nlv.progress import FileStatus, ProgressManager
from nlv.refresh import diff_content_hashes, refresh_progress

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    map_path = guide_dir / "map.json"
    content = json.dumps(map_data, indent=2)
    map_path.write_text(content)
    return hashlib.sha256(content.encode()).hexdigest()


def _setup_progress(
    guide_dir: Path,
    map_data: dict[str, Any],
    *,
    confirmed: list[str] | None = None,
    flagged: list[str] | None = None,
    skimmed: list[str] | None = None,
) -> str:
    """Create progress.json with some files already read."""
    map_hash = _write_map(guide_dir, map_data)
    mgr = ProgressManager(guide_dir)
    mgr.create(map_data, map_hash)

    for path in confirmed or []:
        mgr.update_file(path, status=FileStatus.CONFIRMED, summary=f"Read {path}.")
    for path in flagged or []:
        mgr.update_file(path, status=FileStatus.FLAGGED, note=f"Flag {path}.")
    for path in skimmed or []:
        mgr.update_file(path, status=FileStatus.SKIMMED)

    return map_hash


# ---------------------------------------------------------------------------
# diff_content_hashes
# ---------------------------------------------------------------------------


class TestDiffContentHashes:
    """Diffing old vs new content hashes."""

    def test_no_changes(self) -> None:
        old = {"a.py": "abcd1234", "b.py": "efgh5678"}
        new = {"a.py": "abcd1234", "b.py": "efgh5678"}
        result = diff_content_hashes(old, new)
        assert result.new_files == []
        assert result.modified_files == []
        assert result.removed_files == []
        assert result.unchanged_files == ["a.py", "b.py"]

    def test_new_file_detected(self) -> None:
        old = {"a.py": "abcd1234"}
        new = {"a.py": "abcd1234", "b.py": "efgh5678"}
        result = diff_content_hashes(old, new)
        assert result.new_files == ["b.py"]
        assert result.unchanged_files == ["a.py"]

    def test_removed_file_detected(self) -> None:
        old = {"a.py": "abcd1234", "b.py": "efgh5678"}
        new = {"a.py": "abcd1234"}
        result = diff_content_hashes(old, new)
        assert result.removed_files == ["b.py"]
        assert result.unchanged_files == ["a.py"]

    def test_modified_file_detected(self) -> None:
        old = {"a.py": "abcd1234"}
        new = {"a.py": "xxxx9999"}
        result = diff_content_hashes(old, new)
        assert result.modified_files == ["a.py"]
        assert result.unchanged_files == []

    def test_all_categories_together(self) -> None:
        old = {"a.py": "aaaa1111", "b.py": "bbbb2222", "c.py": "cccc3333"}
        new = {"a.py": "aaaa1111", "b.py": "xxxx9999", "d.py": "dddd4444"}
        result = diff_content_hashes(old, new)
        assert result.unchanged_files == ["a.py"]
        assert result.modified_files == ["b.py"]
        assert result.removed_files == ["c.py"]
        assert result.new_files == ["d.py"]

    def test_empty_old_all_new(self) -> None:
        old: dict[str, str] = {}
        new = {"a.py": "aaaa1111", "b.py": "bbbb2222"}
        result = diff_content_hashes(old, new)
        assert sorted(result.new_files) == ["a.py", "b.py"]
        assert result.modified_files == []
        assert result.removed_files == []

    def test_empty_new_all_removed(self) -> None:
        old = {"a.py": "aaaa1111", "b.py": "bbbb2222"}
        new: dict[str, str] = {}
        result = diff_content_hashes(old, new)
        assert sorted(result.removed_files) == ["a.py", "b.py"]
        assert result.new_files == []

    def test_results_are_sorted(self) -> None:
        old = {"z.py": "zzzz0000", "a.py": "aaaa1111"}
        new = {"z.py": "xxxx9999", "a.py": "yyyy8888"}
        result = diff_content_hashes(old, new)
        assert result.modified_files == ["a.py", "z.py"]


# ---------------------------------------------------------------------------
# refresh_progress — basic file status updates
# ---------------------------------------------------------------------------


class TestRefreshProgressBasic:
    """Basic refresh: new, modified, removed, unchanged file handling."""

    def test_unchanged_files_preserve_status(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py"]
        old_map = _make_map_data(files)
        _setup_progress(guide_dir, old_map, confirmed=["a.py"])

        # Same hashes — nothing changed
        new_map = _make_map_data(files)
        new_hash = _write_map(guide_dir, new_map)

        result = refresh_progress(
            guide_dir, new_map, new_hash,
            old_content_hashes=old_map["content_hashes"],
        )

        mgr = ProgressManager(guide_dir)
        data = mgr.load()
        assert data["files"]["a.py"]["status"] == "confirmed"
        assert result.unchanged == 2

    def test_modified_files_reset_to_unread(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py"]
        old_map = _make_map_data(files)
        _setup_progress(guide_dir, old_map, confirmed=["a.py", "b.py"])

        # Change a.py hash
        new_hashes = dict(old_map["content_hashes"])
        new_hashes["a.py"] = "modified1"
        new_map = _make_map_data(files, hashes=new_hashes)
        new_hash = _write_map(guide_dir, new_map)

        result = refresh_progress(
            guide_dir, new_map, new_hash,
            old_content_hashes=old_map["content_hashes"],
        )

        mgr = ProgressManager(guide_dir)
        data = mgr.load()
        assert data["files"]["a.py"]["status"] == "unread"
        assert data["files"]["b.py"]["status"] == "confirmed"
        assert result.modified == 1

    def test_new_files_added_as_unread(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        old_files = ["a.py"]
        old_map = _make_map_data(old_files)
        _setup_progress(guide_dir, old_map, confirmed=["a.py"])

        new_files = ["a.py", "b.py"]
        new_map = _make_map_data(new_files)
        new_hash = _write_map(guide_dir, new_map)

        result = refresh_progress(
            guide_dir, new_map, new_hash,
            old_content_hashes=old_map["content_hashes"],
        )

        mgr = ProgressManager(guide_dir)
        data = mgr.load()
        assert "b.py" in data["files"]
        assert data["files"]["b.py"]["status"] == "unread"
        assert result.new == 1

    def test_removed_files_deleted_from_progress(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        old_files = ["a.py", "b.py"]
        old_map = _make_map_data(old_files)
        _setup_progress(guide_dir, old_map, confirmed=["a.py", "b.py"])

        new_files = ["a.py"]
        new_map = _make_map_data(new_files)
        new_hash = _write_map(guide_dir, new_map)

        result = refresh_progress(
            guide_dir, new_map, new_hash,
            old_content_hashes=old_map["content_hashes"],
        )

        mgr = ProgressManager(guide_dir)
        data = mgr.load()
        assert "b.py" not in data["files"]
        assert result.removed == 1

    def test_updates_map_hash(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py"]
        old_map = _make_map_data(files)
        old_hash = _setup_progress(guide_dir, old_map)

        new_hashes = {"a.py": "modified1"}
        new_map = _make_map_data(files, hashes=new_hashes)
        new_hash = _write_map(guide_dir, new_map)
        assert new_hash != old_hash

        refresh_progress(
            guide_dir, new_map, new_hash,
            old_content_hashes=old_map["content_hashes"],
        )

        mgr = ProgressManager(guide_dir)
        data = mgr.load()
        assert data["map_hash"] == new_hash

    def test_stats_recalculated_after_refresh(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py"]
        old_map = _make_map_data(files)
        _setup_progress(guide_dir, old_map, confirmed=["a.py", "b.py"])

        # Modify a.py, add c.py
        new_hashes = dict(old_map["content_hashes"])
        new_hashes["a.py"] = "modified1"
        new_hashes["c.py"] = "cccc3333"
        new_files = ["a.py", "b.py", "c.py"]
        new_map = _make_map_data(new_files, hashes=new_hashes)
        new_hash = _write_map(guide_dir, new_map)

        refresh_progress(
            guide_dir, new_map, new_hash,
            old_content_hashes=old_map["content_hashes"],
        )

        mgr = ProgressManager(guide_dir)
        data = mgr.load()
        assert data["stats"]["total"] == 3
        assert data["stats"]["confirmed"] == 1  # b.py
        assert data["stats"]["unread"] == 2  # a.py (modified) + c.py (new)


# ---------------------------------------------------------------------------
# refresh_progress — transitive invalidation
# ---------------------------------------------------------------------------


class TestTransitiveInvalidation:
    """Transitive invalidation via reverse dependency edges."""

    def _make_chain_graph(self) -> dict[str, dict[str, list[str]]]:
        """a.py -> b.py -> c.py (c depends on b, b depends on a)."""
        return {
            "a.py": {"imports": [], "imported_by": ["b.py"]},
            "b.py": {"imports": ["a.py"], "imported_by": ["c.py"]},
            "c.py": {"imports": ["b.py"], "imported_by": []},
        }

    def test_direct_dependents_marked_stale(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py", "c.py"]
        dep_graph = self._make_chain_graph()
        old_map = _make_map_data(files, dep_graph=dep_graph)
        _setup_progress(
            guide_dir, old_map,
            confirmed=["a.py", "b.py", "c.py"],
        )

        # Modify a.py — b.py depends on it
        new_hashes = dict(old_map["content_hashes"])
        new_hashes["a.py"] = "modified1"
        new_map = _make_map_data(files, hashes=new_hashes, dep_graph=dep_graph)
        new_hash = _write_map(guide_dir, new_map)

        result = refresh_progress(
            guide_dir, new_map, new_hash,
            old_content_hashes=old_map["content_hashes"],
        )

        mgr = ProgressManager(guide_dir)
        data = mgr.load()

        # b.py should be flagged with a stale note
        assert data["files"]["b.py"]["status"] == "flagged"
        assert "a.py" in data["files"]["b.py"]["note"]
        assert result.transitively_invalidated == 2  # b.py and c.py

    def test_transitive_dependents_marked_stale(self, tmp_path: Path) -> None:
        """c.py depends on b.py which depends on a.py — all get invalidated."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py", "c.py"]
        dep_graph = self._make_chain_graph()
        old_map = _make_map_data(files, dep_graph=dep_graph)
        _setup_progress(
            guide_dir, old_map,
            confirmed=["a.py", "b.py", "c.py"],
        )

        new_hashes = dict(old_map["content_hashes"])
        new_hashes["a.py"] = "modified1"
        new_map = _make_map_data(files, hashes=new_hashes, dep_graph=dep_graph)
        new_hash = _write_map(guide_dir, new_map)

        refresh_progress(
            guide_dir, new_map, new_hash,
            old_content_hashes=old_map["content_hashes"],
        )

        mgr = ProgressManager(guide_dir)
        data = mgr.load()

        # c.py is a transitive dependent
        assert data["files"]["c.py"]["status"] == "flagged"
        assert "dependency changed" in data["files"]["c.py"]["note"].lower()

    def test_unread_files_not_invalidated(self, tmp_path: Path) -> None:
        """Files already unread should not be flagged as stale."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py"]
        dep_graph = {
            "a.py": {"imports": [], "imported_by": ["b.py"]},
            "b.py": {"imports": ["a.py"], "imported_by": []},
        }
        old_map = _make_map_data(files, dep_graph=dep_graph)
        # b.py is already unread
        _setup_progress(guide_dir, old_map, confirmed=["a.py"])

        new_hashes = dict(old_map["content_hashes"])
        new_hashes["a.py"] = "modified1"
        new_map = _make_map_data(files, hashes=new_hashes, dep_graph=dep_graph)
        new_hash = _write_map(guide_dir, new_map)

        result = refresh_progress(
            guide_dir, new_map, new_hash,
            old_content_hashes=old_map["content_hashes"],
        )

        mgr = ProgressManager(guide_dir)
        data = mgr.load()

        # b.py stays unread, not flagged — already needed to be read
        assert data["files"]["b.py"]["status"] == "unread"
        assert result.transitively_invalidated == 0

    def test_modified_files_not_double_counted_as_stale(
        self, tmp_path: Path,
    ) -> None:
        """A file that is itself modified should not also count as stale."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py"]
        dep_graph = {
            "a.py": {"imports": [], "imported_by": ["b.py"]},
            "b.py": {"imports": ["a.py"], "imported_by": []},
        }
        old_map = _make_map_data(files, dep_graph=dep_graph)
        _setup_progress(guide_dir, old_map, confirmed=["a.py", "b.py"])

        # Both a.py and b.py are modified
        new_hashes = {"a.py": "modified1", "b.py": "modified2"}
        new_map = _make_map_data(files, hashes=new_hashes, dep_graph=dep_graph)
        new_hash = _write_map(guide_dir, new_map)

        result = refresh_progress(
            guide_dir, new_map, new_hash,
            old_content_hashes=old_map["content_hashes"],
        )

        mgr = ProgressManager(guide_dir)
        data = mgr.load()

        # b.py is already reset to unread via modification, not stale
        assert data["files"]["b.py"]["status"] == "unread"
        assert result.modified == 2
        assert result.transitively_invalidated == 0

    def test_diamond_dependency_counts_once(self, tmp_path: Path) -> None:
        """Diamond: a.py <- b.py, a.py <- c.py, b.py <- d.py, c.py <- d.py."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py", "c.py", "d.py"]
        dep_graph = {
            "a.py": {"imports": [], "imported_by": ["b.py", "c.py"]},
            "b.py": {"imports": ["a.py"], "imported_by": ["d.py"]},
            "c.py": {"imports": ["a.py"], "imported_by": ["d.py"]},
            "d.py": {"imports": ["b.py", "c.py"], "imported_by": []},
        }
        old_map = _make_map_data(files, dep_graph=dep_graph)
        _setup_progress(
            guide_dir, old_map,
            confirmed=["a.py", "b.py", "c.py", "d.py"],
        )

        new_hashes = dict(old_map["content_hashes"])
        new_hashes["a.py"] = "modified1"
        new_map = _make_map_data(files, hashes=new_hashes, dep_graph=dep_graph)
        new_hash = _write_map(guide_dir, new_map)

        result = refresh_progress(
            guide_dir, new_map, new_hash,
            old_content_hashes=old_map["content_hashes"],
        )

        # b.py, c.py, d.py all transitively invalidated
        assert result.transitively_invalidated == 3

    def test_stale_note_includes_changed_dependency(
        self, tmp_path: Path,
    ) -> None:
        """The note on a stale file mentions which dependency changed."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py"]
        dep_graph = {
            "a.py": {"imports": [], "imported_by": ["b.py"]},
            "b.py": {"imports": ["a.py"], "imported_by": []},
        }
        old_map = _make_map_data(files, dep_graph=dep_graph)
        _setup_progress(guide_dir, old_map, confirmed=["a.py", "b.py"])

        new_hashes = dict(old_map["content_hashes"])
        new_hashes["a.py"] = "modified1"
        new_map = _make_map_data(files, hashes=new_hashes, dep_graph=dep_graph)
        new_hash = _write_map(guide_dir, new_map)

        refresh_progress(
            guide_dir, new_map, new_hash,
            old_content_hashes=old_map["content_hashes"],
        )

        mgr = ProgressManager(guide_dir)
        data = mgr.load()
        assert "a.py" in data["files"]["b.py"]["note"]


# ---------------------------------------------------------------------------
# refresh_progress — result summary
# ---------------------------------------------------------------------------


class TestRefreshResult:
    """RefreshResult summary values."""

    def test_no_changes_result(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py"]
        old_map = _make_map_data(files)
        _setup_progress(guide_dir, old_map)

        new_map = _make_map_data(files)
        new_hash = _write_map(guide_dir, new_map)

        result = refresh_progress(
            guide_dir, new_map, new_hash,
            old_content_hashes=old_map["content_hashes"],
        )

        assert result.new == 0
        assert result.modified == 0
        assert result.removed == 0
        assert result.unchanged == 1
        assert result.transitively_invalidated == 0

    def test_full_result(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py", "c.py"]
        dep_graph = {
            "a.py": {"imports": [], "imported_by": ["c.py"]},
            "b.py": {"imports": [], "imported_by": []},
            "c.py": {"imports": ["a.py"], "imported_by": []},
        }
        old_map = _make_map_data(files, dep_graph=dep_graph)
        _setup_progress(
            guide_dir, old_map,
            confirmed=["a.py", "b.py", "c.py"],
        )

        # Modify a.py, remove b.py, add d.py
        new_hashes = dict(old_map["content_hashes"])
        new_hashes["a.py"] = "modified1"
        del new_hashes["b.py"]
        new_hashes["d.py"] = "dddd4444"
        new_files = ["a.py", "c.py", "d.py"]
        new_dep_graph = {
            "a.py": {"imports": [], "imported_by": ["c.py"]},
            "c.py": {"imports": ["a.py"], "imported_by": []},
            "d.py": {"imports": [], "imported_by": []},
        }
        new_map = _make_map_data(
            new_files, hashes=new_hashes, dep_graph=new_dep_graph,
        )
        new_hash = _write_map(guide_dir, new_map)

        result = refresh_progress(
            guide_dir, new_map, new_hash,
            old_content_hashes=old_map["content_hashes"],
        )

        assert result.new == 1  # d.py
        assert result.modified == 1  # a.py
        assert result.removed == 1  # b.py
        assert result.unchanged == 1  # c.py (was unchanged)
        assert result.transitively_invalidated == 1  # c.py (depends on a.py)


# ---------------------------------------------------------------------------
# refresh_progress — edge cases
# ---------------------------------------------------------------------------


class TestRefreshEdgeCases:
    """Edge cases for refresh logic."""

    def test_preserves_existing_summaries_on_unchanged(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py"]
        old_map = _make_map_data(files)
        _setup_progress(guide_dir, old_map, confirmed=["a.py"])

        new_map = _make_map_data(files)
        new_hash = _write_map(guide_dir, new_map)

        refresh_progress(
            guide_dir, new_map, new_hash,
            old_content_hashes=old_map["content_hashes"],
        )

        mgr = ProgressManager(guide_dir)
        data = mgr.load()
        assert data["files"]["a.py"]["summary"] == "Read a.py."

    def test_preserves_existing_notes_on_unchanged_flagged(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py"]
        old_map = _make_map_data(files)
        _setup_progress(guide_dir, old_map, flagged=["a.py"])

        new_map = _make_map_data(files)
        new_hash = _write_map(guide_dir, new_map)

        refresh_progress(
            guide_dir, new_map, new_hash,
            old_content_hashes=old_map["content_hashes"],
        )

        mgr = ProgressManager(guide_dir)
        data = mgr.load()
        assert data["files"]["a.py"]["note"] == "Flag a.py."

    def test_no_progress_file_raises(self, tmp_path: Path) -> None:
        """refresh_progress needs existing progress.json."""
        guide_dir = tmp_path / ".codebase-guide"
        guide_dir.mkdir(parents=True)
        new_map = _make_map_data(["a.py"])
        new_hash = _write_map(guide_dir, new_map)

        with pytest.raises(FileNotFoundError):
            refresh_progress(
                guide_dir, new_map, new_hash,
                old_content_hashes={},
            )

    def test_preserves_session_metadata(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py"]
        old_map = _make_map_data(files)
        _setup_progress(guide_dir, old_map)

        mgr = ProgressManager(guide_dir)
        data_before = mgr.load()
        started_at = data_before["started_at"]
        sessions = data_before["sessions"]

        new_map = _make_map_data(files)
        new_hash = _write_map(guide_dir, new_map)

        refresh_progress(
            guide_dir, new_map, new_hash,
            old_content_hashes=old_map["content_hashes"],
        )

        data_after = mgr.load()
        assert data_after["started_at"] == started_at
        assert data_after["sessions"] == sessions

    def test_stale_flagged_file_gets_updated_note(
        self, tmp_path: Path,
    ) -> None:
        """A file already flagged gets its note appended with stale info."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py"]
        dep_graph = {
            "a.py": {"imports": [], "imported_by": ["b.py"]},
            "b.py": {"imports": ["a.py"], "imported_by": []},
        }
        old_map = _make_map_data(files, dep_graph=dep_graph)
        _setup_progress(guide_dir, old_map, flagged=["b.py"])
        # Manually set a.py to confirmed
        mgr = ProgressManager(guide_dir)
        mgr.load()
        mgr.update_file(
            "a.py", status=FileStatus.CONFIRMED, summary="Read a.py.",
        )

        new_hashes = dict(old_map["content_hashes"])
        new_hashes["a.py"] = "modified1"
        new_map = _make_map_data(files, hashes=new_hashes, dep_graph=dep_graph)
        new_hash = _write_map(guide_dir, new_map)

        refresh_progress(
            guide_dir, new_map, new_hash,
            old_content_hashes=old_map["content_hashes"],
        )

        data = mgr.load()
        # b.py was already flagged, should still be flagged with stale note
        assert data["files"]["b.py"]["status"] == "flagged"
        assert "dependency changed" in data["files"]["b.py"]["note"].lower()
