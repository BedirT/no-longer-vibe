"""Tests for session priming — compressed context from previous summaries (BED-79).

Covers: building context for /read-next, dependency summaries vs general
progress, structural data inclusion, compact formatting, missing summaries,
and edge cases (no files read, all deps read, no deps).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from nlv.progress import FileStatus, ProgressManager
from nlv.session_priming import SessionContext, build_session_context


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


# --- SessionContext dataclass ---


class TestSessionContextDataclass:
    """SessionContext holds structured context for a reading session."""

    def test_has_current_file_path(self) -> None:
        ctx = SessionContext(
            current_file="src/api.py",
            layer="integration",
            line_count=100,
            complexity="medium",
            reason="All dependencies read.",
            imports=[],
            imported_by=[],
            exports=[],
            dependency_summaries={},
            general_summaries={},
        )
        assert ctx.current_file == "src/api.py"

    def test_has_layer_info(self) -> None:
        ctx = SessionContext(
            current_file="src/api.py",
            layer="integration",
            line_count=100,
            complexity="medium",
            reason="All dependencies read.",
            imports=["src/config.py"],
            imported_by=["src/app.py"],
            exports=["handle_request"],
            dependency_summaries={},
            general_summaries={},
        )
        assert ctx.layer == "integration"
        assert ctx.line_count == 100
        assert ctx.complexity == "medium"


# --- Dependency summaries vs general summaries ---


class TestDependencySeparation:
    """Direct dependencies are separated from general progress."""

    def test_dependency_summaries_contain_imports(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/models.py", "src/api.py"]
        extras = {
            "src/api.py": {
                "imports": ["src/config.py", "src/models.py"],
                "imported_by": [],
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
                    "summary": "Core configuration.",
                },
                "src/models.py": {
                    "status": "confirmed",
                    "summary": "Data models for users and sessions.",
                },
            },
        )

        ctx = build_session_context(guide_dir, "src/api.py")

        assert "src/config.py" in ctx.dependency_summaries
        assert "src/models.py" in ctx.dependency_summaries
        assert ctx.dependency_summaries["src/config.py"] == (
            "Core configuration."
        )

    def test_general_summaries_exclude_dependencies(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = [
            "src/config.py",
            "src/models.py",
            "src/utils.py",
            "src/api.py",
        ]
        extras = {
            "src/api.py": {
                "imports": ["src/config.py"],
                "imported_by": [],
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
                    "summary": "Core configuration.",
                },
                "src/models.py": {
                    "status": "confirmed",
                    "summary": "Data models.",
                },
                "src/utils.py": {
                    "status": "skimmed",
                    "summary": "Utility helpers.",
                },
            },
        )

        ctx = build_session_context(guide_dir, "src/api.py")

        # config is a dep, should not be in general
        assert "src/config.py" not in ctx.general_summaries
        # models and utils are NOT deps, should be in general
        assert "src/models.py" in ctx.general_summaries
        assert "src/utils.py" in ctx.general_summaries

    def test_unread_files_excluded_from_both(
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
                    "summary": "Core config.",
                },
                # src/models.py left unread
            },
        )

        ctx = build_session_context(guide_dir, "src/api.py")

        assert "src/config.py" in ctx.dependency_summaries
        # models is unread -- should appear in deps but with no summary
        assert "src/models.py" not in ctx.dependency_summaries
        assert "src/models.py" not in ctx.general_summaries


# --- Structural data from map.json ---


class TestStructuralData:
    """Structural data (imports, imported_by, exports) from map.json."""

    def test_includes_imports_list(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/api.py"]
        extras = {
            "src/api.py": {
                "imports": ["src/config.py"],
                "imported_by": ["src/app.py"],
                "exports": ["handle_request", "Router"],
            },
        }
        map_data = _make_map_data(files, reading_order_extras=extras)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        ctx = build_session_context(guide_dir, "src/api.py")

        assert ctx.imports == ["src/config.py"]
        assert ctx.imported_by == ["src/app.py"]
        assert ctx.exports == ["handle_request", "Router"]

    def test_includes_layer_and_complexity(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/api.py"]
        extras = {
            "src/api.py": {"complexity": "high", "line_count": 200},
        }
        layers = {
            "foundation": {
                "description": "No deps",
                "files": ["src/config.py"],
            },
            "integration": {
                "description": "Composes",
                "files": ["src/api.py"],
            },
        }
        map_data = _make_map_data(
            files, layers=layers, reading_order_extras=extras,
        )
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        ctx = build_session_context(guide_dir, "src/api.py")

        assert ctx.layer == "integration"
        assert ctx.complexity == "high"
        assert ctx.line_count == 200

    def test_includes_reason(self, tmp_path: Path) -> None:
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

        ctx = build_session_context(guide_dir, "src/config.py")

        assert ctx.reason == "No dependencies. Used by 23 files."


# --- Missing summaries ---


class TestMissingSummaries:
    """Graceful handling when a file was read but no summary stored."""

    def test_read_file_with_no_summary(self, tmp_path: Path) -> None:
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
                    # no summary
                },
            },
        )

        ctx = build_session_context(guide_dir, "src/api.py")

        # Dep was read but has no summary -- should still appear
        assert "src/config.py" in ctx.dependency_summaries
        assert ctx.dependency_summaries["src/config.py"] is None

    def test_general_file_with_no_summary(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/utils.py", "src/api.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(
            guide_dir,
            map_data,
            map_hash,
            updates={
                "src/config.py": {"status": "confirmed"},
                "src/utils.py": {"status": "skimmed"},
            },
        )

        ctx = build_session_context(guide_dir, "src/api.py")

        # Both files read but no summaries stored
        assert "src/config.py" in ctx.general_summaries
        assert ctx.general_summaries["src/config.py"] is None
        assert "src/utils.py" in ctx.general_summaries


# --- Formatted output ---


class TestFormatOutput:
    """The formatted context string is compact and structured."""

    def test_format_includes_file_path(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        ctx = build_session_context(guide_dir, "src/config.py")
        output = ctx.format()

        assert "src/config.py" in output

    def test_format_includes_layer(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        ctx = build_session_context(guide_dir, "src/config.py")
        output = ctx.format()

        assert "foundation" in output

    def test_format_includes_line_count(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        ctx = build_session_context(guide_dir, "src/config.py")
        output = ctx.format()

        assert "50" in output

    def test_format_shows_dependency_summaries(
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
                    "summary": "App configuration with env overrides.",
                },
            },
        )

        ctx = build_session_context(guide_dir, "src/api.py")
        output = ctx.format()

        assert "src/config.py" in output
        assert "App configuration with env overrides." in output

    def test_format_shows_dependency_status_markers(
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

        ctx = build_session_context(guide_dir, "src/api.py")
        output = ctx.format()

        # confirmed should have checkmark
        assert "confirmed" in output or "✓" in output.lower() or "✅" in output
        # flagged should have flag indicator
        assert "flagged" in output or "⚑" in output

    def test_format_shows_general_summary_section(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/utils.py", "src/api.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(
            guide_dir,
            map_data,
            map_hash,
            updates={
                "src/config.py": {
                    "status": "confirmed",
                    "summary": "Config settings.",
                },
                "src/utils.py": {
                    "status": "skimmed",
                    "summary": "Utility helpers.",
                },
            },
        )

        ctx = build_session_context(guide_dir, "src/api.py")
        output = ctx.format()

        assert "Config settings." in output
        assert "Utility helpers." in output

    def test_format_shows_exports(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/api.py"]
        extras = {
            "src/api.py": {
                "exports": ["handle_request", "Router"],
            },
        }
        map_data = _make_map_data(files, reading_order_extras=extras)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        ctx = build_session_context(guide_dir, "src/api.py")
        output = ctx.format()

        assert "handle_request" in output
        assert "Router" in output

    def test_format_shows_imported_by(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/api.py"]
        extras = {
            "src/api.py": {
                "imported_by": ["src/app.py", "src/main.py"],
            },
        }
        map_data = _make_map_data(files, reading_order_extras=extras)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        ctx = build_session_context(guide_dir, "src/api.py")
        output = ctx.format()

        assert "src/app.py" in output
        assert "src/main.py" in output

    def test_format_no_deps_shows_no_deps_section(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        ctx = build_session_context(guide_dir, "src/config.py")
        output = ctx.format()

        # Should still be valid output, just no dependency section
        assert "src/config.py" in output

    def test_format_handles_missing_summary_in_deps(
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
                    # no summary
                },
            },
        )

        ctx = build_session_context(guide_dir, "src/api.py")
        output = ctx.format()

        assert "src/config.py" in output
        assert "(no summary)" in output


# --- Edge cases ---


class TestEdgeCases:
    """Edge cases for session priming."""

    def test_no_files_read_yet(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/api.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        ctx = build_session_context(guide_dir, "src/config.py")

        assert len(ctx.dependency_summaries) == 0
        assert len(ctx.general_summaries) == 0

    def test_current_file_not_in_its_own_summaries(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/api.py"]
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
                # api.py has been read previously but we're re-reading
                "src/api.py": {
                    "status": "flagged",
                    "note": "Re-review",
                    "summary": "API routes.",
                },
            },
        )

        ctx = build_session_context(guide_dir, "src/api.py")

        assert "src/api.py" not in ctx.dependency_summaries
        assert "src/api.py" not in ctx.general_summaries

    def test_file_not_in_reading_order_raises(
        self, tmp_path: Path,
    ) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        _setup_progress(guide_dir, map_data, map_hash)

        with pytest.raises(KeyError):
            build_session_context(guide_dir, "nonexistent.py")

    def test_missing_map_json_raises(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        guide_dir.mkdir(parents=True)
        # No map.json written

        with pytest.raises(FileNotFoundError):
            build_session_context(guide_dir, "src/config.py")

    def test_missing_progress_json_raises(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py"]
        map_data = _make_map_data(files)
        _write_map(guide_dir, map_data)
        # No progress.json created

        with pytest.raises(FileNotFoundError):
            build_session_context(guide_dir, "src/config.py")

    def test_many_files_general_summaries_are_compact(
        self, tmp_path: Path,
    ) -> None:
        """With many read files, general summaries still collected."""
        guide_dir = tmp_path / ".codebase-guide"
        files = [f"src/file_{i}.py" for i in range(20)]
        files.append("src/target.py")
        map_data = _make_map_data(files)
        map_hash = _write_map(guide_dir, map_data)
        updates: dict[str, dict[str, Any]] = {}
        for i in range(20):
            updates[f"src/file_{i}.py"] = {
                "status": "confirmed",
                "summary": f"File {i} summary.",
            }
        _setup_progress(
            guide_dir, map_data, map_hash, updates=updates,
        )

        ctx = build_session_context(guide_dir, "src/target.py")

        assert len(ctx.general_summaries) == 20
