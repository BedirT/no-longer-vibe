"""Tests for /read-status command output (BED-76).

Covers: progress display, per-status breakdown, layer completion,
next file in queue, flagged count, session count, average pace,
and edge cases (no progress, empty progress, all files read).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from nlv.progress import FileStatus, ProgressManager
from nlv.read_status import format_read_status


def _make_map_data(
    files: list[str] | None = None,
    layers: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a minimal map.json structure for testing."""
    if files is None:
        files = [
            "src/config.py",
            "src/models.py",
            "src/services.py",
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
            "features": {
                "description": "Business logic",
                "files": files[3:] if len(files) > 3 else [],
            },
        }
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
        "reading_order": [
            {
                "index": i,
                "path": f,
                "layer": _layer_for_file(f, layers),
            }
            for i, f in enumerate(files)
        ],
        "dependency_graph": {
            f: {"imports": [], "imported_by": []}
            for f in files
        },
    }


def _layer_for_file(
    filepath: str,
    layers: dict[str, dict[str, Any]],
) -> str:
    """Find which layer a file belongs to."""
    for layer_name, layer_data in layers.items():
        if filepath in layer_data.get("files", []):
            return layer_name
    return "unknown"


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
    updates: dict[str, dict[str, Any]] | None = None,
    sessions: int = 1,
) -> None:
    """Create progress.json and optionally apply file updates."""
    map_hash = _write_map(guide_dir, map_data)
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
    # Add extra sessions if needed (create already starts at 1)
    for _ in range(sessions - 1):
        mgr.start_session()


# --- Progress summary line ---


class TestProgressSummary:
    """The top-line progress fraction and percentage."""

    def test_shows_files_read_vs_total(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py", "c.py", "d.py"]
        map_data = _make_map_data(files)
        _setup_progress(
            guide_dir,
            map_data,
            updates={
                "a.py": {"status": "confirmed"},
                "b.py": {"status": "flagged", "note": "check"},
            },
        )
        output = format_read_status(guide_dir)
        assert "Progress: 2/4 files (50%)" in output

    def test_zero_progress(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data(["a.py", "b.py"])
        _setup_progress(guide_dir, map_data)
        output = format_read_status(guide_dir)
        assert "Progress: 0/2 files (0%)" in output

    def test_all_files_read(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py"]
        map_data = _make_map_data(files)
        _setup_progress(
            guide_dir,
            map_data,
            updates={
                "a.py": {"status": "confirmed"},
                "b.py": {"status": "confirmed"},
            },
        )
        output = format_read_status(guide_dir)
        assert "Progress: 2/2 files (100%)" in output


# --- Per-status breakdown ---


class TestStatusBreakdown:
    """Breakdown by confirmed/flagged/skimmed/unread."""

    def test_shows_all_four_statuses(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py", "c.py", "d.py"]
        map_data = _make_map_data(files)
        _setup_progress(
            guide_dir,
            map_data,
            updates={
                "a.py": {"status": "confirmed"},
                "b.py": {"status": "flagged", "note": "check"},
                "c.py": {"status": "skimmed"},
            },
        )
        output = format_read_status(guide_dir)
        assert "confirmed: 1" in output
        assert "flagged: 1" in output
        assert "skimmed: 1" in output
        assert "unread: 1" in output

    def test_all_unread(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py", "c.py"]
        map_data = _make_map_data(files)
        _setup_progress(guide_dir, map_data)
        output = format_read_status(guide_dir)
        assert "confirmed: 0" in output
        assert "flagged: 0" in output
        assert "skimmed: 0" in output
        assert "unread: 3" in output


# --- Current layer ---


class TestCurrentLayer:
    """Current layer and its completion percentage."""

    def test_shows_current_layer_name(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["src/config.py", "src/models.py", "src/app.py"]
        layers = {
            "foundation": {
                "description": "No deps",
                "files": ["src/config.py"],
            },
            "core": {
                "description": "Core",
                "files": ["src/models.py"],
            },
            "features": {
                "description": "Features",
                "files": ["src/app.py"],
            },
        }
        map_data = _make_map_data(files, layers)
        # foundation done, currently on core
        _setup_progress(
            guide_dir,
            map_data,
            updates={"src/config.py": {"status": "confirmed"}},
        )
        output = format_read_status(guide_dir)
        assert "Current layer: core" in output

    def test_shows_layer_completion_percentage(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py", "c.py", "d.py"]
        layers = {
            "foundation": {
                "description": "No deps",
                "files": ["a.py", "b.py"],
            },
            "core": {
                "description": "Core",
                "files": ["c.py", "d.py"],
            },
        }
        map_data = _make_map_data(files, layers)
        _setup_progress(
            guide_dir,
            map_data,
            updates={"a.py": {"status": "confirmed"}},
        )
        output = format_read_status(guide_dir)
        assert "Current layer: foundation (50% complete)" in output

    def test_all_layers_complete(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py"]
        layers = {
            "foundation": {
                "description": "No deps",
                "files": ["a.py", "b.py"],
            },
        }
        map_data = _make_map_data(files, layers)
        _setup_progress(
            guide_dir,
            map_data,
            updates={
                "a.py": {"status": "confirmed"},
                "b.py": {"status": "confirmed"},
            },
        )
        output = format_read_status(guide_dir)
        assert "All layers complete" in output


# --- Next file ---


class TestNextFile:
    """Next file in reading order queue."""

    def test_shows_next_unread_file(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py", "c.py"]
        map_data = _make_map_data(files)
        _setup_progress(
            guide_dir,
            map_data,
            updates={"a.py": {"status": "confirmed"}},
        )
        output = format_read_status(guide_dir)
        assert "Next file: b.py" in output

    def test_no_next_file_when_all_read(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py"]
        map_data = _make_map_data(files)
        _setup_progress(
            guide_dir,
            map_data,
            updates={"a.py": {"status": "confirmed"}},
        )
        output = format_read_status(guide_dir)
        assert "Next file: (none" in output


# --- Flagged count ---


class TestFlaggedCount:
    """Flagged files awaiting second pass."""

    def test_shows_flagged_count(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py", "c.py"]
        map_data = _make_map_data(files)
        _setup_progress(
            guide_dir,
            map_data,
            updates={
                "a.py": {
                    "status": "flagged",
                    "note": "check this",
                },
                "b.py": {
                    "status": "flagged",
                    "note": "and this",
                },
            },
        )
        output = format_read_status(guide_dir)
        assert "Flagged files awaiting second pass: 2" in output

    def test_zero_flagged(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data(["a.py"])
        _setup_progress(guide_dir, map_data)
        output = format_read_status(guide_dir)
        assert "Flagged files awaiting second pass: 0" in output


# --- Session and pace ---


class TestSessionAndPace:
    """Session count and average pace."""

    def test_shows_session_count(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py", "c.py"]
        map_data = _make_map_data(files)
        _setup_progress(guide_dir, map_data, sessions=3)
        output = format_read_status(guide_dir)
        assert "Sessions: 3" in output

    def test_shows_average_pace(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py", "c.py", "d.py"]
        map_data = _make_map_data(files)
        _setup_progress(
            guide_dir,
            map_data,
            updates={
                "a.py": {"status": "confirmed"},
                "b.py": {"status": "confirmed"},
                "c.py": {"status": "flagged", "note": "review"},
            },
            sessions=3,
        )
        output = format_read_status(guide_dir)
        # 3 files read across 3 sessions = ~1 file/session
        assert "Avg pace: ~1 files/session" in output

    def test_pace_rounds_to_nearest_integer(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["a.py", "b.py", "c.py", "d.py", "e.py", "f.py", "g.py"]
        map_data = _make_map_data(files)
        _setup_progress(
            guide_dir,
            map_data,
            updates={
                "a.py": {"status": "confirmed"},
                "b.py": {"status": "confirmed"},
                "c.py": {"status": "confirmed"},
                "d.py": {"status": "confirmed"},
                "e.py": {"status": "confirmed"},
                "f.py": {"status": "confirmed"},
                "g.py": {"status": "skimmed"},
            },
            sessions=2,
        )
        output = format_read_status(guide_dir)
        # 7 files / 2 sessions = 3.5 -> ~4 (rounded)
        assert "Avg pace: ~4 files/session" in output

    def test_zero_files_read_shows_zero_pace(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data(["a.py"])
        _setup_progress(guide_dir, map_data, sessions=2)
        output = format_read_status(guide_dir)
        assert "Avg pace: ~0 files/session" in output


# --- Edge cases ---


class TestEdgeCases:
    """Edge cases: no progress file, empty progress, etc."""

    def test_no_progress_file(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        # Write map but no progress
        map_data = _make_map_data()
        _write_map(guide_dir, map_data)
        output = format_read_status(guide_dir)
        assert "/read-next" in output

    def test_no_map_file(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        guide_dir.mkdir(parents=True, exist_ok=True)
        output = format_read_status(guide_dir)
        assert "/read-index" in output

    def test_empty_map_no_files(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        map_data = _make_map_data([])
        _setup_progress(guide_dir, map_data)
        output = format_read_status(guide_dir)
        assert "Progress: 0/0 files" in output

    def test_single_file_project(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        files = ["main.py"]
        layers = {
            "foundation": {
                "description": "Single file",
                "files": ["main.py"],
            },
        }
        map_data = _make_map_data(files, layers)
        _setup_progress(guide_dir, map_data)
        output = format_read_status(guide_dir)
        assert "Progress: 0/1 files (0%)" in output
        assert "Next file: main.py" in output


# --- Output format ---


class TestOutputFormat:
    """The output matches the expected format from the SPEC."""

    def test_output_structure(self, tmp_path: Path) -> None:
        """Full output matches expected format structure."""
        guide_dir = tmp_path / ".codebase-guide"
        files = [
            "src/config.py",
            "src/models.py",
            "src/services.py",
            "src/app.py",
        ]
        layers = {
            "foundation": {
                "description": "No deps",
                "files": ["src/config.py"],
            },
            "core": {
                "description": "Core",
                "files": ["src/models.py", "src/services.py"],
            },
            "features": {
                "description": "Features",
                "files": ["src/app.py"],
            },
        }
        map_data = _make_map_data(files, layers)
        _setup_progress(
            guide_dir,
            map_data,
            updates={
                "src/config.py": {"status": "confirmed"},
                "src/models.py": {
                    "status": "flagged",
                    "note": "check imports",
                },
            },
            sessions=2,
        )
        output = format_read_status(guide_dir)
        lines = output.strip().split("\n")

        # First line: progress summary
        assert lines[0].startswith("Progress:")

        # Status breakdown (indented)
        status_lines = [
            ln for ln in lines if ln.strip().startswith(
                ("confirmed:", "flagged:", "skimmed:", "unread:")
            )
        ]
        assert len(status_lines) == 4

        # Current layer line exists
        layer_lines = [
            ln for ln in lines if "Current layer:" in ln
        ]
        assert len(layer_lines) == 1

        # Next file line exists
        next_lines = [
            ln for ln in lines if "Next file:" in ln
        ]
        assert len(next_lines) == 1

        # Flagged awaiting line exists
        flagged_lines = [
            ln for ln in lines if "Flagged files awaiting" in ln
        ]
        assert len(flagged_lines) == 1

        # Sessions line exists
        session_lines = [
            ln for ln in lines if "Sessions:" in ln
        ]
        assert len(session_lines) == 1
