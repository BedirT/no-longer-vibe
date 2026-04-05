"""Tests for the nlv CLI entry point."""

import pathlib
import subprocess
import sys

import pytest

from nlv.cli import main


class TestCLIEntryPoint:
    """Tests for `python -m nlv` and the main() function."""

    def test_main_with_path_prints_not_implemented(
        self, capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path,
    ) -> None:
        """Given a valid path argument, main() prints 'not yet implemented.'"""
        main([str(tmp_path)])
        captured = capsys.readouterr()
        assert captured.out.strip() == "not yet implemented."

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

    def test_module_invocation_prints_not_implemented(
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
        assert result.stdout.strip() == "not yet implemented."

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
        assert result.stdout.strip() == "not yet implemented."
