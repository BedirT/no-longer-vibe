"""Tests for the nlv CLI entry point (BED-71).

Tests cover argument parsing, help text, verbose mode, the full pipeline
integration, summary output, and exit codes.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from unittest.mock import patch

import pytest

from nlv.cli import main

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_project(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal Python project for end-to-end tests."""
    # config.py — foundation, no imports
    (tmp_path / "config.py").write_text(
        "DB_URL = 'sqlite:///db.sqlite'\n", encoding="utf-8",
    )
    # models.py — imports config
    (tmp_path / "models.py").write_text(
        "from config import DB_URL\n\nclass User:\n    pass\n",
        encoding="utf-8",
    )
    # main.py — entry point, imports models
    (tmp_path / "main.py").write_text(
        'from models import User\n\nif __name__ == "__main__":\n    pass\n',
        encoding="utf-8",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


class TestArgumentParsing:
    """Tests for argparse-based argument parsing."""

    def test_default_path_is_cwd(
        self, sample_project: pathlib.Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """With no path argument, main() defaults to current directory."""
        with patch("os.getcwd", return_value=str(sample_project)):
            main([])
        captured = capsys.readouterr()
        assert "Indexed" in captured.out

    def test_explicit_path_argument(
        self, sample_project: pathlib.Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An explicit path argument indexes that directory."""
        main([str(sample_project)])
        captured = capsys.readouterr()
        assert "Indexed" in captured.out

    def test_nonexistent_path_exits_with_error(self) -> None:
        """A nonexistent path exits with code 1."""
        with pytest.raises(SystemExit) as exc_info:
            main(["/nonexistent/path"])
        assert exc_info.value.code == 1

    def test_file_path_not_directory_exits_with_error(
        self, tmp_path: pathlib.Path,
    ) -> None:
        """A file (not a directory) exits with code 1."""
        f = tmp_path / "file.txt"
        f.write_text("hello", encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            main([str(f)])
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Help flag
# ---------------------------------------------------------------------------


class TestHelpFlag:
    """Tests for --help output."""

    def test_help_flag_shows_usage(self) -> None:
        """--help prints usage info and exits 0."""
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_help_contains_description(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--help output mentions nlv's purpose."""
        with pytest.raises(SystemExit):
            main(["--help"])
        captured = capsys.readouterr()
        assert "nlv" in captured.out.lower() or "codebase" in captured.out.lower()


# ---------------------------------------------------------------------------
# Verbose flag
# ---------------------------------------------------------------------------


class TestVerboseFlag:
    """Tests for --verbose output."""

    def test_verbose_enables_debug_logging(
        self,
        sample_project: pathlib.Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--verbose flag sets logging level to DEBUG."""
        import logging

        main(["--verbose", str(sample_project)])
        # After main runs with --verbose, the nlv logger should be DEBUG
        nlv_logger = logging.getLogger("nlv")
        assert nlv_logger.level == logging.DEBUG


# ---------------------------------------------------------------------------
# Full pipeline integration
# ---------------------------------------------------------------------------


class TestPipelineIntegration:
    """Tests for the full pipeline: walk, parse, graph, classify, sort, output."""

    def test_produces_map_json(
        self, sample_project: pathlib.Path,
    ) -> None:
        """Running main() creates .codebase-guide/map.json."""
        main([str(sample_project)])
        map_path = sample_project / ".codebase-guide" / "map.json"
        assert map_path.exists()

    def test_map_json_is_valid(
        self, sample_project: pathlib.Path,
    ) -> None:
        """The generated map.json is valid JSON with expected keys."""
        main([str(sample_project)])
        map_path = sample_project / ".codebase-guide" / "map.json"
        data = json.loads(map_path.read_text(encoding="utf-8"))
        assert "version" in data
        assert "total_files" in data
        assert "layers" in data
        assert "reading_order" in data
        assert "dependency_graph" in data
        assert "content_hashes" in data

    def test_map_json_total_files(
        self, sample_project: pathlib.Path,
    ) -> None:
        """total_files matches the number of .py files discovered."""
        main([str(sample_project)])
        map_path = sample_project / ".codebase-guide" / "map.json"
        data = json.loads(map_path.read_text(encoding="utf-8"))
        assert data["total_files"] == 3

    def test_map_json_has_all_five_layers(
        self, sample_project: pathlib.Path,
    ) -> None:
        """All five layer keys are present in map.json."""
        main([str(sample_project)])
        map_path = sample_project / ".codebase-guide" / "map.json"
        data = json.loads(map_path.read_text(encoding="utf-8"))
        expected_layers = {"foundation", "core", "features", "integration", "entry"}
        assert set(data["layers"].keys()) == expected_layers


# ---------------------------------------------------------------------------
# Summary output
# ---------------------------------------------------------------------------


class TestSummaryOutput:
    """Tests for the printed summary after indexing."""

    def test_summary_shows_indexed_count(
        self, sample_project: pathlib.Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Summary line shows 'Indexed N files across 5 layers'."""
        main([str(sample_project)])
        captured = capsys.readouterr()
        assert "Indexed 3 files across 5 layers" in captured.out

    def test_summary_shows_layer_counts(
        self, sample_project: pathlib.Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Summary includes per-layer file counts."""
        main([str(sample_project)])
        captured = capsys.readouterr()
        assert "foundation:" in captured.out
        assert "core:" in captured.out
        assert "features:" in captured.out
        assert "integration:" in captured.out
        assert "entry:" in captured.out

    def test_summary_shows_output_path(
        self, sample_project: pathlib.Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Summary includes the output file path."""
        main([str(sample_project)])
        captured = capsys.readouterr()
        assert ".codebase-guide/map.json" in captured.out


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


class TestExitCodes:
    """Tests for exit codes."""

    def test_success_exit_code(
        self, sample_project: pathlib.Path,
    ) -> None:
        """Successful run returns exit code 0 (no SystemExit raised)."""
        # main() should not raise SystemExit on success
        main([str(sample_project)])

    def test_error_exit_code_nonexistent_path(self) -> None:
        """Nonexistent path exits with code 1."""
        with pytest.raises(SystemExit) as exc_info:
            main(["/nonexistent/path"])
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Console script / module invocation
# ---------------------------------------------------------------------------


class TestEntryPoints:
    """Tests for the nlv console script and python -m nlv."""

    def test_module_invocation(
        self, sample_project: pathlib.Path,
    ) -> None:
        """`python -m nlv <path>` works as a module entry point."""
        result = subprocess.run(
            [sys.executable, "-m", "nlv", str(sample_project)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert "Indexed" in result.stdout

    def test_module_invocation_no_args_uses_cwd(
        self, sample_project: pathlib.Path,
    ) -> None:
        """`python -m nlv` with no args uses the cwd."""
        result = subprocess.run(
            [sys.executable, "-m", "nlv"],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(sample_project),
        )
        assert result.returncode == 0

    def test_console_script_entry_point(
        self, sample_project: pathlib.Path,
    ) -> None:
        """The `nlv` console script works."""
        result = subprocess.run(
            ["nlv", str(sample_project)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert "Indexed" in result.stdout

    def test_nlv_package_is_importable(self) -> None:
        """The nlv package can be imported and has a version."""
        import nlv

        assert hasattr(nlv, "__version__")
        assert nlv.__version__ == "0.1.0"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_directory(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An empty directory produces 0 files and still writes map.json."""
        main([str(tmp_path)])
        captured = capsys.readouterr()
        assert "Indexed 0 files" in captured.out
        map_path = tmp_path / ".codebase-guide" / "map.json"
        assert map_path.exists()

    def test_directory_with_non_python_files_only(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Directory with only non-.py files produces 0 files."""
        (tmp_path / "readme.md").write_text("# Hello", encoding="utf-8")
        (tmp_path / "data.json").write_text("{}", encoding="utf-8")
        main([str(tmp_path)])
        captured = capsys.readouterr()
        assert "Indexed 0 files" in captured.out
