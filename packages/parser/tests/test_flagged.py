"""Tests for /read-flagged command logic (BED-77).

Covers: collecting flagged files, ordering by reading order, formatting
briefings, resolving/re-flagging/skipping, and edge cases.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from nlv.flagged import (
    FlaggedIterator,
    NoFlaggedFilesError,
)
from nlv.progress import FileStatus, ProgressManager


def _make_map_data(
    files: list[str] | None = None,
    layers: dict[str, list[str]] | None = None,
    reading_order_extras: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a minimal map.json structure for testing."""
    if files is None:
        files = [
            "src/config.py",
            "src/models.py",
            "src/service.py",
            "src/api.py",
            "src/app.py",
        ]
    if layers is None:
        layers = {
            "foundation": {
                "description": "No deps",
                "files": files[:1],
            },
            "core": {
                "description": "Depends on foundation",
                "files": files[1:3],
            },
            "integration": {
                "description": "Composes features",
                "files": files[3:],
            },
        }

    extras = reading_order_extras or {}
    reading_order = []
    for i, f in enumerate(files):
        entry: dict[str, Any] = {
            "index": i,
            "path": f,
            "layer": _layer_for_file(f, layers),
            "line_count": 50 + i * 10,
            "complexity": "low",
            "imports": [],
            "imported_by": [],
            "exports": [],
        }
        if f in extras:
            entry.update(extras[f])
        reading_order.append(entry)

    return {
        "version": "1.0.0",
        "repo_root": "/tmp/test-repo",
        "generated_at": "2026-04-05T10:00:00Z",
        "content_hashes": {
            f: hashlib.sha256(f.encode()).hexdigest()[:8]
            for f in files
        },
        "total_files": len(files),
        "layers": layers,
        "reading_order": reading_order,
        "dependency_graph": {
            f: {"imports": [], "imported_by": []}
            for f in files
        },
    }


def _layer_for_file(
    filepath: str,
    layers: dict[str, list[str] | dict[str, Any]],
) -> str:
    """Find the layer a file belongs to."""
    for layer_name, layer_val in layers.items():
        if isinstance(layer_val, dict):
            layer_files = layer_val.get("files", [])
        else:
            layer_files = layer_val
        if filepath in layer_files:
            return layer_name
    return "unknown"


def _write_map(guide_dir: Path, map_data: dict[str, Any]) -> str:
    """Write map.json and return its content hash."""
    guide_dir.mkdir(parents=True, exist_ok=True)
    content = json.dumps(map_data, indent=2)
    (guide_dir / "map.json").write_text(content)
    return hashlib.sha256(content.encode()).hexdigest()


def _setup_progress_with_flags(
    guide_dir: Path,
    map_data: dict[str, Any],
    map_hash: str,
    flagged_files: dict[str, str],
    confirmed_files: list[str] | None = None,
) -> ProgressManager:
    """Create progress.json with specified files flagged.

    Args:
        guide_dir: Path to .codebase-guide directory.
        map_data: Map data dict.
        map_hash: SHA-256 hex of map.json content.
        flagged_files: Mapping of filepath -> flag note.
        confirmed_files: Filepaths to mark as confirmed.
    """
    mgr = ProgressManager(guide_dir)
    mgr.create(map_data, map_hash)

    for path, note in flagged_files.items():
        mgr.update_file(
            path,
            status=FileStatus.FLAGGED,
            note=note,
            summary=f"First-pass summary of {path}.",
        )

    for path in (confirmed_files or []):
        mgr.update_file(
            path,
            status=FileStatus.CONFIRMED,
            summary=f"Confirmed: {path}.",
        )

    return mgr


# --- Collecting flagged files ---


class TestCollectFlaggedFiles:
    """FlaggedIterator should collect only flagged files."""

    def test_collects_flagged_files_only(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/a.py", "src/b.py", "src/c.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={"src/b.py": "Check this"},
            confirmed_files=["src/a.py"],
        )

        it = FlaggedIterator(guide_dir)
        briefings = it.collect()

        assert len(briefings) == 1
        assert briefings[0].path == "src/b.py"

    def test_returns_multiple_flagged_files(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/a.py", "src/b.py", "src/c.py", "src/d.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={
                "src/b.py": "Check this",
                "src/d.py": "Also check",
            },
        )

        it = FlaggedIterator(guide_dir)
        briefings = it.collect()

        assert len(briefings) == 2
        paths = [b.path for b in briefings]
        assert "src/b.py" in paths
        assert "src/d.py" in paths


# --- Reading order preservation ---


class TestReadingOrder:
    """Flagged files must be presented in their original reading order."""

    def test_flagged_files_sorted_by_reading_order(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = [
            "src/config.py",
            "src/models.py",
            "src/service.py",
            "src/api.py",
            "src/app.py",
        ]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        # Flag files in reverse order of reading order
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={
                "src/app.py": "Entry point issue",
                "src/models.py": "Type concern",
                "src/service.py": "Logic question",
            },
        )

        it = FlaggedIterator(guide_dir)
        briefings = it.collect()

        result_paths = [b.path for b in briefings]
        assert result_paths == [
            "src/models.py",
            "src/service.py",
            "src/app.py",
        ]

    def test_reading_order_index_preserved(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/a.py", "src/b.py", "src/c.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={"src/c.py": "Check"},
        )

        it = FlaggedIterator(guide_dir)
        briefings = it.collect()

        assert briefings[0].reading_order_index == 2


# --- Briefing content ---


class TestBriefingContent:
    """Each flagged file briefing must include required context."""

    def test_briefing_has_flag_note(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/a.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={"src/a.py": "Dual token store"},
        )

        it = FlaggedIterator(guide_dir)
        briefings = it.collect()

        assert briefings[0].note == "Dual token store"

    def test_briefing_has_summary(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/a.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={"src/a.py": "Check it"},
        )

        it = FlaggedIterator(guide_dir)
        briefings = it.collect()

        assert briefings[0].summary == "First-pass summary of src/a.py."

    def test_briefing_has_layer(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/models.py"]
        layers = {
            "foundation": {
                "description": "No deps",
                "files": ["src/config.py"],
            },
            "core": {
                "description": "Deps on foundation",
                "files": ["src/models.py"],
            },
        }
        map_data = _make_map_data(files, layers=layers)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={"src/models.py": "Check types"},
        )

        it = FlaggedIterator(guide_dir)
        briefings = it.collect()

        assert briefings[0].layer == "core"

    def test_briefing_has_structural_context(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/models.py"]
        extras = {
            "src/models.py": {
                "imports": ["src/config.py"],
                "imported_by": ["src/api.py"],
                "exports": ["User", "Session"],
            },
        }
        map_data = _make_map_data(files, reading_order_extras=extras)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={"src/models.py": "Check"},
        )

        it = FlaggedIterator(guide_dir)
        briefings = it.collect()

        b = briefings[0]
        assert b.imports == ["src/config.py"]
        assert b.imported_by == ["src/api.py"]
        assert b.exports == ["User", "Session"]

    def test_briefing_has_line_count(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/a.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={"src/a.py": "Check"},
        )

        it = FlaggedIterator(guide_dir)
        briefings = it.collect()

        assert briefings[0].line_count == 50


# --- Formatting ---


class TestFormatBriefing:
    """Formatted output must match the SKILL.md template."""

    def test_format_includes_path(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/auth.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={"src/auth.py": "JWT issue"},
        )

        it = FlaggedIterator(guide_dir)
        briefings = it.collect()
        output = briefings[0].format()

        assert "src/auth.py" in output

    def test_format_includes_original_note(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/auth.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={
                "src/auth.py": "Dual token store seems unnecessary",
            },
        )

        it = FlaggedIterator(guide_dir)
        briefings = it.collect()
        output = briefings[0].format()

        assert "Dual token store seems unnecessary" in output

    def test_format_includes_layer(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/auth.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={"src/auth.py": "Check"},
        )

        it = FlaggedIterator(guide_dir)
        briefings = it.collect()
        output = briefings[0].format()

        assert "Layer:" in output

    def test_format_includes_original_summary(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/auth.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={"src/auth.py": "Check"},
        )

        it = FlaggedIterator(guide_dir)
        briefings = it.collect()
        output = briefings[0].format()

        assert "First-pass summary of src/auth.py." in output

    def test_format_includes_exports(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/auth.py"]
        extras = {
            "src/auth.py": {
                "exports": ["authenticate", "refresh"],
            },
        }
        map_data = _make_map_data(files, reading_order_extras=extras)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={"src/auth.py": "Check"},
        )

        it = FlaggedIterator(guide_dir)
        briefings = it.collect()
        output = briefings[0].format()

        assert "authenticate" in output
        assert "refresh" in output


# --- Resolve actions ---


class TestResolveActions:
    """Resolve, re-flag, and skip must update progress correctly."""

    def test_resolve_to_confirmed(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/a.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={"src/a.py": "Check"},
        )

        it = FlaggedIterator(guide_dir)
        it.collect()
        it.resolve(
            "src/a.py",
            action="confirmed",
            summary="All good now.",
        )

        mgr = ProgressManager(guide_dir)
        data = mgr.load()
        assert data["files"]["src/a.py"]["status"] == "confirmed"
        assert data["files"]["src/a.py"]["note"] is None
        assert data["files"]["src/a.py"]["summary"] == "All good now."

    def test_reflag_with_updated_note(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/a.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={"src/a.py": "Original concern"},
        )

        it = FlaggedIterator(guide_dir)
        it.collect()
        it.resolve(
            "src/a.py",
            action="flagged",
            note="Updated concern after second look",
        )

        mgr = ProgressManager(guide_dir)
        data = mgr.load()
        assert data["files"]["src/a.py"]["status"] == "flagged"
        assert data["files"]["src/a.py"]["note"] == (
            "Updated concern after second look"
        )

    def test_resolve_to_skimmed(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/a.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={"src/a.py": "Check"},
        )

        it = FlaggedIterator(guide_dir)
        it.collect()
        it.resolve("src/a.py", action="skimmed")

        mgr = ProgressManager(guide_dir)
        data = mgr.load()
        assert data["files"]["src/a.py"]["status"] == "skimmed"

    def test_resolve_updates_stats(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/a.py", "src/b.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={
                "src/a.py": "Check A",
                "src/b.py": "Check B",
            },
        )

        it = FlaggedIterator(guide_dir)
        it.collect()
        it.resolve("src/a.py", action="confirmed", summary="Done.")

        mgr = ProgressManager(guide_dir)
        data = mgr.load()
        assert data["stats"]["confirmed"] == 1
        assert data["stats"]["flagged"] == 1

    def test_resolve_unknown_file_raises(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/a.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={"src/a.py": "Check"},
        )

        it = FlaggedIterator(guide_dir)
        it.collect()

        with pytest.raises(KeyError):
            it.resolve("nonexistent.py", action="confirmed")

    def test_resolve_invalid_action_raises(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/a.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={"src/a.py": "Check"},
        )

        it = FlaggedIterator(guide_dir)
        it.collect()

        with pytest.raises(ValueError, match="Invalid action"):
            it.resolve("src/a.py", action="invalid_status")


# --- Edge cases ---


class TestEdgeCases:
    """Edge cases: no flags, missing files, etc."""

    def test_no_flagged_files_raises(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/a.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        mgr.update_file(
            "src/a.py",
            status=FileStatus.CONFIRMED,
            summary="Done.",
        )

        it = FlaggedIterator(guide_dir)
        with pytest.raises(NoFlaggedFilesError):
            it.collect()

    def test_progress_file_missing_raises(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        guide_dir.mkdir(parents=True)
        files = ["src/a.py"]
        map_data = _make_map_data(files)
        _write_map(guide_dir, map_data)

        it = FlaggedIterator(guide_dir)
        with pytest.raises(FileNotFoundError):
            it.collect()

    def test_map_file_missing_raises(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        guide_dir.mkdir(parents=True)
        # No map.json written, but write a progress.json
        files = ["src/a.py"]
        map_data = _make_map_data(files)
        map_hash = "fake-hash"
        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)

        it = FlaggedIterator(guide_dir)
        with pytest.raises(FileNotFoundError):
            it.collect()

    def test_flagged_file_not_in_reading_order(
        self, tmp_path: Path,
    ) -> None:
        """A flagged file missing from map's reading_order is skipped."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/a.py", "src/b.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        # Flag src/b.py normally
        mgr.update_file(
            "src/b.py",
            status=FileStatus.FLAGGED,
            note="Check",
        )

        # Now remove src/b.py from reading_order in map.json
        map_data["reading_order"] = [
            e for e in map_data["reading_order"]
            if e["path"] != "src/b.py"
        ]
        content = json.dumps(map_data, indent=2)
        (guide_dir / "map.json").write_text(content)

        it = FlaggedIterator(guide_dir)
        # The file is flagged in progress but not in reading_order;
        # it should be included at the end since it has no index
        briefings = it.collect()
        paths = [b.path for b in briefings]
        assert "src/b.py" in paths

    def test_all_flagged_resolved_then_no_more(
        self, tmp_path: Path,
    ) -> None:
        """After resolving all flagged files, remaining() is empty."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/a.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={"src/a.py": "Check"},
        )

        it = FlaggedIterator(guide_dir)
        it.collect()
        it.resolve("src/a.py", action="confirmed", summary="Done.")

        remaining = it.remaining()
        assert len(remaining) == 0

    def test_remaining_tracks_unresolved(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/a.py", "src/b.py", "src/c.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress_with_flags(
            guide_dir,
            map_data,
            map_hash,
            flagged_files={
                "src/a.py": "Check A",
                "src/b.py": "Check B",
            },
        )

        it = FlaggedIterator(guide_dir)
        it.collect()
        it.resolve("src/a.py", action="confirmed", summary="Done.")

        remaining = it.remaining()
        assert len(remaining) == 1
        assert remaining[0].path == "src/b.py"

    def test_briefing_with_none_note(self, tmp_path: Path) -> None:
        """Flagged file with no note still works."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/a.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)

        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)
        # Flag without a note explicitly
        mgr.update_file(
            "src/a.py",
            status=FileStatus.FLAGGED,
        )

        it = FlaggedIterator(guide_dir)
        briefings = it.collect()

        assert briefings[0].note is None
        # Format should not crash
        output = briefings[0].format()
        assert "src/a.py" in output
