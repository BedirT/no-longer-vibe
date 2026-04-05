"""Python language plugin — AST-based parsing and import resolution.

Uses the built-in ``ast`` module to parse Python source files, extracting
imports, exports, function/class declarations, call relationships, and
entry point markers.
"""

from __future__ import annotations

import ast
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from nlv.plugins import (
    ExportKind,
    ExportRef,
    FunctionRef,
    ImportRef,
    ParseResult,
)

logger = logging.getLogger(__name__)

# Standard library top-level module names — used to skip import resolution.
# Available since Python 3.10; the project requires 3.11+.
_STDLIB_TOP_LEVEL: frozenset[str] = frozenset(sys.stdlib_module_names)


class PythonPlugin:
    """Language plugin for Python (.py, .pyi) files."""

    @property
    def name(self) -> str:
        return "python"

    @property
    def extensions(self) -> Sequence[str]:
        return (".py", ".pyi")

    # ------------------------------------------------------------------
    # parse_file
    # ------------------------------------------------------------------

    def parse_file(self, path: Path) -> ParseResult:
        """Parse a Python file and return structured data.

        Raises ``FileNotFoundError`` if *path* does not exist.
        Returns an empty ``ParseResult`` for files with syntax errors.
        """
        if not path.exists():
            msg = f"File not found: {path}"
            raise FileNotFoundError(msg)

        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            logger.warning("Syntax error in %s — returning empty result", path)
            return ParseResult(
                imports=(), exports=(), functions=(), entry_point=False,
            )

        imports = _extract_imports(tree)
        all_names = _extract_dunder_all(tree)
        exports = _extract_exports(tree, all_names)
        functions = _extract_functions(tree)
        entry_point = _detect_entry_point(tree, path)

        return ParseResult(
            imports=tuple(sorted(imports, key=lambda r: r.source)),
            exports=tuple(sorted(exports, key=lambda e: (e.name, e.line))),
            functions=tuple(sorted(functions, key=lambda f: (f.line, f.name))),
            entry_point=entry_point,
        )

    # ------------------------------------------------------------------
    # resolve_import
    # ------------------------------------------------------------------

    def resolve_import(
        self, import_ref: ImportRef, from_file: Path,
    ) -> Path | None:
        """Resolve an import reference to a file path on disk.

        Returns ``None`` for third-party or stdlib imports that cannot
        be resolved to a local file.
        """
        if import_ref.is_relative:
            return _resolve_relative(import_ref, from_file)
        return _resolve_absolute(import_ref, from_file)


# ======================================================================
# Import extraction helpers
# ======================================================================


def _extract_imports(tree: ast.Module) -> list[ImportRef]:
    """Walk the entire AST and collect all import statements."""
    results: list[ImportRef] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.append(
                    ImportRef(
                        source=alias.name,
                        specifiers=(),
                        is_relative=False,
                    ),
                )
        elif isinstance(node, ast.ImportFrom):
            source = _import_from_source(node)
            specifiers = tuple(sorted(
                alias.name for alias in node.names
            ))
            results.append(
                ImportRef(
                    source=source,
                    specifiers=specifiers,
                    is_relative=node.level > 0,
                ),
            )
    return results


def _import_from_source(node: ast.ImportFrom) -> str:
    """Build the source string for ``from X import Y``.

    Relative imports get leading dots: ``from ..utils import X`` -> ``..utils``.
    """
    dots = "." * node.level
    module = node.module or ""
    return f"{dots}{module}"


# ======================================================================
# Export extraction helpers
# ======================================================================


def _extract_dunder_all(tree: ast.Module) -> list[str] | None:
    """Return the list from ``__all__ = [...]`` or None if absent."""
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                return _parse_all_value(node.value)
    return None


def _parse_all_value(value: ast.expr) -> list[str] | None:
    """Extract string elements from a list/tuple literal."""
    if isinstance(value, (ast.List, ast.Tuple)):
        names: list[str] = []
        for elt in value.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                names.append(elt.value)
        return names
    return None


def _extract_exports(
    tree: ast.Module,
    all_names: list[str] | None,
) -> list[ExportRef]:
    """Extract exported symbols from module-level declarations."""
    exports: list[ExportRef] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            exports.append(
                ExportRef(
                    name=node.name,
                    kind=ExportKind.FUNCTION,
                    line=node.lineno,
                ),
            )
        elif isinstance(node, ast.ClassDef):
            exports.append(
                ExportRef(
                    name=node.name,
                    kind=ExportKind.CLASS,
                    line=node.lineno,
                ),
            )
        elif isinstance(node, ast.Assign):
            _collect_assign_exports(node, exports)
        elif isinstance(node, ast.AnnAssign):
            _collect_annassign_exports(node, exports)

    return _filter_exports(exports, all_names)


def _collect_assign_exports(
    node: ast.Assign,
    exports: list[ExportRef],
) -> None:
    """Collect variable exports from ``X = ...`` assignments."""
    for target in node.targets:
        if isinstance(target, ast.Name):
            exports.append(
                ExportRef(
                    name=target.id,
                    kind=ExportKind.VARIABLE,
                    line=node.lineno,
                ),
            )


def _collect_annassign_exports(
    node: ast.AnnAssign,
    exports: list[ExportRef],
) -> None:
    """Collect exports from annotated assignments (``x: int = 1``)."""
    if isinstance(node.target, ast.Name):
        exports.append(
            ExportRef(
                name=node.target.id,
                kind=ExportKind.VARIABLE,
                line=node.lineno,
            ),
        )


def _filter_exports(
    exports: list[ExportRef],
    all_names: list[str] | None,
) -> list[ExportRef]:
    """Apply __all__ filtering or private-name exclusion."""
    if all_names is not None:
        all_set = set(all_names)
        return [e for e in exports if e.name in all_set]
    # Exclude __all__ itself and private names
    return [
        e for e in exports
        if not e.name.startswith("_")
    ]


# ======================================================================
# Function extraction helpers
# ======================================================================


def _extract_functions(tree: ast.Module) -> list[FunctionRef]:
    """Extract all function/method declarations with call relationships."""
    results: list[FunctionRef] = []
    _visit_functions(tree, prefix="", results=results)
    return results


def _visit_functions(
    node: ast.AST,
    prefix: str,
    results: list[FunctionRef],
) -> None:
    """Recursively visit function and class definitions."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualified = (
                f"{prefix}.{child.name}" if prefix else child.name
            )
            calls = _extract_calls(child)
            results.append(
                FunctionRef(
                    name=qualified,
                    line=child.lineno,
                    end_line=child.end_lineno or child.lineno,
                    calls=tuple(sorted(set(calls))),
                ),
            )
            # Recurse for nested functions
            _visit_functions(child, prefix=qualified, results=results)
        elif isinstance(child, ast.ClassDef):
            class_prefix = (
                f"{prefix}.{child.name}" if prefix else child.name
            )
            _visit_functions(child, prefix=class_prefix, results=results)


def _extract_calls(func_node: ast.AST) -> list[str]:
    """Extract function/method call names from a function body."""
    calls: list[str] = []
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        if name is not None:
            calls.append(name)
    return calls


def _call_name(node: ast.expr) -> str | None:
    """Extract the callable name from a Call node's func attribute."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        value_name = _call_name(node.value)
        if value_name is not None:
            return f"{value_name}.{node.attr}"
        return node.attr
    return None


# ======================================================================
# Entry point detection
# ======================================================================


def _detect_entry_point(tree: ast.Module, path: Path) -> bool:
    """Detect whether the file is a Python entry point."""
    # __main__.py is always an entry point
    if path.name == "__main__.py":
        return True
    # Check for `if __name__ == "__main__":` guard
    return _has_name_main_guard(tree)


def _has_name_main_guard(tree: ast.Module) -> bool:
    """Check for ``if __name__ == '__main__':`` at module level."""
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.If):
            continue
        if _is_name_main_compare(node.test):
            return True
    return False


def _is_name_main_compare(node: ast.expr) -> bool:
    """Check if an expression is ``__name__ == '__main__'``."""
    if not isinstance(node, ast.Compare):
        return False
    if len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
        return False
    left = node.left
    if not (isinstance(left, ast.Name) and left.id == "__name__"):
        return False
    if len(node.comparators) != 1:
        return False
    right = node.comparators[0]
    return isinstance(right, ast.Constant) and right.value == "__main__"


# ======================================================================
# Import resolution helpers
# ======================================================================


def _resolve_relative(
    import_ref: ImportRef,
    from_file: Path,
) -> Path | None:
    """Resolve a relative import to a file path on disk."""
    source = import_ref.source
    # Count leading dots
    level = 0
    for ch in source:
        if ch == ".":
            level += 1
        else:
            break

    module_part = source[level:]

    # Start from the directory of from_file, go up (level - 1) times
    # (level=1 means same package directory)
    base = from_file.parent
    for _ in range(level - 1):
        base = base.parent

    if module_part:
        return _find_module_on_disk(base, module_part)

    # `from . import X` — resolve each specifier
    for spec in import_ref.specifiers:
        result = _find_module_on_disk(base, spec)
        if result is not None:
            return result
    return None


def _resolve_absolute(
    import_ref: ImportRef,
    from_file: Path,
) -> Path | None:
    """Resolve an absolute import, searching upward for package roots."""
    top_level = import_ref.source.split(".")[0]
    if top_level in _STDLIB_TOP_LEVEL:
        return None

    # Walk upward from from_file to find a directory containing the
    # top-level module/package
    current = from_file.parent
    while True:
        result = _find_module_on_disk(current, import_ref.source)
        if result is not None:
            return result
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _find_module_on_disk(base: Path, dotted_name: str) -> Path | None:
    """Find a dotted module name as a file or package on disk."""
    parts = dotted_name.split(".")
    target = base
    for part in parts:
        target = target / part

    # Check for module file
    module_file = target.with_suffix(".py")
    if module_file.is_file():
        return module_file

    # Check for package directory with __init__.py
    init_file = target / "__init__.py"
    if init_file.is_file():
        return init_file

    return None
