"""Tests for /read-next command logic (BED-75).

Covers: finding the next unread file, building structural briefings,
session context injection, completion actions (confirmed/flagged/skimmed),
session counting, edge cases (all read, no map, no progress).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from nlv.progress import FileStatus, ProgressManager
from nlv.read_next import (
    AllFilesReadError,
    ReadNextManager,
)


def _make_map_data(
    files: list[str] | None = None,
    layers: dict[str, dict[str, Any]] | None = None,
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
                "files": files[1:3] if len(files) > 2 else files[1:],
            },
            "integration": {
                "description": "Composes features",
                "files": files[3:] if len(files) > 3 else [],
            },
        }

    extras = reading_order_extras or {}
    reading_order = []
    for i, f in enumerate(files):
        entry: dict[str, Any] = {
            "index": i,
            "path": f,
            "layer": _layer_for_file(f, layers),
            "reason": f"File #{i} in reading order.",
            "complexity": "low",
            "line_count": 50 + i * 10,
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
    """Find which layer a file belongs to."""
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


def _setup_progress(
    guide_dir: Path,
    map_data: dict[str, Any],
    map_hash: str,
    updates: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Create progress.json and apply optional file updates."""
    mgr = ProgressManager(guide_dir)
    mgr.create(map_data, map_hash)
    if updates:
        for path, kwargs in updates.items():
            status = FileStatus(kwargs["status"])
            mgr.update_file(
                path,
                status=status,
                note=kwargs.get("note"),
                summary=kwargs.get("summary"),
            )


# --- Finding the next unread file ---


class TestFindNextUnread:
    """ReadNextManager should find the next unread file in order."""

    def test_first_file_when_nothing_read(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/models.py", "src/api.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()

        assert briefing.path == "src/config.py"

    def test_skips_confirmed_files(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/models.py", "src/api.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(
            guide_dir,
            map_data,
            map_hash,
            updates={
                "src/config.py": {
                    "status": "confirmed",
                    "summary": "Config.",
                },
            },
        )

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()

        assert briefing.path == "src/models.py"

    def test_skips_flagged_and_skimmed(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = [
            "src/config.py",
            "src/models.py",
            "src/service.py",
            "src/api.py",
        ]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(
            guide_dir,
            map_data,
            map_hash,
            updates={
                "src/config.py": {
                    "status": "confirmed",
                    "summary": "Config.",
                },
                "src/models.py": {
                    "status": "flagged",
                    "note": "Check types",
                },
                "src/service.py": {
                    "status": "skimmed",
                    "summary": "Service layer.",
                },
            },
        )

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()

        assert briefing.path == "src/api.py"

    def test_all_files_read_raises(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(
            guide_dir,
            map_data,
            map_hash,
            updates={
                "src/config.py": {
                    "status": "confirmed",
                    "summary": "Done.",
                },
            },
        )

        mgr = ReadNextManager(guide_dir)

        with pytest.raises(AllFilesReadError):
            mgr.next_briefing()


# --- Briefing content ---


class TestBriefingContent:
    """The briefing must include layer, lines, complexity, reason."""

    def test_briefing_has_layer(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()

        assert briefing.layer == "foundation"

    def test_briefing_has_line_count(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()

        assert briefing.line_count == 50

    def test_briefing_has_complexity(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        extras = {"src/config.py": {"complexity": "high"}}
        map_data = _make_map_data(files, reading_order_extras=extras)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()

        assert briefing.complexity == "high"

    def test_briefing_has_reason(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        extras = {
            "src/config.py": {
                "reason": "No dependencies. Used by 23 files.",
            },
        }
        map_data = _make_map_data(files, reading_order_extras=extras)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()

        assert briefing.reason == "No dependencies. Used by 23 files."

    def test_briefing_has_exports(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        extras = {
            "src/config.py": {
                "exports": ["AppConfig", "getConfig"],
            },
        }
        map_data = _make_map_data(files, reading_order_extras=extras)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()

        assert briefing.exports == ["AppConfig", "getConfig"]

    def test_briefing_has_imported_by(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        extras = {
            "src/config.py": {
                "imported_by": ["src/api.py", "src/app.py"],
            },
        }
        map_data = _make_map_data(files, reading_order_extras=extras)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()

        assert briefing.imported_by == ["src/api.py", "src/app.py"]

    def test_briefing_has_imports(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/api.py"]
        extras = {
            "src/api.py": {"imports": ["src/config.py"]},
        }
        map_data = _make_map_data(files, reading_order_extras=extras)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(
            guide_dir,
            map_data,
            map_hash,
            updates={
                "src/config.py": {
                    "status": "confirmed",
                    "summary": "Config.",
                },
            },
        )

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()

        assert briefing.imports == ["src/config.py"]


# --- Dependency status in briefing ---


class TestDependencyStatus:
    """Briefing shows read status of each import."""

    def test_dependency_statuses_included(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/models.py", "src/api.py"]
        extras = {
            "src/api.py": {
                "imports": ["src/config.py", "src/models.py"],
            },
        }
        map_data = _make_map_data(files, reading_order_extras=extras)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(
            guide_dir,
            map_data,
            map_hash,
            updates={
                "src/config.py": {
                    "status": "confirmed",
                    "summary": "Config.",
                },
                "src/models.py": {
                    "status": "flagged",
                    "note": "Check types",
                    "summary": "Models.",
                },
            },
        )

        mgr = ReadNextManager(guide_dir)
        # First two are read; next unread is src/api.py
        briefing = mgr.next_briefing()

        assert briefing.path == "src/api.py"
        assert briefing.dependency_statuses["src/config.py"] == (
            "confirmed"
        )
        assert briefing.dependency_statuses["src/models.py"] == (
            "flagged"
        )

    def test_unread_dependency_not_in_statuses(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/models.py", "src/api.py"]
        extras = {
            "src/models.py": {
                "imports": ["src/config.py"],
            },
        }
        map_data = _make_map_data(files, reading_order_extras=extras)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(
            guide_dir,
            map_data,
            map_hash,
            updates={
                "src/config.py": {
                    "status": "confirmed",
                    "summary": "Config.",
                },
                # models is the next unread; config is its dep (read)
            },
        )

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()

        assert briefing.path == "src/models.py"
        assert "src/config.py" in briefing.dependency_statuses


# --- Session context integration ---


class TestSessionContext:
    """Briefing includes session context from session_priming."""

    def test_session_context_present(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/api.py"]
        extras = {
            "src/api.py": {"imports": ["src/config.py"]},
        }
        map_data = _make_map_data(files, reading_order_extras=extras)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(
            guide_dir,
            map_data,
            map_hash,
            updates={
                "src/config.py": {
                    "status": "confirmed",
                    "summary": "Core configuration.",
                },
            },
        )

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()

        assert briefing.session_context is not None
        assert briefing.session_context.current_file == "src/api.py"

    def test_session_context_has_dep_summaries(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/api.py"]
        extras = {
            "src/api.py": {"imports": ["src/config.py"]},
        }
        map_data = _make_map_data(files, reading_order_extras=extras)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(
            guide_dir,
            map_data,
            map_hash,
            updates={
                "src/config.py": {
                    "status": "confirmed",
                    "summary": "Core config with env overrides.",
                },
            },
        )

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()

        dep_sums = briefing.session_context.dependency_summaries
        assert dep_sums["src/config.py"] == (
            "Core config with env overrides."
        )


# --- Briefing formatting ---


class TestBriefingFormat:
    """Formatted briefing must match the spec template."""

    def test_format_includes_path(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()
        output = briefing.format()

        assert "src/config.py" in output

    def test_format_includes_layer_lines_complexity(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        extras = {
            "src/config.py": {
                "complexity": "medium",
                "line_count": 142,
            },
        }
        map_data = _make_map_data(files, reading_order_extras=extras)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()
        output = briefing.format()

        assert "foundation" in output
        assert "142" in output
        assert "medium" in output

    def test_format_includes_reason(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        extras = {
            "src/config.py": {
                "reason": "No dependencies. Used by 23 files.",
            },
        }
        map_data = _make_map_data(files, reading_order_extras=extras)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()
        output = briefing.format()

        assert "No dependencies. Used by 23 files." in output

    def test_format_shows_dependency_statuses(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/models.py", "src/api.py"]
        extras = {
            "src/api.py": {
                "imports": ["src/config.py", "src/models.py"],
            },
        }
        map_data = _make_map_data(files, reading_order_extras=extras)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(
            guide_dir,
            map_data,
            map_hash,
            updates={
                "src/config.py": {
                    "status": "confirmed",
                    "summary": "Config.",
                },
                "src/models.py": {
                    "status": "confirmed",
                    "summary": "Models.",
                },
            },
        )

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()
        output = briefing.format()

        assert "src/config.py" in output
        assert "confirmed" in output

    def test_format_shows_exports(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        extras = {
            "src/config.py": {
                "exports": ["AppConfig", "getConfig"],
            },
        }
        map_data = _make_map_data(files, reading_order_extras=extras)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()
        output = briefing.format()

        assert "AppConfig" in output
        assert "getConfig" in output

    def test_format_shows_imported_by(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        extras = {
            "src/config.py": {
                "imported_by": ["src/api.py", "src/app.py"],
            },
        }
        map_data = _make_map_data(files, reading_order_extras=extras)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()
        output = briefing.format()

        assert "src/api.py" in output
        assert "src/app.py" in output

    def test_format_shows_separator_lines(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()
        output = briefing.format()

        assert "---" in output or "---" in output.replace(" ", "")


# --- Completion actions ---


class TestCompletionActions:
    """complete_file must update progress for each action type."""

    def test_complete_confirmed(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        mgr.next_briefing()
        mgr.complete_file(
            "src/config.py",
            action="confirmed",
            summary="Config with env overrides.",
        )

        pm = ProgressManager(guide_dir)
        data = pm.load()
        assert data["files"]["src/config.py"]["status"] == "confirmed"
        assert data["files"]["src/config.py"]["summary"] == (
            "Config with env overrides."
        )

    def test_complete_flagged_with_note(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        mgr.next_briefing()
        mgr.complete_file(
            "src/config.py",
            action="flagged",
            note="Dual token store seems unnecessary",
            summary="Auth middleware with JWT.",
        )

        pm = ProgressManager(guide_dir)
        data = pm.load()
        assert data["files"]["src/config.py"]["status"] == "flagged"
        assert data["files"]["src/config.py"]["note"] == (
            "Dual token store seems unnecessary"
        )

    def test_complete_skimmed(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        mgr.next_briefing()
        mgr.complete_file(
            "src/config.py",
            action="skimmed",
            summary="Boilerplate config.",
        )

        pm = ProgressManager(guide_dir)
        data = pm.load()
        assert data["files"]["src/config.py"]["status"] == "skimmed"

    def test_complete_invalid_action_raises(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        mgr.next_briefing()

        with pytest.raises(ValueError, match="Invalid action"):
            mgr.complete_file("src/config.py", action="invalid")

    def test_complete_unknown_file_raises(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        mgr.next_briefing()

        with pytest.raises(KeyError):
            mgr.complete_file("nonexistent.py", action="confirmed")

    def test_complete_updates_stats(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/models.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        mgr.next_briefing()
        mgr.complete_file(
            "src/config.py",
            action="confirmed",
            summary="Config.",
        )

        pm = ProgressManager(guide_dir)
        data = pm.load()
        assert data["stats"]["confirmed"] == 1
        assert data["stats"]["unread"] == 1


# --- Auto-advance after completion ---


class TestAutoAdvance:
    """After completing a file, next_briefing returns the next one."""

    def test_advance_after_confirm(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/models.py", "src/api.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        b1 = mgr.next_briefing()
        assert b1.path == "src/config.py"

        mgr.complete_file(
            "src/config.py",
            action="confirmed",
            summary="Config.",
        )

        b2 = mgr.next_briefing()
        assert b2.path == "src/models.py"

    def test_advance_to_end_raises(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        mgr.next_briefing()
        mgr.complete_file(
            "src/config.py",
            action="confirmed",
            summary="Done.",
        )

        with pytest.raises(AllFilesReadError):
            mgr.next_briefing()


# --- Session counting ---


class TestSessionCounting:
    """First next_briefing in a session increments session count."""

    def test_first_briefing_increments_session(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/models.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        mgr.next_briefing()

        pm = ProgressManager(guide_dir)
        data = pm.load()
        # progress.create() sets sessions=1, next_briefing adds 1
        assert data["sessions"] == 2

    def test_subsequent_briefings_no_extra_increment(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/models.py", "src/api.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        mgr.next_briefing()
        mgr.complete_file(
            "src/config.py",
            action="confirmed",
            summary="Config.",
        )
        mgr.next_briefing()

        pm = ProgressManager(guide_dir)
        data = pm.load()
        # Should still be 2 (only incremented once per session)
        assert data["sessions"] == 2


# --- All files read message ---


class TestAllFilesRead:
    """When all files are read, provide stats summary."""

    def test_all_files_read_error_has_stats(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(
            guide_dir,
            map_data,
            map_hash,
            updates={
                "src/config.py": {
                    "status": "confirmed",
                    "summary": "Done.",
                },
            },
        )

        mgr = ReadNextManager(guide_dir)

        with pytest.raises(AllFilesReadError) as exc_info:
            mgr.next_briefing()

        msg = str(exc_info.value)
        assert "1" in msg  # total count

    def test_format_all_read_message(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/models.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(
            guide_dir,
            map_data,
            map_hash,
            updates={
                "src/config.py": {
                    "status": "confirmed",
                    "summary": "Config.",
                },
                "src/models.py": {
                    "status": "flagged",
                    "note": "Check types",
                    "summary": "Models.",
                },
            },
        )

        mgr = ReadNextManager(guide_dir)
        msg = mgr.format_all_read()

        assert "2" in msg  # total files
        assert "confirmed" in msg.lower() or "1" in msg
        assert "flagged" in msg.lower()


# --- Missing files edge cases ---


class TestMissingFiles:
    """Edge cases: missing map.json, missing progress.json."""

    def test_missing_map_json_raises(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        guide_dir.mkdir(parents=True)

        mgr = ReadNextManager(guide_dir)

        with pytest.raises(FileNotFoundError):
            mgr.next_briefing()

    def test_missing_progress_json_raises(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        map_data = _make_map_data(files)
        _write_map(guide_dir, map_data)
        # No progress.json

        mgr = ReadNextManager(guide_dir)

        with pytest.raises(FileNotFoundError):
            mgr.next_briefing()


# --- Pointer optimization (BED-97) ---


class TestPointerOptimization:
    """next_unread_index pointer optimization (BED-97)."""

    def test_complete_file_advances_pointer(
        self, tmp_path: Path,
    ) -> None:
        """Completing a file updates next_unread_index in progress."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/models.py", "src/api.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        mgr.next_briefing()
        mgr.complete_file(
            "src/config.py", action="confirmed", summary="Config.",
        )

        pm = ProgressManager(guide_dir)
        data = pm.load()
        assert data["next_unread_index"] == 1

    def test_sequential_completion_advances_pointer(
        self, tmp_path: Path,
    ) -> None:
        """Completing files 0 and 1 moves pointer to 2."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/models.py", "src/api.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        mgr.next_briefing()
        mgr.complete_file(
            "src/config.py", action="confirmed", summary="Config.",
        )
        mgr.next_briefing()
        mgr.complete_file(
            "src/models.py", action="confirmed", summary="Models.",
        )

        pm = ProgressManager(guide_dir)
        data = pm.load()
        assert data["next_unread_index"] == 2

    def test_out_of_order_completion_preserves_pointer(
        self, tmp_path: Path,
    ) -> None:
        """Completing a file ahead of the pointer doesn't skip unread."""
        guide_dir = tmp_path / ".codebase-guide"
        files = [
            "src/config.py", "src/models.py",
            "src/service.py", "src/api.py",
        ]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr = ReadNextManager(guide_dir)
        mgr.next_briefing()
        mgr.complete_file(
            "src/config.py", action="confirmed", summary="Config.",
        )

        # Complete file at index 2 out of order (e.g. via /read-flagged)
        mgr.complete_file(
            "src/service.py", action="confirmed", summary="Service.",
        )

        # Pointer should still point to index 1 (src/models.py)
        pm = ProgressManager(guide_dir)
        data = pm.load()
        assert data["next_unread_index"] == 1

        # And next_briefing should return src/models.py
        briefing = mgr.next_briefing()
        assert briefing.path == "src/models.py"

    def test_pointer_survives_new_manager_instance(
        self, tmp_path: Path,
    ) -> None:
        """New ReadNextManager uses the stored pointer."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/models.py", "src/api.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        mgr1 = ReadNextManager(guide_dir)
        mgr1.next_briefing()
        mgr1.complete_file(
            "src/config.py", action="confirmed", summary="Config.",
        )

        mgr2 = ReadNextManager(guide_dir)
        briefing = mgr2.next_briefing()
        assert briefing.path == "src/models.py"

        pm = ProgressManager(guide_dir)
        data = pm.load()
        assert data["next_unread_index"] == 1

    def test_lookup_works_with_stale_pointer(
        self, tmp_path: Path,
    ) -> None:
        """When files are marked outside this manager, lookup still works."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/models.py", "src/api.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(
            guide_dir, map_data, map_hash,
            updates={
                "src/config.py": {
                    "status": "confirmed", "summary": "Config.",
                },
                "src/models.py": {
                    "status": "confirmed", "summary": "Models.",
                },
            },
        )

        # Pointer is 0 (stale) but lookup should still find api.py
        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()

        assert briefing.path == "src/api.py"

    def test_fallback_scan_finds_unread_before_pointer(
        self, tmp_path: Path,
    ) -> None:
        """Stale pointer falls back to scanning from index 0."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/models.py", "src/api.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        # Manually set pointer past the end to simulate stale state
        pm = ProgressManager(guide_dir)
        data = pm.load()
        data["next_unread_index"] = 3
        raw = json.dumps(data, indent=2) + "\n"
        (guide_dir / "progress.json").write_text(raw)

        mgr = ReadNextManager(guide_dir)
        briefing = mgr.next_briefing()

        # Fallback should find the first unread file
        assert briefing.path == "src/config.py"

    def test_pointer_beyond_array_length_returns_none(
        self, tmp_path: Path,
    ) -> None:
        """Pointer past reading_order length still works gracefully."""
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(
            guide_dir, map_data, map_hash,
            updates={
                "src/config.py": {
                    "status": "confirmed", "summary": "Config.",
                },
            },
        )

        # Set pointer way past the end
        pm = ProgressManager(guide_dir)
        data = pm.load()
        data["next_unread_index"] = 999
        raw = json.dumps(data, indent=2) + "\n"
        (guide_dir / "progress.json").write_text(raw)

        mgr = ReadNextManager(guide_dir)
        with pytest.raises(AllFilesReadError):
            mgr.next_briefing()
