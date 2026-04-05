"""Tests for the nlv CLI entry point."""

import pathlib
import subprocess
import sys

import pytest

from nlv.cli import main


class TestCLIEntryPoint:
    """Tests for `python -m nlv` and the main() function."""

    def test_main_with_path_runs_index(
        self, capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path,
    ) -> None:
        """Given a valid path argument, main() runs the index pipeline."""
        main([str(tmp_path)])
        captured = capsys.readouterr()
        # Empty dir produces "0 files" summary
        assert "0 files" in captured.out

    def test_main_with_python_files(
        self, capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path,
    ) -> None:
        """Given a directory with Python files, main() produces a summary."""
        (tmp_path / "main.py").write_text("x = 1\n")
        main([str(tmp_path)])
        captured = capsys.readouterr()
        assert "Indexed" in captured.out
        assert "/read-next" in captured.out

    def test_main_with_no_args_exits_with_error(self) -> None:
        """With no arguments, main() exits with a non-zero code."""
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code != 0

    def test_main_with_nonexistent_path_exits_with_error(self) -> None:
        """With a nonexistent path, main() exits with a non-zero code."""
        with pytest.raises(SystemExit) as exc_info:
            main(["/nonexistent/path"])
        assert exc_info.value.code != 0

    def test_module_invocation_runs_index(
        self, tmp_path: pathlib.Path,
    ) -> None:
        """`python -m nlv <path>` works as a module entry point."""
        result = subprocess.run(
            [sys.executable, "-m", "nlv", str(tmp_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        # Empty dir -> "0 files" message
        assert "0 files" in result.stdout

    def test_module_invocation_no_args_fails(self) -> None:
        """`python -m nlv` with no args exits non-zero."""
        result = subprocess.run(
            [sys.executable, "-m", "nlv"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0

    def test_nlv_package_is_importable(self) -> None:
        """The nlv package can be imported and has a version."""
        import nlv

        assert hasattr(nlv, "__version__")
        assert nlv.__version__ == "0.1.0"

    def test_console_script_entry_point(self, tmp_path: pathlib.Path) -> None:
        """The `nlv` console script works."""
        result = subprocess.run(
            ["nlv", str(tmp_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert "0 files" in result.stdout
