"""Tests for the file tree walker module."""

from __future__ import annotations

import pathlib

import pytest

from nlv.walker import SourceFile, walk_tree


@pytest.fixture()
def project(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal project tree for walker tests."""
    # Python source files
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("import os\n")
    (tmp_path / "src" / "utils.py").write_text("def helper(): ...\n")
    (tmp_path / "src" / "__init__.py").write_text("")

    # Test files
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_app(): ...\n")
    (tmp_path / "tests" / "conftest.py").write_text("import pytest\n")

    # Config file at root
    (tmp_path / "setup.py").write_text("")

    return tmp_path


class TestWalkTree:
    """Tests for walk_tree() collecting source files."""

    def test_collects_python_files(self, project: pathlib.Path) -> None:
        """walk_tree returns all .py files as SourceFile objects."""
        files = walk_tree(project, extensions={".py"})
        paths = {f.path for f in files}
        assert "src/app.py" in paths
        assert "src/utils.py" in paths
        assert "src/__init__.py" in paths

    def test_returns_source_file_objects(self, project: pathlib.Path) -> None:
        """Each result is a SourceFile with path and is_test fields."""
        files = walk_tree(project, extensions={".py"})
        for f in files:
            assert isinstance(f, SourceFile)
            assert isinstance(f.path, str)
            assert isinstance(f.is_test, bool)

    def test_paths_are_relative_to_root(self, project: pathlib.Path) -> None:
        """Returned paths are relative to the given root, using forward slashes."""
        files = walk_tree(project, extensions={".py"})
        for f in files:
            assert not pathlib.PurePosixPath(f.path).is_absolute()

    def test_filters_by_extension(self, project: pathlib.Path) -> None:
        """Only files with matching extensions are returned."""
        (project / "readme.md").write_text("# hello")
        (project / "data.json").write_text("{}")
        files = walk_tree(project, extensions={".py"})
        paths = {f.path for f in files}
        assert "readme.md" not in paths
        assert "data.json" not in paths
        # Python files are still collected
        assert "src/app.py" in paths


class TestTestFileDetection:
    """Tests for is_test flag on discovered files."""

    def test_test_prefix_detected(self, project: pathlib.Path) -> None:
        """Files named test_*.py are tagged as tests."""
        files = walk_tree(project, extensions={".py"})
        by_path = {f.path: f for f in files}
        assert by_path["tests/test_app.py"].is_test is True

    def test_test_suffix_detected(self, tmp_path: pathlib.Path) -> None:
        """Files named *_test.py are tagged as tests."""
        (tmp_path / "app_test.py").write_text("")
        files = walk_tree(tmp_path, extensions={".py"})
        by_path = {f.path: f for f in files}
        assert by_path["app_test.py"].is_test is True

    def test_conftest_detected(self, project: pathlib.Path) -> None:
        """conftest.py files are tagged as tests."""
        files = walk_tree(project, extensions={".py"})
        by_path = {f.path: f for f in files}
        assert by_path["tests/conftest.py"].is_test is True

    def test_files_in_tests_dir_detected(self, tmp_path: pathlib.Path) -> None:
        """Files inside a tests/ directory are tagged as tests."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "helpers.py").write_text("")
        files = walk_tree(tmp_path, extensions={".py"})
        by_path = {f.path: f for f in files}
        assert by_path["tests/helpers.py"].is_test is True

    def test_files_in_test_dir_detected(self, tmp_path: pathlib.Path) -> None:
        """Files inside a test/ (singular) directory are tagged as tests."""
        (tmp_path / "test").mkdir()
        (tmp_path / "test" / "check.py").write_text("")
        files = walk_tree(tmp_path, extensions={".py"})
        by_path = {f.path: f for f in files}
        assert by_path["test/check.py"].is_test is True

    def test_non_test_files_not_tagged(self, project: pathlib.Path) -> None:
        """Regular source files are not tagged as tests."""
        files = walk_tree(project, extensions={".py"})
        by_path = {f.path: f for f in files}
        assert by_path["src/app.py"].is_test is False
        assert by_path["src/utils.py"].is_test is False


class TestGitignoreRespect:
    """Tests for .gitignore pattern handling."""

    def test_respects_root_gitignore(self, tmp_path: pathlib.Path) -> None:
        """.gitignore patterns exclude matching files."""
        (tmp_path / ".gitignore").write_text("*.log\nbuild/\n")
        (tmp_path / "app.py").write_text("")
        (tmp_path / "debug.log").write_text("")
        (tmp_path / "build").mkdir()
        (tmp_path / "build" / "output.py").write_text("")

        files = walk_tree(tmp_path, extensions={".py", ".log"})
        paths = {f.path for f in files}
        assert "app.py" in paths
        assert "debug.log" not in paths
        assert "build/output.py" not in paths

    def test_respects_nested_gitignore(self, tmp_path: pathlib.Path) -> None:
        """Nested .gitignore files apply within their directory."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("")
        (tmp_path / "src" / "generated.py").write_text("")
        (tmp_path / "src" / ".gitignore").write_text("generated.py\n")

        files = walk_tree(tmp_path, extensions={".py"})
        paths = {f.path for f in files}
        assert "src/app.py" in paths
        assert "src/generated.py" not in paths

    def test_no_gitignore_still_works(self, project: pathlib.Path) -> None:
        """Walker works fine when no .gitignore exists."""
        files = walk_tree(project, extensions={".py"})
        assert len(files) > 0

    def test_nested_gitignore_does_not_leak_to_siblings(
        self, tmp_path: pathlib.Path,
    ) -> None:
        """A .gitignore in one directory should not affect sibling directories."""
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / ".gitignore").write_text("secret.py\n")
        (tmp_path / "a" / "secret.py").write_text("")
        (tmp_path / "b").mkdir()
        (tmp_path / "b" / "secret.py").write_text("")

        files = walk_tree(tmp_path, extensions={".py"})
        paths = {f.path for f in files}
        assert "a/secret.py" not in paths
        assert "b/secret.py" in paths


class TestDirectorySkipping:
    """Tests for skipping common non-source directories."""

    @pytest.mark.parametrize(
        "dirname",
        [
            "node_modules",
            "dist",
            "build",
            ".git",
            "__pycache__",
            "venv",
            ".venv",
            ".tox",
        ],
    )
    def test_skips_common_dirs(
        self, tmp_path: pathlib.Path, dirname: str,
    ) -> None:
        """Common non-source directories are always skipped."""
        (tmp_path / dirname).mkdir()
        (tmp_path / dirname / "file.py").write_text("")
        (tmp_path / "real.py").write_text("")

        files = walk_tree(tmp_path, extensions={".py"})
        paths = {f.path for f in files}
        assert f"{dirname}/file.py" not in paths
        assert "real.py" in paths


class TestSymlinkHandling:
    """Tests for symlink behavior."""

    def test_skips_symlinks_by_default(self, tmp_path: pathlib.Path) -> None:
        """Symlinked files are skipped by default."""
        (tmp_path / "real.py").write_text("")
        target = tmp_path / "real.py"
        link = tmp_path / "link.py"
        link.symlink_to(target)

        files = walk_tree(tmp_path, extensions={".py"})
        paths = {f.path for f in files}
        assert "real.py" in paths
        assert "link.py" not in paths

    def test_skips_symlinked_directories(self, tmp_path: pathlib.Path) -> None:
        """Symlinked directories are skipped."""
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        (real_dir / "module.py").write_text("")
        (tmp_path / "linked_dir").symlink_to(real_dir)

        files = walk_tree(tmp_path, extensions={".py"})
        paths = {f.path for f in files}
        assert "real_dir/module.py" in paths
        assert "linked_dir/module.py" not in paths


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_directory(self, tmp_path: pathlib.Path) -> None:
        """Empty directory returns empty list."""
        files = walk_tree(tmp_path, extensions={".py"})
        assert files == []

    def test_no_matching_extensions(self, tmp_path: pathlib.Path) -> None:
        """When no files match extensions, returns empty."""
        (tmp_path / "readme.md").write_text("")
        files = walk_tree(tmp_path, extensions={".py"})
        assert files == []

    def test_deterministic_order(self, project: pathlib.Path) -> None:
        """Results are sorted for deterministic output."""
        files1 = walk_tree(project, extensions={".py"})
        files2 = walk_tree(project, extensions={".py"})
        assert [f.path for f in files1] == [f.path for f in files2]
        # Verify actually sorted
        paths = [f.path for f in files1]
        assert paths == sorted(paths)

    def test_binary_files_excluded_by_extension(
        self, tmp_path: pathlib.Path,
    ) -> None:
        """Binary files are excluded via extension filtering."""
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        (tmp_path / "app.py").write_text("")
        files = walk_tree(tmp_path, extensions={".py"})
        paths = {f.path for f in files}
        assert "image.png" not in paths
        assert "app.py" in paths

    def test_raises_on_nonexistent_root(self, tmp_path: pathlib.Path) -> None:
        """Raises NotADirectoryError for nonexistent path."""
        with pytest.raises(NotADirectoryError):
            walk_tree(tmp_path / "nonexistent", extensions={".py"})

    def test_raises_on_file_root(self, tmp_path: pathlib.Path) -> None:
        """Raises NotADirectoryError when root is a file."""
        f = tmp_path / "file.py"
        f.write_text("")
        with pytest.raises(NotADirectoryError):
            walk_tree(f, extensions={".py"})

    def test_multiple_extensions(self, tmp_path: pathlib.Path) -> None:
        """Multiple extensions collect all matching file types."""
        (tmp_path / "app.py").write_text("")
        (tmp_path / "style.css").write_text("")
        (tmp_path / "readme.md").write_text("")
        files = walk_tree(tmp_path, extensions={".py", ".css"})
        paths = {f.path for f in files}
        assert "app.py" in paths
        assert "style.css" in paths
        assert "readme.md" not in paths
