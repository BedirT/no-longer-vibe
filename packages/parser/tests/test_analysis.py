"""Tests for entry point detection and complexity scoring (BED-67).

Tests the detect_entry_point() and compute_complexity() functions that
feed into reading order and map.json generation.
"""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from nlv.analysis import (
    ComplexityLevel,
    ComplexityResult,
    compute_complexity,
    detect_entry_point,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_ROOT = pathlib.Path("/fake/project")


@pytest.fixture()
def tmp_py(tmp_path: pathlib.Path) -> pathlib.Path:
    """Return the tmp_path as the project root for file-based tests."""
    return tmp_path


def _write(root: pathlib.Path, name: str, content: str) -> pathlib.Path:
    """Write a Python file with dedented content."""
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content))
    return p


# ===================================================================
# Entry point detection — AST-based
# ===================================================================


class TestNameMainGuard:
    """Files with if __name__ == '__main__' are entry points."""

    def test_standard_guard(self, tmp_py: pathlib.Path) -> None:
        _write(tmp_py, "app.py", """\
            import sys

            def main():
                pass

            if __name__ == "__main__":
                main()
        """)
        assert detect_entry_point(tmp_py / "app.py", importers=set()) is True

    def test_double_quoted_guard(self, tmp_py: pathlib.Path) -> None:
        _write(tmp_py, "run.py", """\
            if __name__ == '__main__':
                print("hello")
        """)
        assert detect_entry_point(tmp_py / "run.py", importers=set()) is True

    def test_no_guard(self, tmp_py: pathlib.Path) -> None:
        _write(tmp_py, "lib.py", """\
            def helper():
                return 42
        """)
        assert detect_entry_point(tmp_py / "lib.py", importers=set()) is False

    def test_guard_in_function_body_not_top_level(
        self, tmp_py: pathlib.Path,
    ) -> None:
        """A __name__ check nested inside a function is NOT an entry point."""
        _write(tmp_py, "nested.py", """\
            def run():
                if __name__ == "__main__":
                    pass
        """)
        assert detect_entry_point(
            tmp_py / "nested.py", importers=set(),
        ) is False


# ===================================================================
# Entry point detection — filename patterns
# ===================================================================


class TestEntryPointFilePatterns:
    """Files matching common entry point naming patterns."""

    @pytest.mark.parametrize(
        "filename",
        ["main.py", "__main__.py", "app.py", "server.py", "cli.py"],
    )
    def test_common_entry_filenames(
        self, tmp_py: pathlib.Path, filename: str,
    ) -> None:
        _write(tmp_py, filename, """\
            print("running")
        """)
        assert detect_entry_point(
            tmp_py / filename, importers=set(),
        ) is True

    def test_non_entry_filename(self, tmp_py: pathlib.Path) -> None:
        _write(tmp_py, "utils.py", """\
            def helper():
                pass
        """)
        assert detect_entry_point(
            tmp_py / "utils.py", importers=set(),
        ) is False


# ===================================================================
# Entry point detection — top-level side effects
# ===================================================================


class TestTopLevelSideEffects:
    """Files with top-level executable statements (not just defs/imports)."""

    def test_top_level_function_call(self, tmp_py: pathlib.Path) -> None:
        """A file that calls a function at module level has side effects."""
        _write(tmp_py, "run.py", """\
            from app import main
            main()
        """)
        # Has side effects, but not an entry-pattern name.
        # Entry detection is: guard OR pattern OR (no importers + side effects).
        # This file has importers, so side effects alone don't make it entry.
        assert detect_entry_point(
            tmp_py / "run.py", importers={"other.py"},
        ) is False

    def test_graph_leaf_with_side_effects(
        self, tmp_py: pathlib.Path,
    ) -> None:
        """A file with no importers AND side effects is an entry point."""
        _write(tmp_py, "bootstrap.py", """\
            import logging
            logging.basicConfig()
            setup_database()
        """)
        assert detect_entry_point(
            tmp_py / "bootstrap.py", importers=set(),
        ) is True

    def test_graph_leaf_without_side_effects(
        self, tmp_py: pathlib.Path,
    ) -> None:
        """A file with no importers but only defs/imports is NOT entry."""
        _write(tmp_py, "types.py", """\
            from typing import TypeVar

            T = TypeVar("T")

            class MyType:
                pass

            def helper():
                pass
        """)
        assert detect_entry_point(
            tmp_py / "types.py", importers=set(),
        ) is False

    def test_pure_imports_no_side_effects(
        self, tmp_py: pathlib.Path,
    ) -> None:
        """A file with only import statements has no side effects."""
        _write(tmp_py, "imports_only.py", """\
            import os
            import sys
            from pathlib import Path
        """)
        assert detect_entry_point(
            tmp_py / "imports_only.py", importers=set(),
        ) is False


# ===================================================================
# Entry point detection — pyproject.toml scripts
# ===================================================================


class TestPyprojectScripts:
    """Files referenced in pyproject.toml scripts sections."""

    def test_project_scripts_entry(self, tmp_py: pathlib.Path) -> None:
        _write(tmp_py, "cli_mod.py", """\
            def main():
                pass
        """)
        scripts = {"my-tool": "cli_mod:main"}
        assert detect_entry_point(
            tmp_py / "cli_mod.py",
            importers={"other.py"},
            pyproject_scripts=scripts,
        ) is True

    def test_poetry_scripts_entry(self, tmp_py: pathlib.Path) -> None:
        _write(tmp_py, "entry.py", """\
            def run():
                pass
        """)
        scripts = {"tool": "entry:run"}
        assert detect_entry_point(
            tmp_py / "entry.py",
            importers=set(),
            pyproject_scripts=scripts,
        ) is True

    def test_not_in_scripts(self, tmp_py: pathlib.Path) -> None:
        _write(tmp_py, "lib.py", """\
            def helper():
                pass
        """)
        scripts = {"tool": "entry:run"}
        assert detect_entry_point(
            tmp_py / "lib.py",
            importers=set(),
            pyproject_scripts=scripts,
        ) is False


# ===================================================================
# Entry point detection — edge cases
# ===================================================================


class TestEntryPointEdgeCases:
    """Edge cases for entry point detection."""

    def test_empty_file(self, tmp_py: pathlib.Path) -> None:
        _write(tmp_py, "empty.py", "")
        assert detect_entry_point(
            tmp_py / "empty.py", importers=set(),
        ) is False

    def test_syntax_error_returns_false(self, tmp_py: pathlib.Path) -> None:
        """Files with syntax errors should not crash, return False."""
        _write(tmp_py, "bad.py", """\
            def broken(
        """)
        assert detect_entry_point(
            tmp_py / "bad.py", importers=set(),
        ) is False

    def test_nonexistent_file_raises(self, tmp_py: pathlib.Path) -> None:
        with pytest.raises(FileNotFoundError):
            detect_entry_point(
                tmp_py / "missing.py", importers=set(),
            )


# ===================================================================
# Complexity scoring
# ===================================================================


class TestComplexityResult:
    """Tests for the ComplexityResult data type."""

    def test_fields(self) -> None:
        result = ComplexityResult(
            line_count=100,
            function_count=5,
            max_nesting=3,
            complexity=ComplexityLevel.MEDIUM,
        )
        assert result.line_count == 100
        assert result.function_count == 5
        assert result.max_nesting == 3
        assert result.complexity == ComplexityLevel.MEDIUM

    def test_frozen(self) -> None:
        result = ComplexityResult(
            line_count=10,
            function_count=1,
            max_nesting=1,
            complexity=ComplexityLevel.LOW,
        )
        with pytest.raises(AttributeError):
            result.line_count = 99  # type: ignore[misc]


class TestComplexityLevels:
    """All three complexity levels exist."""

    def test_all_levels(self) -> None:
        assert {lv.value for lv in ComplexityLevel} == {
            "low", "medium", "high",
        }


# ===================================================================
# Complexity scoring — line counting
# ===================================================================


class TestLineCount:
    """Line count excludes blank lines and comments."""

    def test_counts_code_lines_only(self, tmp_py: pathlib.Path) -> None:
        _write(tmp_py, "mixed.py", """\
            # A comment
            import os

            def hello():
                # inline comment
                return "hi"

        """)
        result = compute_complexity(tmp_py / "mixed.py")
        # Lines: import os, def hello():, return "hi" => 3
        assert result.line_count == 3

    def test_empty_file_zero_lines(self, tmp_py: pathlib.Path) -> None:
        _write(tmp_py, "empty.py", "")
        result = compute_complexity(tmp_py / "empty.py")
        assert result.line_count == 0


# ===================================================================
# Complexity scoring — function counting
# ===================================================================


class TestFunctionCount:
    """Counts function and method declarations."""

    def test_counts_functions(self, tmp_py: pathlib.Path) -> None:
        _write(tmp_py, "funcs.py", """\
            def foo():
                pass

            def bar():
                pass

            async def baz():
                pass
        """)
        result = compute_complexity(tmp_py / "funcs.py")
        assert result.function_count == 3

    def test_counts_methods(self, tmp_py: pathlib.Path) -> None:
        _write(tmp_py, "cls.py", """\
            class MyClass:
                def __init__(self):
                    pass

                def method(self):
                    pass
        """)
        result = compute_complexity(tmp_py / "cls.py")
        assert result.function_count == 2

    def test_no_functions(self, tmp_py: pathlib.Path) -> None:
        _write(tmp_py, "const.py", """\
            X = 42
            Y = "hello"
        """)
        result = compute_complexity(tmp_py / "const.py")
        assert result.function_count == 0


# ===================================================================
# Complexity scoring — nesting depth
# ===================================================================


class TestMaxNesting:
    """Measures deepest nesting level."""

    def test_flat_code(self, tmp_py: pathlib.Path) -> None:
        _write(tmp_py, "flat.py", """\
            x = 1
            y = 2
        """)
        result = compute_complexity(tmp_py / "flat.py")
        assert result.max_nesting == 0

    def test_single_level(self, tmp_py: pathlib.Path) -> None:
        _write(tmp_py, "one.py", """\
            def foo():
                pass
        """)
        result = compute_complexity(tmp_py / "one.py")
        assert result.max_nesting == 1

    def test_deep_nesting(self, tmp_py: pathlib.Path) -> None:
        _write(tmp_py, "deep.py", """\
            def outer():
                for i in range(10):
                    if i > 5:
                        while True:
                            break
        """)
        result = compute_complexity(tmp_py / "deep.py")
        assert result.max_nesting == 4

    def test_class_methods_nesting(self, tmp_py: pathlib.Path) -> None:
        _write(tmp_py, "cls_nested.py", """\
            class Foo:
                def bar(self):
                    if True:
                        pass
        """)
        result = compute_complexity(tmp_py / "cls_nested.py")
        # class -> method -> if = 3
        assert result.max_nesting == 3


# ===================================================================
# Complexity scoring — overall level classification
# ===================================================================


class TestComplexityClassification:
    """Tests the low/medium/high classification."""

    def test_low_complexity(self, tmp_py: pathlib.Path) -> None:
        """< 50 lines, <= 2 functions, simple control flow."""
        _write(tmp_py, "simple.py", """\
            def greet(name):
                return f"Hello {name}"
        """)
        result = compute_complexity(tmp_py / "simple.py")
        assert result.complexity == ComplexityLevel.LOW

    def test_medium_complexity(self, tmp_py: pathlib.Path) -> None:
        """50-200 lines, 3-8 functions, moderate branching."""
        # Generate a file with ~60 code lines and 4 functions
        lines = []
        for i in range(4):
            lines.append(f"def func_{i}(x):")
            for j in range(12):
                lines.append(f"    y_{j} = x + {j}")
            lines.append(f"    if x > {i}:")
            lines.append(f"        return y_0 + {i}")
            lines.append("    return x")
            lines.append("")
        (tmp_py / "medium.py").write_text("\n".join(lines))
        result = compute_complexity(tmp_py / "medium.py")
        assert result.complexity == ComplexityLevel.MEDIUM

    def test_high_complexity(self, tmp_py: pathlib.Path) -> None:
        """200+ lines, 8+ functions, deep nesting."""
        lines = []
        for i in range(10):
            lines.append(f"def func_{i}(x):")
            for j in range(20):
                lines.append(f"    y_{j} = x + {j}")
            lines.append("    if x > 0:")
            lines.append("        for k in range(x):")
            lines.append(f"            if k > {i}:")
            lines.append("                return k")
            lines.append("    return x")
            lines.append("")
        (tmp_py / "high.py").write_text("\n".join(lines))
        result = compute_complexity(tmp_py / "high.py")
        assert result.complexity == ComplexityLevel.HIGH


# ===================================================================
# Complexity scoring — edge cases
# ===================================================================


class TestComplexityEdgeCases:
    """Edge cases for complexity scoring."""

    def test_syntax_error_returns_fallback(
        self, tmp_py: pathlib.Path,
    ) -> None:
        """Files with syntax errors use line-count-only fallback."""
        _write(tmp_py, "bad.py", """\
            def broken(
        """)
        result = compute_complexity(tmp_py / "bad.py")
        # Should not crash; returns a valid ComplexityResult
        assert isinstance(result, ComplexityResult)
        assert result.function_count == 0
        assert result.max_nesting == 0

    def test_nonexistent_file_raises(self, tmp_py: pathlib.Path) -> None:
        with pytest.raises(FileNotFoundError):
            compute_complexity(tmp_py / "missing.py")

    def test_deterministic(self, tmp_py: pathlib.Path) -> None:
        """Same file always produces the same result."""
        _write(tmp_py, "stable.py", """\
            def foo():
                for i in range(10):
                    if i > 5:
                        pass
        """)
        r1 = compute_complexity(tmp_py / "stable.py")
        r2 = compute_complexity(tmp_py / "stable.py")
        assert r1 == r2
