"""Go language plugin -- tree-sitter-based parsing and import resolution.

Uses tree-sitter with the Go grammar to parse Go source files, extracting
imports, exports (capitalized symbols), function/method declarations,
type declarations, call relationships, and entry point markers.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import tree_sitter as ts
import tree_sitter_go as tsgo

from nlv.plugins import (
    ExportKind,
    ExportRef,
    FunctionRef,
    ImportRef,
    ParseResult,
)

logger = logging.getLogger(__name__)

# Initialize the Go language and parser once at module level.
_GO_LANG = ts.Language(tsgo.language())

# Go standard library top-level package names.
# This is a comprehensive set -- used to skip import resolution.
_GO_STDLIB: frozenset[str] = frozenset({
    "archive", "bufio", "builtin", "bytes", "cmp", "compress",
    "container", "context", "crypto", "database", "debug", "embed",
    "encoding", "errors", "expvar", "flag", "fmt", "go", "hash",
    "html", "image", "index", "io", "iter", "log", "maps", "math",
    "mime", "net", "os", "path", "plugin", "reflect", "regexp",
    "runtime", "slices", "sort", "strconv", "strings", "structs",
    "sync", "syscall", "testing", "text", "time", "unicode", "unique",
    "unsafe",
    # internal packages (users should not import these, but parse them)
    "internal", "vendor",
})


class GoPlugin:
    """Language plugin for Go (.go) files."""

    @property
    def name(self) -> str:
        return "go"

    @property
    def extensions(self) -> Sequence[str]:
        return (".go",)

    # ------------------------------------------------------------------
    # parse_file
    # ------------------------------------------------------------------

    def parse_file(self, path: Path) -> ParseResult:
        """Parse a Go file and return structured data.

        Raises ``FileNotFoundError`` if *path* does not exist.
        """
        if not path.exists():
            msg = f"File not found: {path}"
            raise FileNotFoundError(msg)

        source = path.read_bytes()
        parser = ts.Parser(_GO_LANG)
        tree = parser.parse(source)
        root = tree.root_node

        package_name = _extract_package_name(root, source)
        imports = _extract_imports(root, source)
        functions, methods = _extract_functions_and_methods(root, source)
        type_exports = _extract_type_exports(root, source)
        const_var_exports = _extract_const_var_exports(root, source)

        exports = _build_exports(functions, methods, type_exports, const_var_exports)
        all_functions = list(functions) + list(methods)
        entry_point = (
            package_name == "main"
            and any(fn.name == "main" for fn in functions)
        )

        return ParseResult(
            imports=tuple(sorted(imports, key=lambda r: r.source)),
            exports=tuple(sorted(exports, key=lambda e: (e.line, e.name))),
            functions=tuple(
                sorted(all_functions, key=lambda f: (f.line, f.name))
            ),
            entry_point=entry_point,
        )

    # ------------------------------------------------------------------
    # resolve_import
    # ------------------------------------------------------------------

    def resolve_import(
        self, import_ref: ImportRef, from_file: Path,
    ) -> Path | None:
        """Resolve a Go import to a local directory path.

        Returns ``None`` for standard library and third-party imports.
        Local imports (matching go.mod module path) resolve to the
        corresponding directory under the repo root.
        """
        source = import_ref.source

        # Standard library check
        top_level = source.split("/")[0]
        if top_level in _GO_STDLIB:
            return None

        # Find go.mod to determine module path and repo root
        repo_root = _find_gomod_root(from_file)
        if repo_root is None:
            return None

        module_path = _read_module_path(repo_root / "go.mod")
        if module_path is None:
            return None

        # Check if this import is module-relative
        if not source.startswith(module_path):
            return None

        # Strip the module path prefix to get the relative directory
        relative = source[len(module_path):]
        if relative.startswith("/"):
            relative = relative[1:]

        if not relative:
            return repo_root

        local_dir = repo_root / relative
        if local_dir.is_dir():
            return local_dir

        return None


# ======================================================================
# Tree-sitter extraction helpers
# ======================================================================


def _node_text(node: ts.Node, source: bytes) -> str:
    """Extract the text of a tree-sitter node."""
    return source[node.start_byte:node.end_byte].decode("utf-8")


def _is_exported(name: str) -> bool:
    """Check if a Go symbol is exported (starts with uppercase)."""
    return len(name) > 0 and name[0].isupper()


def _build_exports(
    functions: list[FunctionRef] | tuple[FunctionRef, ...],
    methods: list[FunctionRef] | tuple[FunctionRef, ...],
    type_exports: list[ExportRef],
    const_var_exports: list[ExportRef],
) -> list[ExportRef]:
    """Build the exports list from all extracted symbols."""
    exports: list[ExportRef] = []
    for fn in functions:
        if _is_exported(fn.name):
            exports.append(ExportRef(
                name=fn.name, kind=ExportKind.FUNCTION, line=fn.line,
            ))
    for fn in methods:
        method_name = fn.name.rsplit(".", 1)[-1]
        if _is_exported(method_name):
            exports.append(ExportRef(
                name=fn.name, kind=ExportKind.FUNCTION, line=fn.line,
            ))
    exports.extend(type_exports)
    exports.extend(const_var_exports)
    return exports


def _extract_package_name(root: ts.Node, source: bytes) -> str:
    """Extract the package name from a Go source file."""
    for child in root.children:
        if child.type == "package_clause":
            for sub in child.children:
                if sub.type == "package_identifier":
                    return _node_text(sub, source)
    return ""


# ======================================================================
# Import extraction
# ======================================================================


def _extract_imports(root: ts.Node, source: bytes) -> list[ImportRef]:
    """Extract all import declarations from the AST."""
    results: list[ImportRef] = []
    for child in root.children:
        if child.type == "import_declaration":
            _visit_import_declaration(child, source, results)
    return results


def _visit_import_declaration(
    node: ts.Node, source: bytes, results: list[ImportRef],
) -> None:
    """Visit an import declaration and extract ImportRefs."""
    for child in node.children:
        if child.type == "import_spec":
            _extract_single_import(child, source, results)
        elif child.type == "import_spec_list":
            for spec in child.children:
                if spec.type == "import_spec":
                    _extract_single_import(spec, source, results)


def _extract_single_import(
    node: ts.Node, source: bytes, results: list[ImportRef],
) -> None:
    """Extract a single import spec into an ImportRef."""
    alias: str | None = None
    import_path: str = ""

    for child in node.children:
        if child.type == "interpreted_string_literal":
            # Remove surrounding quotes
            raw = _node_text(child, source)
            import_path = raw.strip('"')
        elif child.type == "package_identifier":
            alias = _node_text(child, source)
        elif child.type == "dot":
            alias = "."
        elif child.type == "blank_identifier":
            alias = "_"

    if not import_path:
        return

    specifiers: tuple[str, ...] = ()
    if alias is not None:
        specifiers = (alias,)

    results.append(
        ImportRef(
            source=import_path,
            specifiers=specifiers,
            is_relative=False,  # Go imports are never relative
        )
    )


# ======================================================================
# Function and method extraction
# ======================================================================


def _extract_functions_and_methods(
    root: ts.Node, source: bytes,
) -> tuple[list[FunctionRef], list[FunctionRef]]:
    """Extract function and method declarations.

    Returns (standalone_functions, methods).
    """
    functions: list[FunctionRef] = []
    methods: list[FunctionRef] = []

    for child in root.children:
        if child.type == "function_declaration":
            fn = _parse_function_declaration(child, source)
            if fn is not None:
                functions.append(fn)
        elif child.type == "method_declaration":
            fn = _parse_method_declaration(child, source)
            if fn is not None:
                methods.append(fn)

    return functions, methods


def _parse_function_declaration(
    node: ts.Node, source: bytes,
) -> FunctionRef | None:
    """Parse a function_declaration node into a FunctionRef."""
    name = ""
    for child in node.children:
        if child.type == "identifier":
            name = _node_text(child, source)
            break

    if not name:
        return None

    calls = _extract_calls_from_body(node, source)

    return FunctionRef(
        name=name,
        line=node.start_point.row + 1,  # 1-indexed
        end_line=node.end_point.row + 1,
        calls=tuple(sorted(set(calls))),
    )


def _parse_method_declaration(
    node: ts.Node, source: bytes,
) -> FunctionRef | None:
    """Parse a method_declaration node into a FunctionRef.

    Names are qualified as ``Receiver.Method``.
    """
    receiver_name = ""
    method_name = ""
    seen_receiver = False

    for child in node.children:
        if child.type == "parameter_list" and not seen_receiver:
            # First parameter_list is the receiver
            receiver_name = _extract_receiver_type(child, source)
            seen_receiver = True
        elif child.type == "field_identifier":
            method_name = _node_text(child, source)

    if not method_name:
        return None

    qualified_name = (
        f"{receiver_name}.{method_name}" if receiver_name else method_name
    )

    calls = _extract_calls_from_body(node, source)

    return FunctionRef(
        name=qualified_name,
        line=node.start_point.row + 1,
        end_line=node.end_point.row + 1,
        calls=tuple(sorted(set(calls))),
    )


def _extract_receiver_type(
    param_list: ts.Node, source: bytes,
) -> str:
    """Extract the receiver type name from a method's parameter list.

    Handles ``(r *Type)`` and ``(r Type)`` patterns.
    """
    for child in param_list.children:
        if child.type == "parameter_declaration":
            for sub in child.children:
                if sub.type == "pointer_type":
                    # *Type -> extract Type
                    for ptr_child in sub.children:
                        if ptr_child.type == "type_identifier":
                            return _node_text(ptr_child, source)
                elif sub.type == "type_identifier":
                    return _node_text(sub, source)
    return ""


# ======================================================================
# Call extraction
# ======================================================================


def _extract_calls_from_body(
    node: ts.Node, source: bytes,
) -> list[str]:
    """Extract function/method call names from a function body."""
    calls: list[str] = []
    body = _find_child_by_type(node, "block")
    if body is None:
        return calls
    _visit_calls(body, source, calls)
    return calls


def _visit_calls(
    node: ts.Node, source: bytes, calls: list[str],
) -> None:
    """Recursively visit nodes to find call expressions."""
    if node.type == "call_expression":
        func_node = node.children[0] if node.children else None
        if func_node is not None:
            name = _call_expression_name(func_node, source)
            if name:
                calls.append(name)

    for child in node.children:
        _visit_calls(child, source, calls)


def _call_expression_name(node: ts.Node, source: bytes) -> str:
    """Extract the name from a call expression's function node."""
    if node.type == "identifier":
        return _node_text(node, source)
    if node.type == "selector_expression":
        return _selector_name(node, source)
    return ""


def _selector_name(node: ts.Node, source: bytes) -> str:
    """Build a dotted name from a selector_expression (e.g., pkg.Func)."""
    parts: list[str] = []
    for child in node.children:
        if child.type == "identifier":
            parts.append(_node_text(child, source))
        elif child.type == "field_identifier":
            parts.append(_node_text(child, source))
        elif child.type == "selector_expression":
            nested = _selector_name(child, source)
            if nested:
                parts.append(nested)
    return ".".join(parts)


# ======================================================================
# Type export extraction
# ======================================================================


def _extract_type_exports(
    root: ts.Node, source: bytes,
) -> list[ExportRef]:
    """Extract exported type declarations (struct, interface, type alias)."""
    exports: list[ExportRef] = []

    for child in root.children:
        if child.type == "type_declaration":
            _visit_type_declaration(child, source, exports)

    return exports


def _visit_type_declaration(
    node: ts.Node, source: bytes, exports: list[ExportRef],
) -> None:
    """Visit a type_declaration and extract exported types."""
    for child in node.children:
        if child.type == "type_spec":
            _extract_type_spec(child, source, exports)
        elif child.type == "type_spec_list":
            for spec in child.children:
                if spec.type == "type_spec":
                    _extract_type_spec(spec, source, exports)


def _extract_type_spec(
    node: ts.Node, source: bytes, exports: list[ExportRef],
) -> None:
    """Extract a single type spec."""
    name = ""
    kind = ExportKind.TYPE

    for child in node.children:
        if child.type == "type_identifier":
            name = _node_text(child, source)
        elif child.type == "struct_type":
            kind = ExportKind.CLASS
        elif child.type == "interface_type":
            kind = ExportKind.TYPE

    if name and _is_exported(name):
        exports.append(
            ExportRef(
                name=name,
                kind=kind,
                line=node.start_point.row + 1,
            )
        )


# ======================================================================
# Const/var export extraction
# ======================================================================


def _extract_const_var_exports(
    root: ts.Node, source: bytes,
) -> list[ExportRef]:
    """Extract exported const and var declarations."""
    exports: list[ExportRef] = []

    for child in root.children:
        if child.type in ("const_declaration", "var_declaration"):
            _visit_const_var_declaration(child, source, exports)

    return exports


def _visit_const_var_declaration(
    node: ts.Node, source: bytes, exports: list[ExportRef],
) -> None:
    """Visit a const/var declaration and extract exported symbols."""
    for child in node.children:
        if child.type == "const_spec":
            _extract_const_var_spec(child, source, exports)
        elif child.type == "var_spec":
            _extract_const_var_spec(child, source, exports)
        elif child.type == "const_spec_list":
            for spec in child.children:
                if spec.type == "const_spec":
                    _extract_const_var_spec(spec, source, exports)
        elif child.type == "var_spec_list":
            for spec in child.children:
                if spec.type == "var_spec":
                    _extract_const_var_spec(spec, source, exports)


def _extract_const_var_spec(
    node: ts.Node, source: bytes, exports: list[ExportRef],
) -> None:
    """Extract a single const/var spec name if exported."""
    for child in node.children:
        if child.type == "identifier":
            name = _node_text(child, source)
            if _is_exported(name):
                exports.append(
                    ExportRef(
                        name=name,
                        kind=ExportKind.VARIABLE,
                        line=node.start_point.row + 1,
                    )
                )


# ======================================================================
# Utility helpers
# ======================================================================


def _find_child_by_type(node: ts.Node, type_name: str) -> ts.Node | None:
    """Find the first child of a given type."""
    for child in node.children:
        if child.type == type_name:
            return child
    return None


# ======================================================================
# Import resolution helpers
# ======================================================================


def _find_gomod_root(from_file: Path) -> Path | None:
    """Walk up from a file to find the directory containing go.mod."""
    current = from_file.parent
    while True:
        if (current / "go.mod").is_file():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _read_module_path(gomod_path: Path) -> str | None:
    """Read the module path from a go.mod file.

    Looks for the line: ``module github.com/example/myproject``
    """
    try:
        content = gomod_path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Failed to read go.mod at %s", gomod_path)
        return None

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("module "):
            return stripped[len("module "):].strip()

    return None
