"""Tests for progress.json management (BED-73).

Covers: create, load, update, stats, session tracking, map_hash validation,
atomic writes, and edge cases.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import pytest

from nlv.progress import (
    FileStatus,
    ProgressManager,
    StaleMapError,
)


def _make_map_data(files: list[str] | None = None) -> dict[str, Any]:
    """Build a minimal map.json structure for testing."""
    if files is None:
        files = ["src/config.py", "src/models.py", "src/app.py"]
    return {
        "version": "1.0.0",
        "repo_root": "/tmp/test-repo",
        "generated_at": "2026-04-05T10:00:00Z",
        "content_hashes": {
            f: hashlib.sha256(f.encode()).hexdigest()[:8]
            for f in files
        },
        "total_files": len(files),
        "layers": {
            "foundation": {"description": "No deps", "files": files[:1]},
            "core": {"description": "Depends on foundation", "files": files[1:]},
        },
        "reading_order": [
            {"index": i, "path": f, "layer": "foundation" if i == 0 else "core"}
            for i, f in enumerate(files)
        ],
        "dependency_graph": {f: {"imports": [], "imported_by": []} for f in files},
    }


def _write_map(guide_dir: Path, map_data: dict[str, Any]) -> str:
    """Write map.json and return its content hash."""
    guide_dir.mkdir(parents=True, exist_ok=True)
    map_path = guide_dir / "map.json"
    content = json.dumps(map_data, indent=2)
    map_path.write_text(content)
    return hashlib.sha256(content.encode()).hexdigest()


class TestCreate:
    """Creating a new progress.json from map data."""

    def test_create_initializes_progress_file(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data()
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)

        progress_path = guide_dir / "progress.json"
        assert progress_path.exists()

    def test_create_sets_version(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data()
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        data = mgr.load()

        assert data["version"] == "1.0.0"

    def test_create_stores_map_hash(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data()
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        data = mgr.load()

        assert data["map_hash"] == map_hash

    def test_create_sets_timestamps(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data()
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        data = mgr.load()

        assert "started_at" in data
        assert "last_session" in data
        assert data["started_at"] == data["last_session"]

    def test_create_initializes_sessions_to_one(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data()
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        data = mgr.load()

        assert data["sessions"] == 1

    def test_create_marks_all_files_unread(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/a.py", "src/b.py", "src/c.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        data = mgr.load()

        for f in files:
            assert f in data["files"]
            assert data["files"][f]["status"] == "unread"
            assert data["files"][f]["read_at"] is None
            assert data["files"][f]["note"] is None
            assert data["files"][f]["summary"] is None

    def test_create_computes_initial_stats(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py", "c.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        data = mgr.load()

        assert data["stats"]["total"] == 3
        assert data["stats"]["confirmed"] == 0
        assert data["stats"]["flagged"] == 0
        assert data["stats"]["skimmed"] == 0
        assert data["stats"]["unread"] == 3

    def test_create_creates_guide_directory_if_missing(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        # Don't create guide_dir — only write map via helper
        map_data = _make_map_data()
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)

        assert (guide_dir / "progress.json").exists()


class TestLoad:
    """Loading progress.json from disk."""

    def test_load_returns_progress_data(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data()
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        data = mgr.load()

        assert data["version"] == "1.0.0"
        assert isinstance(data["files"], dict)

    def test_load_raises_when_file_missing(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        guide_dir.mkdir(parents=True)

        mgr = ProgressManager(guide_dir)
        with pytest.raises(FileNotFoundError):
            mgr.load()

    def test_load_raises_on_invalid_json(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        guide_dir.mkdir(parents=True)
        (guide_dir / "progress.json").write_text("not json")

        mgr = ProgressManager(guide_dir)
        with pytest.raises(json.JSONDecodeError):
            mgr.load()


class TestUpdateFile:
    """Updating individual file status entries."""

    def test_update_to_confirmed(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data(["src/a.py"])
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        mgr.update_file(
            "src/a.py", status=FileStatus.CONFIRMED,
            summary="Config loader.",
        )

        data = mgr.load()
        assert data["files"]["src/a.py"]["status"] == "confirmed"
        assert data["files"]["src/a.py"]["summary"] == "Config loader."
        assert data["files"]["src/a.py"]["read_at"] is not None

    def test_update_to_flagged_with_note(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data(["src/a.py"])
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        mgr.update_file(
            "src/a.py",
            status=FileStatus.FLAGGED,
            note="Dual token store seems unnecessary",
            summary="Auth middleware with JWT.",
        )

        data = mgr.load()
        assert data["files"]["src/a.py"]["status"] == "flagged"
        assert data["files"]["src/a.py"]["note"] == "Dual token store seems unnecessary"

    def test_update_to_skimmed(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data(["src/a.py"])
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        mgr.update_file("src/a.py", status=FileStatus.SKIMMED)

        data = mgr.load()
        assert data["files"]["src/a.py"]["status"] == "skimmed"

    def test_update_recalculates_stats(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py", "c.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        mgr.update_file("a.py", status=FileStatus.CONFIRMED, summary="Done.")
        mgr.update_file("b.py", status=FileStatus.FLAGGED, note="Check later.")

        data = mgr.load()
        assert data["stats"]["confirmed"] == 1
        assert data["stats"]["flagged"] == 1
        assert data["stats"]["unread"] == 1

    def test_update_unknown_file_raises(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data(["src/a.py"])
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)

        with pytest.raises(KeyError):
            mgr.update_file("nonexistent.py", status=FileStatus.CONFIRMED)

    def test_update_persists_to_disk(self, tmp_path: Path) -> None:
        """Changes survive a fresh ProgressManager instance."""
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data(["src/a.py"])
        map_hash = _write_map(guide_dir, map_data)

        mgr1 = ProgressManager(guide_dir)
        mgr1.create(map_data, map_hash)
        mgr1.update_file("src/a.py", status=FileStatus.CONFIRMED, summary="Done.")

        mgr2 = ProgressManager(guide_dir)
        data = mgr2.load()
        assert data["files"]["src/a.py"]["status"] == "confirmed"


class TestStats:
    """Computing reading statistics."""

    def test_compute_stats_all_unread(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)

        stats = mgr.compute_stats()
        assert stats == {
            "total": 2, "confirmed": 0, "flagged": 0,
            "skimmed": 0, "unread": 2,
        }

    def test_compute_stats_mixed(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py", "c.py", "d.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        mgr.update_file("a.py", status=FileStatus.CONFIRMED, summary="Ok.")
        mgr.update_file("b.py", status=FileStatus.FLAGGED, note="Check.")
        mgr.update_file("c.py", status=FileStatus.SKIMMED)

        stats = mgr.compute_stats()
        assert stats == {
            "total": 4, "confirmed": 1, "flagged": 1,
            "skimmed": 1, "unread": 1,
        }

    def test_compute_stats_requires_load(self, tmp_path: Path) -> None:
        """compute_stats works on a freshly loaded manager."""
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data(["a.py"])
        map_hash = _write_map(guide_dir, map_data)

        mgr1 = ProgressManager(guide_dir)
        mgr1.create(map_data, map_hash)
        mgr1.update_file("a.py", status=FileStatus.CONFIRMED, summary="Ok.")

        mgr2 = ProgressManager(guide_dir)
        mgr2.load()
        stats = mgr2.compute_stats()
        assert stats["confirmed"] == 1


class TestSessionTracking:
    """Tracking reading session count and timestamps."""

    def test_start_session_increments_count(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data()
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        assert mgr.load()["sessions"] == 1

        mgr.start_session()
        assert mgr.load()["sessions"] == 2

    def test_start_session_updates_last_session(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data()
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        data_before = mgr.load()
        original_last = data_before["last_session"]

        # Small sleep to ensure timestamp differs
        time.sleep(0.01)
        mgr.start_session()
        data_after = mgr.load()

        assert data_after["last_session"] >= original_last

    def test_start_session_preserves_started_at(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data()
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        original_started = mgr.load()["started_at"]

        mgr.start_session()
        assert mgr.load()["started_at"] == original_started


class TestMapHashValidation:
    """Validating that progress matches the current map."""

    def test_validate_matching_hash_returns_true(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data()
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        mgr.load()

        assert mgr.validate_map_hash(map_hash) is True

    def test_validate_different_hash_returns_false(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data()
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        mgr.load()

        assert mgr.validate_map_hash("different-hash") is False

    def test_validate_raises_when_strict(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data()
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        mgr.load()

        with pytest.raises(StaleMapError):
            mgr.validate_map_hash("different-hash", strict=True)


class TestAtomicWrites:
    """Progress updates must not leave partial files on crash."""

    def test_progress_file_is_valid_json_after_update(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data(["a.py"])
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        mgr.update_file("a.py", status=FileStatus.CONFIRMED, summary="Ok.")

        # Directly read and parse the file — must be valid JSON
        raw = (guide_dir / "progress.json").read_text()
        data = json.loads(raw)
        assert data["files"]["a.py"]["status"] == "confirmed"

    def test_no_temp_files_left_after_write(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data(["a.py"])
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        mgr.update_file("a.py", status=FileStatus.CONFIRMED, summary="Ok.")

        # No .tmp files should remain
        tmp_files = list(guide_dir.glob("*.tmp"))
        assert tmp_files == []


class TestEdgeCases:
    """Edge cases and robustness."""

    def test_empty_map_creates_empty_progress(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data([])
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        data = mgr.load()

        assert data["files"] == {}
        assert data["stats"]["total"] == 0
        assert data["stats"]["unread"] == 0

    def test_update_from_flagged_to_confirmed(self, tmp_path: Path) -> None:
        """Re-reviewing a flagged file and confirming it."""
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data(["a.py"])
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        mgr.update_file("a.py", status=FileStatus.FLAGGED, note="Check this.")
        mgr.update_file("a.py", status=FileStatus.CONFIRMED, summary="All good now.")

        data = mgr.load()
        assert data["files"]["a.py"]["status"] == "confirmed"
        assert data["files"]["a.py"]["summary"] == "All good now."
        assert data["files"]["a.py"]["note"] is None
        assert data["stats"]["confirmed"] == 1
        assert data["stats"]["flagged"] == 0

    def test_create_raises_if_progress_exists(self, tmp_path: Path) -> None:
        """create() refuses to overwrite existing progress."""
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data()
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)

        with pytest.raises(FileExistsError):
            mgr.create(map_data, map_hash)

    def test_create_with_force_overwrites(self, tmp_path: Path) -> None:
        """create(force=True) overwrites existing progress."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        mgr.update_file("a.py", status=FileStatus.CONFIRMED, summary="Ok.")

        mgr.create(map_data, map_hash, force=True)
        data = mgr.load()
        assert data["files"]["a.py"]["status"] == "unread"

    def test_compute_stats_auto_loads(self, tmp_path: Path) -> None:
        """compute_stats works without explicit load()."""
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data(["a.py"])
        map_hash = _write_map(guide_dir, map_data)

        mgr1 = ProgressManager(guide_dir)
        mgr1.create(map_data, map_hash)

        mgr2 = ProgressManager(guide_dir)
        stats = mgr2.compute_stats()
        assert stats["unread"] == 1

    def test_unknown_status_counted_as_unread(
        self, tmp_path: Path,
    ) -> None:
        """Unknown status values are counted as unread."""
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data(["a.py"])
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)

        # Inject an unknown status directly on disk
        data = mgr.load()
        data["files"]["a.py"]["status"] = "alien_status"
        raw = json.dumps(data, indent=2) + "\n"
        (guide_dir / "progress.json").write_text(raw)

        mgr2 = ProgressManager(guide_dir)
        mgr2.load()
        stats = mgr2.compute_stats()
        assert stats["unread"] == 1
        assert stats["total"] == 1

    def test_file_status_enum_values(self) -> None:
        """FileStatus enum has the four expected values."""
        assert FileStatus.CONFIRMED.value == "confirmed"
        assert FileStatus.FLAGGED.value == "flagged"
        assert FileStatus.SKIMMED.value == "skimmed"
        assert FileStatus.UNREAD.value == "unread"


class TestNextUnreadPointer:
    """next_unread_index pointer in progress.json (BED-97)."""

    def test_create_initializes_pointer_to_zero(self, tmp_path: Path) -> None:
        """New progress.json has next_unread_index set to 0."""
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data(["a.py", "b.py"])
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        data = mgr.load()

        assert data["next_unread_index"] == 0

    def test_advance_pointer_finds_next_unread(self, tmp_path: Path) -> None:
        """After marking first file, pointer advances to index 1."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py", "c.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        mgr.update_file("a.py", status=FileStatus.CONFIRMED, summary="Done.")
        mgr.advance_pointer(files)
        data = mgr.load()

        assert data["next_unread_index"] == 1

    def test_advance_pointer_skips_multiple_read(self, tmp_path: Path) -> None:
        """Pointer skips over confirmed and flagged files."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py", "c.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        mgr.update_file("a.py", status=FileStatus.CONFIRMED, summary="Done.")
        mgr.update_file("b.py", status=FileStatus.FLAGGED, note="Check.")
        mgr.advance_pointer(files)
        data = mgr.load()

        assert data["next_unread_index"] == 2

    def test_advance_pointer_at_end_when_all_read(self, tmp_path: Path) -> None:
        """When all files are read, pointer equals len(files)."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        mgr.update_file("a.py", status=FileStatus.CONFIRMED, summary="Done.")
        mgr.update_file("b.py", status=FileStatus.CONFIRMED, summary="Done.")
        mgr.advance_pointer(files)
        data = mgr.load()

        assert data["next_unread_index"] == 2

    def test_advance_pointer_persists_to_disk(self, tmp_path: Path) -> None:
        """Pointer survives a fresh ProgressManager instance."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py", "c.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)

        mgr1 = ProgressManager(guide_dir)
        mgr1.create(map_data, map_hash)
        mgr1.update_file("a.py", status=FileStatus.CONFIRMED, summary="Done.")
        mgr1.advance_pointer(files)

        mgr2 = ProgressManager(guide_dir)
        data = mgr2.load()
        assert data["next_unread_index"] == 1

    def test_legacy_progress_defaults_pointer_to_zero(
        self, tmp_path: Path,
    ) -> None:
        """Progress files without next_unread_index default to 0."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)

        # Remove field to simulate legacy progress
        data = mgr.load()
        del data["next_unread_index"]
        raw = json.dumps(data, indent=2) + "\n"
        (guide_dir / "progress.json").write_text(raw)

        mgr2 = ProgressManager(guide_dir)
        mgr2.load()
        mgr2.advance_pointer(files)
        data2 = mgr2.load()
        assert data2["next_unread_index"] == 0
