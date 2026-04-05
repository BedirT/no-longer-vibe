"""Tests for the /read-index pipeline orchestrator (BED-74).

Covers: full pipeline execution, map.json output, progress.json init,
summary formatting, error handling.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nlv.index import IndexResult, format_summary, run_index
from nlv.layers import Layer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_python_project(root: Path) -> None:
    """Create a minimal multi-file Python project for testing."""
    src = root / "src"
    src.mkdir()
    (src / "__init__.py").write_text("")
    (src / "config.py").write_text(
        "DB_URL = 'sqlite:///test.db'\n"
        "DEBUG = True\n"
    )
    (src / "models.py").write_text(
        "from src.config import DB_URL\n"
        "\n"
        "class User:\n"
        "    pass\n"
    )
    (src / "app.py").write_text(
        "from src.config import DB_URL\n"
        "from src.models import User\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    pass\n"
    )
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_models.py").write_text(
        "from src.models import User\n"
        "\n"
        "def test_user():\n"
        "    assert User\n"
    )


def _create_single_file_project(root: Path) -> None:
    """Create a project with a single Python file."""
    (root / "main.py").write_text(
        'if __name__ == "__main__":\n'
        '    print("hello")\n'
    )


def _read_map(root: Path) -> dict[str, Any]:
    """Load .codebase-guide/map.json."""
    map_path = root / ".codebase-guide" / "map.json"
    return json.loads(map_path.read_text())  # type: ignore[no-any-return]


def _read_progress(root: Path) -> dict[str, Any]:
    """Load .codebase-guide/progress.json."""
    progress_path = root / ".codebase-guide" / "progress.json"
    return json.loads(progress_path.read_text())  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------


class TestRunIndex:
    """Tests for the run_index() pipeline orchestrator."""

    def test_returns_index_result(self, tmp_path: Path) -> None:
        """run_index returns an IndexResult dataclass."""
        _create_python_project(tmp_path)
        result = run_index(tmp_path)
        assert isinstance(result, IndexResult)

    def test_discovers_python_files(self, tmp_path: Path) -> None:
        """run_index finds all Python source files."""
        _create_python_project(tmp_path)
        result = run_index(tmp_path)
        assert result.total_files > 0

    def test_assigns_layers(self, tmp_path: Path) -> None:
        """run_index assigns files to architectural layers."""
        _create_python_project(tmp_path)
        result = run_index(tmp_path)
        # Every layer key should be present
        for layer in Layer:
            assert layer in result.layer_counts

    def test_computes_reading_order(self, tmp_path: Path) -> None:
        """run_index computes a reading order with entries."""
        _create_python_project(tmp_path)
        result = run_index(tmp_path)
        assert result.total_files == len(result.reading_order)


# ---------------------------------------------------------------------------
# map.json output
# ---------------------------------------------------------------------------


class TestMapJsonOutput:
    """Tests for map.json generation via run_index."""

    def test_writes_map_json(self, tmp_path: Path) -> None:
        """run_index creates .codebase-guide/map.json."""
        _create_python_project(tmp_path)
        run_index(tmp_path)
        assert (tmp_path / ".codebase-guide" / "map.json").exists()

    def test_map_json_has_version(self, tmp_path: Path) -> None:
        """map.json contains a version field."""
        _create_python_project(tmp_path)
        run_index(tmp_path)
        data = _read_map(tmp_path)
        assert data["version"] == "1.0.0"

    def test_map_json_has_repo_root(self, tmp_path: Path) -> None:
        """map.json contains the repo root path."""
        _create_python_project(tmp_path)
        run_index(tmp_path)
        data = _read_map(tmp_path)
        assert data["repo_root"] == str(tmp_path.resolve())

    def test_map_json_has_content_hashes(self, tmp_path: Path) -> None:
        """map.json includes content hashes for all files."""
        _create_python_project(tmp_path)
        run_index(tmp_path)
        data = _read_map(tmp_path)
        assert isinstance(data["content_hashes"], dict)
        assert len(data["content_hashes"]) > 0

    def test_map_json_has_layers(self, tmp_path: Path) -> None:
        """map.json has a layers object with descriptions and files."""
        _create_python_project(tmp_path)
        run_index(tmp_path)
        data = _read_map(tmp_path)
        assert "layers" in data
        for layer_data in data["layers"].values():
            assert "description" in layer_data
            assert "files" in layer_data

    def test_map_json_has_reading_order(self, tmp_path: Path) -> None:
        """map.json has a reading_order array with entries."""
        _create_python_project(tmp_path)
        run_index(tmp_path)
        data = _read_map(tmp_path)
        assert isinstance(data["reading_order"], list)
        assert len(data["reading_order"]) > 0
        entry = data["reading_order"][0]
        assert "index" in entry
        assert "path" in entry
        assert "layer" in entry

    def test_map_json_has_dependency_graph(self, tmp_path: Path) -> None:
        """map.json has a dependency_graph object."""
        _create_python_project(tmp_path)
        run_index(tmp_path)
        data = _read_map(tmp_path)
        assert "dependency_graph" in data
        for node_data in data["dependency_graph"].values():
            assert "imports" in node_data
            assert "imported_by" in node_data

    def test_map_json_has_total_files(self, tmp_path: Path) -> None:
        """map.json includes total_files count."""
        _create_python_project(tmp_path)
        run_index(tmp_path)
        data = _read_map(tmp_path)
        assert "total_files" in data
        assert data["total_files"] > 0

    def test_map_json_deterministic(self, tmp_path: Path) -> None:
        """Running index twice on same project produces identical map.json."""
        _create_python_project(tmp_path)
        run_index(tmp_path)
        data1 = _read_map(tmp_path)
        run_index(tmp_path)
        data2 = _read_map(tmp_path)
        # generated_at will differ, so compare everything else
        data1.pop("generated_at")
        data2.pop("generated_at")
        assert data1 == data2


# ---------------------------------------------------------------------------
# progress.json initialization
# ---------------------------------------------------------------------------


class TestProgressInit:
    """Tests for progress.json initialization after indexing."""

    def test_creates_progress_json(self, tmp_path: Path) -> None:
        """run_index creates .codebase-guide/progress.json."""
        _create_python_project(tmp_path)
        run_index(tmp_path)
        assert (tmp_path / ".codebase-guide" / "progress.json").exists()

    def test_progress_has_all_files_as_unread(self, tmp_path: Path) -> None:
        """All files in progress.json start as unread."""
        _create_python_project(tmp_path)
        run_index(tmp_path)
        data = _read_progress(tmp_path)
        for entry in data["files"].values():
            assert entry["status"] == "unread"

    def test_progress_stats_match_total(self, tmp_path: Path) -> None:
        """Progress stats total matches total_files in map.json."""
        _create_python_project(tmp_path)
        run_index(tmp_path)
        progress = _read_progress(tmp_path)
        map_data = _read_map(tmp_path)
        assert progress["stats"]["total"] == map_data["total_files"]

    def test_re_index_overwrites_progress(self, tmp_path: Path) -> None:
        """Re-running index overwrites progress.json (fresh start)."""
        _create_python_project(tmp_path)
        run_index(tmp_path)
        assert (tmp_path / ".codebase-guide" / "progress.json").exists()
        # Run again -- should not error
        run_index(tmp_path)
        assert (tmp_path / ".codebase-guide" / "progress.json").exists()

    def test_progress_has_map_hash(self, tmp_path: Path) -> None:
        """progress.json contains a map_hash field."""
        _create_python_project(tmp_path)
        run_index(tmp_path)
        data = _read_progress(tmp_path)
        assert "map_hash" in data
        assert len(data["map_hash"]) > 0


# ---------------------------------------------------------------------------
# Summary formatting
# ---------------------------------------------------------------------------


class TestSummaryFormatting:
    """Tests for the human-readable summary in IndexResult."""

    def test_summary_contains_total_files(self, tmp_path: Path) -> None:
        """Summary mentions total file count."""
        _create_python_project(tmp_path)
        result = run_index(tmp_path)
        assert str(result.total_files) in result.summary

    def test_summary_contains_layer_names(self, tmp_path: Path) -> None:
        """Summary mentions each layer that has files."""
        _create_python_project(tmp_path)
        result = run_index(tmp_path)
        for layer in Layer:
            if result.layer_counts[layer] > 0:
                assert layer.value in result.summary

    def test_summary_ends_with_next_instruction(
        self, tmp_path: Path,
    ) -> None:
        """Summary ends with instructions to run /read-next."""
        _create_python_project(tmp_path)
        result = run_index(tmp_path)
        assert "/read-next" in result.summary

    def test_summary_single_file(self, tmp_path: Path) -> None:
        """Summary works correctly for a single-file project."""
        _create_single_file_project(tmp_path)
        result = run_index(tmp_path)
        assert "1 file" in result.summary

    def test_format_summary_with_zero_files(self) -> None:
        """format_summary handles zero files gracefully."""
        layer_counts = {layer: 0 for layer in Layer}
        summary = format_summary(0, layer_counts)
        assert "0 files" in summary


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for error cases in run_index."""

    def test_nonexistent_path_raises(self) -> None:
        """run_index raises NotADirectoryError for a nonexistent path."""
        with pytest.raises(NotADirectoryError):
            run_index(Path("/nonexistent/path"))

    def test_empty_directory_returns_zero_files(
        self, tmp_path: Path,
    ) -> None:
        """An empty directory produces zero files (no crash)."""
        result = run_index(tmp_path)
        assert result.total_files == 0

    def test_empty_directory_summary(self, tmp_path: Path) -> None:
        """An empty directory gets a helpful summary."""
        result = run_index(tmp_path)
        assert "0 files" in result.summary

    def test_file_with_syntax_error_does_not_crash(
        self, tmp_path: Path,
    ) -> None:
        """A file with a syntax error is handled gracefully."""
        (tmp_path / "bad.py").write_text("def broken(\n")
        (tmp_path / "good.py").write_text("x = 1\n")
        result = run_index(tmp_path)
        # Should still index at least the good file
        assert result.total_files >= 1
