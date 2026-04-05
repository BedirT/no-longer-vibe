"""Entry point detection and complexity scoring (BED-67).

Provides two utilities that feed into reading order and map.json:

- ``detect_entry_point(path, importers, pyproject_scripts)`` — determines
  whether a Python file is an application entry point.
- ``compute_complexity(path)`` — assigns a complexity level to a file
  based on line count, function count, and nesting depth.
"""

from __future__ import annotations

import ast
import enum
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import AbstractSet

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ENTRY_FILENAMES: frozenset[str] = frozenset({
    "main.py",
    "__main__.py",
    "app.py",
    "server.py",
    "cli.py",
})

# AST node types that represent passive declarations (no side effects).
_PASSIVE_NODE_TYPES: tuple[type[ast.stmt], ...] = (
    ast.Import,
    ast.ImportFrom,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Assign,
    ast.AnnAssign,
)

# Python 3.12+ has ast.TypeAlias
if hasattr(ast, "TypeAlias"):
    _PASSIVE_NODE_TYPES = (*_PASSIVE_NODE_TYPES, ast.TypeAlias)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class ComplexityLevel(enum.Enum):
    """Overall complexity classification for a source file."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ComplexityResult:
    """Metrics and classification for a single file's complexity."""

    line_count: int
    function_count: int
    max_nesting: int
    complexity: ComplexityLevel


# ---------------------------------------------------------------------------
# Entry point detection
# ---------------------------------------------------------------------------


def detect_entry_point(
    path: Path,
    *,
    importers: AbstractSet[str],
    pyproject_scripts: dict[str, str] | None = None,
) -> bool:
    """Determine whether a Python file is an application entry point.

    A file is considered an entry point if ANY of:
    1. It contains a top-level ``if __name__ == "__main__"`` guard.
    2. Its filename matches a common entry-point pattern.
    3. It is referenced in pyproject.toml ``[project.scripts]`` or
       ``[tool.poetry.scripts]``.
    4. It has no importers (graph leaf) AND has top-level side effects.

    Args:
        path: Absolute path to the Python source file.
        importers: Set of file paths that import this file.
        pyproject_scripts: Mapping of script-name to "module:func"
            from pyproject.toml, if available.

    Returns:
        True if the file is an entry point.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    if not path.exists():
        msg = f"File not found: {path}"
        raise FileNotFoundError(msg)

    source = path.read_text(encoding="utf-8")

    tree = _try_parse(source)

    # 1. top-level __name__ == "__main__" guard
    if tree is not None and _has_name_main_guard(tree):
        return True

    # 2. filename pattern
    if path.name in _ENTRY_FILENAMES:
        return True

    # 3. pyproject.toml scripts reference
    if _in_pyproject_scripts(path, pyproject_scripts):
        return True

    # 4. graph leaf with side effects
    if not importers and tree is not None and _has_side_effects(tree):
        return True

    return False


def _try_parse(source: str) -> ast.Module | None:
    """Parse source into an AST, returning None on syntax errors."""
    try:
        return ast.parse(source)
    except SyntaxError:
        logger.debug("Syntax error while parsing, skipping AST analysis")
        return None


def _has_name_main_guard(tree: ast.Module) -> bool:
    """Check for a top-level ``if __name__ == "__main__"`` guard."""
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        if _is_name_main_compare(node.test):
            return True
    return False


def _is_name_main_compare(node: ast.expr) -> bool:
    """Check if an expression is ``__name__ == "__main__"``."""
    if not isinstance(node, ast.Compare):
        return False
    if len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
        return False
    if len(node.comparators) != 1:
        return False

    left = node.left
    right = node.comparators[0]

    return _is_dunder_name_and_main(left, right) or _is_dunder_name_and_main(
        right, left,
    )


def _is_dunder_name_and_main(
    name_node: ast.expr, value_node: ast.expr,
) -> bool:
    """Check if one side is ``__name__`` and the other is ``"__main__"``."""
    if not isinstance(name_node, ast.Name):
        return False
    if name_node.id != "__name__":
        return False
    if not isinstance(value_node, ast.Constant):
        return False
    return value_node.value == "__main__"  # type: ignore[no-any-return]


def _in_pyproject_scripts(
    path: Path, scripts: dict[str, str] | None,
) -> bool:
    """Check if the file's module is referenced in pyproject scripts."""
    if not scripts:
        return False
    stem = path.stem
    for entry_spec in scripts.values():
        module_part = entry_spec.split(":")[0]
        # Match on the last component of dotted module paths
        module_leaf = module_part.rsplit(".", maxsplit=1)[-1]
        if module_leaf == stem:
            return True
    return False


def _has_side_effects(tree: ast.Module) -> bool:
    """Check if the module has top-level statements with side effects.

    Passive statements (imports, function/class defs, assignments) are
    not considered side effects.
    """
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(
            node.value, ast.Constant,
        ):
            # Docstrings / standalone string literals — no side effect
            continue
        if not isinstance(node, _PASSIVE_NODE_TYPES):
            return True
    return False


# ---------------------------------------------------------------------------
# Complexity scoring
# ---------------------------------------------------------------------------


def compute_complexity(path: Path) -> ComplexityResult:
    """Compute complexity metrics for a Python source file.

    Metrics:
    - ``line_count``: total lines excluding blanks and comments.
    - ``function_count``: number of function/method declarations.
    - ``max_nesting``: deepest nesting level in the AST.
    - ``complexity``: overall "low" / "medium" / "high" classification.

    Args:
        path: Absolute path to the Python source file.

    Returns:
        A ComplexityResult with all computed metrics.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    if not path.exists():
        msg = f"File not found: {path}"
        raise FileNotFoundError(msg)

    source = path.read_text(encoding="utf-8")

    line_count = _count_code_lines(source)
    tree = _try_parse(source)

    if tree is None:
        return ComplexityResult(
            line_count=line_count,
            function_count=0,
            max_nesting=0,
            complexity=_classify(line_count, 0, 0),
        )

    function_count = _count_functions(tree)
    max_nesting = _max_nesting_depth(tree)
    level = _classify(line_count, function_count, max_nesting)

    return ComplexityResult(
        line_count=line_count,
        function_count=function_count,
        max_nesting=max_nesting,
        complexity=level,
    )


def _count_code_lines(source: str) -> int:
    """Count non-blank, non-comment lines in source text."""
    count = 0
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        count += 1
    return count


def _count_functions(tree: ast.Module) -> int:
    """Count all function and async function definitions in the AST."""
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            count += 1
    return count


def _max_nesting_depth(tree: ast.Module) -> int:
    """Compute the maximum nesting depth of the AST.

    Nesting-incrementing nodes: FunctionDef, AsyncFunctionDef, ClassDef,
    For, AsyncFor, While, If, With, AsyncWith, Try, ExceptHandler,
    Match.
    """
    return _walk_depth(tree, 0)


_NESTING_TYPES: tuple[type[ast.AST], ...] = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.If,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.ExceptHandler,
)

# Python 3.11+ has ast.TryStar
if hasattr(ast, "TryStar"):
    _NESTING_TYPES = (*_NESTING_TYPES, ast.TryStar)  # type: ignore[attr-defined]

# Python 3.10+ has ast.Match/ast.match_case
if hasattr(ast, "Match"):
    _NESTING_TYPES = (*_NESTING_TYPES, ast.Match, ast.match_case)  # type: ignore[attr-defined]


def _walk_depth(node: ast.AST, depth: int) -> int:
    """Recursively walk the AST tracking nesting depth."""
    max_depth = depth
    for child in ast.iter_child_nodes(node):
        child_depth = depth + 1 if isinstance(child, _NESTING_TYPES) else depth
        max_depth = max(max_depth, _walk_depth(child, child_depth))
    return max_depth


def _classify(
    line_count: int,
    function_count: int,
    max_nesting: int,
) -> ComplexityLevel:
    """Classify overall complexity from individual metrics.

    | Level  | Criteria                                        |
    |--------|-------------------------------------------------|
    | low    | < 50 lines, <= 2 functions, simple control flow |
    | medium | 50-200 lines, 3-8 functions, moderate branching |
    | high   | 200+ lines, 8+ functions, deep nesting          |

    Uses a scoring approach: each metric votes for a level, and the
    highest vote wins. Ties resolve upward.
    """
    high_votes = 0
    medium_votes = 0

    # Line count
    if line_count >= 200:
        high_votes += 1
    elif line_count >= 50:
        medium_votes += 1

    # Function count
    if function_count > 8:
        high_votes += 1
    elif function_count >= 3:
        medium_votes += 1

    # Nesting depth
    if max_nesting >= 4:
        high_votes += 1
    elif max_nesting >= 2:
        medium_votes += 1

    if high_votes >= 2:
        return ComplexityLevel.HIGH
    if high_votes >= 1 or medium_votes >= 2:
        return ComplexityLevel.MEDIUM
    return ComplexityLevel.LOW
