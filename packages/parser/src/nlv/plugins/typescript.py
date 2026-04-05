"""TypeScript/JavaScript language plugin — tree-sitter-based parsing.

Uses tree-sitter Python bindings (tree-sitter-javascript and
tree-sitter-typescript) to parse TS/JS source files, extracting
imports, exports, function/class declarations, call relationships,
and entry point markers.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import tree_sitter as ts
import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts

from nlv.plugins import (
    ExportKind,
    ExportRef,
    FunctionRef,
    ImportRef,
    ParseResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# tree-sitter language setup (module-level singletons)
# ---------------------------------------------------------------------------

_JS_LANGUAGE = ts.Language(tsjs.language())
_TS_LANGUAGE = ts.Language(tsts.language_typescript())
_TSX_LANGUAGE = ts.Language(tsts.language_tsx())

# Map file extensions to the correct tree-sitter language
_EXTENSION_LANGUAGE: dict[str, ts.Language] = {
    ".js": _JS_LANGUAGE,
    ".jsx": _JS_LANGUAGE,
    ".mjs": _JS_LANGUAGE,
    ".cjs": _JS_LANGUAGE,
    ".ts": _TS_LANGUAGE,
    ".tsx": _TSX_LANGUAGE,
}

# Extensions to try when resolving imports without explicit extension
_RESOLVE_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

# File names that indicate an entry point
_ENTRY_POINT_STEMS = frozenset({"index", "main", "app"})


class TypeScriptPlugin:
    """Language plugin for TypeScript and JavaScript files.

    Handles .ts, .tsx, .js, .jsx, .mjs, and .cjs extensions.
    """

    @property
    def name(self) -> str:
        return "typescript"

    @property
    def extensions(self) -> Sequence[str]:
        return (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

    # ------------------------------------------------------------------
    # parse_file
    # ------------------------------------------------------------------

    def parse_file(self, path: Path) -> ParseResult:
        """Parse a TS/JS file and return structured data.

        Raises ``FileNotFoundError`` if *path* does not exist.
        Returns an empty ``ParseResult`` for files that cannot be parsed.
        """
        if not path.exists():
            msg = f"File not found: {path}"
            raise FileNotFoundError(msg)

        source = path.read_text(encoding="utf-8")
        language = _EXTENSION_LANGUAGE.get(path.suffix)
        if language is None:
            logger.warning("No language for suffix %s — returning empty", path.suffix)
            return ParseResult(
                imports=(), exports=(), functions=(), entry_point=False,
            )

        parser = ts.Parser(language)
        tree = parser.parse(source.encode("utf-8"))

        imports = _extract_imports(tree.root_node)
        exports = _extract_exports(tree.root_node)
        functions = _extract_functions(tree.root_node)
        entry_point = _detect_entry_point(path)

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

        Returns ``None`` for external packages (non-relative imports).
        """
        if not import_ref.is_relative:
            return None
        return _resolve_relative(import_ref.source, from_file)


# ======================================================================
# Import extraction helpers
# ======================================================================


def _extract_imports(root: ts.Node) -> list[ImportRef]:
    """Walk the tree and collect all import statements and require calls."""
    results: list[ImportRef] = []
    _walk_imports(root, results)
    return results


def _walk_imports(node: ts.Node, results: list[ImportRef]) -> None:
    """Recursively walk the AST to find import statements and require calls."""
    if node.type == "import_statement":
        _handle_import_statement(node, results)
    elif node.type == "call_expression":
        _handle_call_expression_import(node, results)
    else:
        for child in node.children:
            _walk_imports(child, results)


def _handle_import_statement(node: ts.Node, results: list[ImportRef]) -> None:
    """Extract an ES6 import statement."""
    source = _get_import_source(node)
    if source is None:
        return

    is_relative = source.startswith(".") or source.startswith("/")

    # Check for import clause (named/default/namespace imports)
    import_clause = _find_child(node, "import_clause")
    if import_clause is None:
        # Side-effect import: `import 'module'`
        results.append(ImportRef(source=source, specifiers=(), is_relative=is_relative))
        return

    specifiers = _extract_import_specifiers(import_clause)
    results.append(ImportRef(
        source=source,
        specifiers=tuple(sorted(specifiers)),
        is_relative=is_relative,
    ))


def _extract_import_specifiers(import_clause: ts.Node) -> list[str]:
    """Extract specifier names from an import clause."""
    specifiers: list[str] = []

    for child in import_clause.children:
        if child.type == "identifier":
            # Default import: `import X from 'mod'`
            specifiers.append(_node_text(child))
        elif child.type == "namespace_import":
            # Namespace import: `import * as ns from 'mod'`
            specifiers.append("*")
        elif child.type == "named_imports":
            # Named imports: `import { a, b } from 'mod'`
            for spec in child.children:
                if spec.type == "import_specifier":
                    # Use the original name (first identifier), not the alias
                    name_node = _find_child(spec, "identifier")
                    if name_node is not None:
                        specifiers.append(_node_text(name_node))

    return specifiers


def _handle_call_expression_import(
    node: ts.Node, results: list[ImportRef],
) -> None:
    """Handle require() and dynamic import() calls."""
    func_node = node.children[0] if node.children else None
    if func_node is None:
        return

    args_node = _find_child(node, "arguments")
    if args_node is None:
        return

    # Dynamic import: `import('module')`
    if func_node.type == "import":
        source = _get_string_argument(args_node)
        if source is not None:
            is_relative = source.startswith(".") or source.startswith("/")
            results.append(ImportRef(
                source=source, specifiers=(), is_relative=is_relative,
            ))
        return

    # require('module')
    if func_node.type == "identifier" and _node_text(func_node) == "require":
        source = _get_string_argument(args_node)
        if source is not None:
            is_relative = source.startswith(".") or source.startswith("/")
            specifiers = _get_require_specifiers(node)
            results.append(ImportRef(
                source=source,
                specifiers=tuple(sorted(specifiers)),
                is_relative=is_relative,
            ))
        return

    # Recurse into children for nested calls
    for child in node.children:
        _walk_imports(child, results)


def _get_require_specifiers(call_node: ts.Node) -> list[str]:
    """Extract variable name(s) from a require() assignment.

    Handles: `const x = require(...)` and `const { a, b } = require(...)`
    """
    parent = call_node.parent
    if parent is None or parent.type != "variable_declarator":
        return []

    name_node = parent.children[0] if parent.children else None
    if name_node is None:
        return []

    if name_node.type == "identifier":
        return [_node_text(name_node)]

    if name_node.type == "object_pattern":
        specifiers: list[str] = []
        for child in name_node.children:
            if child.type == "shorthand_property_identifier_pattern":
                specifiers.append(_node_text(child))
            elif child.type == "pair_pattern":
                key = _find_child(child, "property_identifier")
                if key is not None:
                    specifiers.append(_node_text(key))
        return specifiers

    return []


# ======================================================================
# Export extraction helpers
# ======================================================================


def _extract_exports(root: ts.Node) -> list[ExportRef]:
    """Walk the tree and collect all export declarations."""
    results: list[ExportRef] = []
    for child in root.children:
        if child.type == "export_statement":
            _handle_export_statement(child, results)
        elif child.type == "expression_statement":
            _handle_module_exports(child, results)
    return results


def _handle_export_declaration(
    child: ts.Node, has_default: bool, results: list[ExportRef],
) -> None:
    """Handle a single declaration child inside an export statement."""
    if child.type == "function_declaration":
        name_node = _find_child(child, "identifier")
        name = _node_text(name_node) if name_node is not None else "default"
        line = child.start_point.row + 1
        kind = ExportKind.DEFAULT if has_default else ExportKind.FUNCTION
        results.append(ExportRef(name=name, kind=kind, line=line))

    elif child.type == "class_declaration":
        name_node = _find_child(child, "identifier") or _find_child(
            child, "type_identifier",
        )
        name = _node_text(name_node) if name_node is not None else "default"
        line = child.start_point.row + 1
        kind = ExportKind.DEFAULT if has_default else ExportKind.CLASS
        results.append(ExportRef(name=name, kind=kind, line=line))

    elif child.type in ("lexical_declaration", "variable_declaration"):
        _handle_export_variable(child, results)

    elif child.type in ("interface_declaration", "type_alias_declaration"):
        name_node = _find_child(child, "type_identifier")
        if name_node is not None:
            results.append(ExportRef(
                name=_node_text(name_node),
                kind=ExportKind.TYPE,
                line=child.start_point.row + 1,
            ))

    elif child.type == "enum_declaration":
        name_node = _find_child(child, "identifier")
        if name_node is not None:
            results.append(ExportRef(
                name=_node_text(name_node),
                kind=ExportKind.TYPE,
                line=child.start_point.row + 1,
            ))


def _handle_export_statement(node: ts.Node, results: list[ExportRef]) -> None:
    """Process an export statement node."""
    has_default = any(c.type == "default" for c in node.children)

    for child in node.children:
        if child.type == "export_clause":
            _handle_export_clause(child, node, results)
        else:
            _handle_export_declaration(child, has_default, results)

    # Handle `export default <expression>` (number, string, identifier, etc.)
    if has_default and not any(
        c.type in ("function_declaration", "class_declaration", "export_clause")
        for c in node.children
    ):
        line = node.start_point.row + 1
        already_has = any(
            e.kind == ExportKind.DEFAULT for e in results if e.line == line
        )
        if not already_has:
            results.append(ExportRef(
                name="default", kind=ExportKind.DEFAULT, line=line,
            ))


def _handle_export_variable(
    node: ts.Node, results: list[ExportRef],
) -> None:
    """Extract variable names from `export const/let/var X = ...`."""
    for child in node.children:
        if child.type == "variable_declarator":
            name_node = _find_child(child, "identifier")
            if name_node is not None:
                results.append(ExportRef(
                    name=_node_text(name_node),
                    kind=ExportKind.VARIABLE,
                    line=node.start_point.row + 1,
                ))


def _handle_export_clause(
    clause_node: ts.Node,
    export_node: ts.Node,
    results: list[ExportRef],
) -> None:
    """Handle `export { foo, bar }` and `export { foo } from 'mod'`."""
    for child in clause_node.children:
        if child.type == "export_specifier":
            # Get the exported name (could be aliased)
            identifiers = [c for c in child.children if c.type == "identifier"]
            if identifiers:
                # First identifier is the local name
                name = _node_text(identifiers[0])
                # Check if aliased to default
                has_default_alias = any(c.type == "default" for c in child.children)
                if has_default_alias:
                    results.append(ExportRef(
                        name=name,
                        kind=ExportKind.DEFAULT,
                        line=export_node.start_point.row + 1,
                    ))
                else:
                    results.append(ExportRef(
                        name=name,
                        kind=ExportKind.VARIABLE,
                        line=export_node.start_point.row + 1,
                    ))


def _handle_module_exports(
    node: ts.Node, results: list[ExportRef],
) -> None:
    """Handle `module.exports = { foo, bar }` pattern."""
    assign = _find_child(node, "assignment_expression")
    if assign is None:
        return

    left = assign.children[0] if assign.children else None
    if left is None or left.type != "member_expression":
        return

    # Check for `module.exports`
    obj = _find_child(left, "identifier")
    prop = _find_child(left, "property_identifier")
    if obj is None or prop is None:
        return
    if _node_text(obj) != "module" or _node_text(prop) != "exports":
        return

    # Find the right-hand side value
    rhs = assign.children[-1] if len(assign.children) >= 2 else None
    if rhs is None:
        return

    if rhs.type == "object":
        for child in rhs.children:
            if child.type == "shorthand_property_identifier":
                results.append(ExportRef(
                    name=_node_text(child),
                    kind=ExportKind.VARIABLE,
                    line=node.start_point.row + 1,
                ))
            elif child.type == "pair":
                key = _find_child(child, "property_identifier")
                if key is not None:
                    results.append(ExportRef(
                        name=_node_text(key),
                        kind=ExportKind.VARIABLE,
                        line=node.start_point.row + 1,
                    ))
    else:
        # module.exports = something (single default)
        results.append(ExportRef(
            name="default",
            kind=ExportKind.DEFAULT,
            line=node.start_point.row + 1,
        ))


# ======================================================================
# Function extraction helpers
# ======================================================================


def _extract_functions(root: ts.Node) -> list[FunctionRef]:
    """Extract all function/method declarations with call relationships."""
    results: list[FunctionRef] = []
    _visit_functions(root, prefix="", results=results)
    return results


def _visit_functions(
    node: ts.Node,
    prefix: str,
    results: list[FunctionRef],
) -> None:
    """Recursively visit function, class, and variable declarations."""
    for child in node.children:
        if child.type in ("function_declaration", "generator_function_declaration"):
            _handle_function_node(child, prefix, results)
        elif child.type == "class_declaration":
            _handle_class_node(child, prefix, results)
        elif child.type in ("lexical_declaration", "variable_declaration"):
            _handle_variable_function(child, prefix, results)
        elif child.type == "export_statement":
            # Recurse into export statements to find their declarations
            _visit_functions(child, prefix, results)


def _handle_function_node(
    node: ts.Node,
    prefix: str,
    results: list[FunctionRef],
) -> None:
    """Handle a function_declaration node."""
    name_node = _find_child(node, "identifier")
    if name_node is None:
        return

    raw_name = _node_text(name_node)
    qualified = f"{prefix}.{raw_name}" if prefix else raw_name
    calls = _extract_calls(node)

    results.append(FunctionRef(
        name=qualified,
        line=node.start_point.row + 1,
        end_line=node.end_point.row + 1,
        calls=tuple(sorted(set(calls))),
    ))


def _handle_class_node(
    node: ts.Node,
    prefix: str,
    results: list[FunctionRef],
) -> None:
    """Handle a class_declaration node — extract its methods."""
    name_node = _find_child(node, "identifier") or _find_child(
        node, "type_identifier",
    )
    if name_node is None:
        return

    class_name = _node_text(name_node)
    class_prefix = f"{prefix}.{class_name}" if prefix else class_name

    body = _find_child(node, "class_body")
    if body is None:
        return

    for member in body.children:
        if member.type == "method_definition":
            method_name_node = _find_child(member, "property_identifier")
            if method_name_node is None:
                continue
            method_name = _node_text(method_name_node)
            qualified = f"{class_prefix}.{method_name}"
            calls = _extract_calls(member)
            results.append(FunctionRef(
                name=qualified,
                line=member.start_point.row + 1,
                end_line=member.end_point.row + 1,
                calls=tuple(sorted(set(calls))),
            ))
        elif member.type == "field_definition":
            # Arrow function class fields: `baz = () => {}`
            field_name_node = _find_child(member, "property_identifier")
            value_node = _find_child(member, "arrow_function") or _find_child(
                member, "function_expression",
            )
            if field_name_node is not None and value_node is not None:
                field_name = _node_text(field_name_node)
                qualified = f"{class_prefix}.{field_name}"
                calls = _extract_calls(value_node)
                results.append(FunctionRef(
                    name=qualified,
                    line=member.start_point.row + 1,
                    end_line=member.end_point.row + 1,
                    calls=tuple(sorted(set(calls))),
                ))


def _handle_variable_function(
    node: ts.Node,
    prefix: str,
    results: list[FunctionRef],
) -> None:
    """Handle arrow functions and function expressions assigned to variables."""
    for child in node.children:
        if child.type != "variable_declarator":
            continue

        name_node = _find_child(child, "identifier")
        func_node = (
            _find_child(child, "arrow_function")
            or _find_child(child, "function_expression")
        )
        if name_node is None or func_node is None:
            continue

        raw_name = _node_text(name_node)
        qualified = f"{prefix}.{raw_name}" if prefix else raw_name
        calls = _extract_calls(func_node)

        results.append(FunctionRef(
            name=qualified,
            line=node.start_point.row + 1,
            end_line=func_node.end_point.row + 1,
            calls=tuple(sorted(set(calls))),
        ))


# ======================================================================
# Call extraction helpers
# ======================================================================


def _extract_calls(func_node: ts.Node) -> list[str]:
    """Extract function/method call names from a function body."""
    calls: list[str] = []
    _walk_calls(func_node, calls)
    return calls


def _walk_calls(node: ts.Node, calls: list[str]) -> None:
    """Recursively walk to find call_expression nodes."""
    if node.type == "call_expression":
        func = node.children[0] if node.children else None
        if func is not None:
            name = _call_name(func)
            if name is not None:
                calls.append(name)
    for child in node.children:
        _walk_calls(child, calls)


def _call_name(node: ts.Node) -> str | None:
    """Extract the callable name from a call expression's function node."""
    if node.type == "identifier":
        return _node_text(node)
    if node.type == "member_expression":
        obj = node.children[0] if node.children else None
        prop = _find_child(node, "property_identifier")
        if obj is not None and prop is not None:
            obj_name = _call_name(obj)
            if obj_name is not None:
                return f"{obj_name}.{_node_text(prop)}"
            return _node_text(prop)
    return None


# ======================================================================
# Entry point detection
# ======================================================================


def _detect_entry_point(path: Path) -> bool:
    """Detect whether the file is a TS/JS entry point.

    Entry points are files named index, main, or app (any supported extension).
    """
    return path.stem in _ENTRY_POINT_STEMS


# ======================================================================
# Import resolution helpers
# ======================================================================


def _resolve_relative(source: str, from_file: Path) -> Path | None:
    """Resolve a relative import path to a file on disk.

    Tries the source as-is, then with various extensions, then as a
    directory with index files.
    """
    base = from_file.parent
    target = base / source

    # 1. Try exact path (already has extension)
    if target.is_file():
        return target

    # 2. Try appending extensions
    for ext in _RESOLVE_EXTENSIONS:
        candidate = target.with_suffix(ext)
        if candidate.is_file():
            return candidate

    # 3. Try as directory with index file
    if target.is_dir():
        for ext in _RESOLVE_EXTENSIONS:
            index = target / f"index{ext}"
            if index.is_file():
                return index

    return None


# ======================================================================
# Tree-sitter helpers
# ======================================================================


def _find_child(node: ts.Node, child_type: str) -> ts.Node | None:
    """Find the first child of a given type."""
    for child in node.children:
        if child.type == child_type:
            return child
    return None


def _node_text(node: ts.Node) -> str:
    """Decode a node's text to a string.

    tree-sitter's ``Node.text`` is typed as ``bytes | None`` but in
    practice is always ``bytes`` for parsed nodes.  This helper
    satisfies pyright while keeping call sites concise.
    """
    raw = node.text
    if raw is None:
        return ""
    return raw.decode()


def _get_import_source(node: ts.Node) -> str | None:
    """Extract the module source string from an import statement."""
    string_node = _find_child(node, "string")
    if string_node is None:
        return None
    return _get_string_value(string_node)


def _get_string_argument(args_node: ts.Node) -> str | None:
    """Extract the first string argument from a call's arguments node."""
    string_node = _find_child(args_node, "string")
    if string_node is None:
        return None
    return _get_string_value(string_node)


def _get_string_value(string_node: ts.Node) -> str | None:
    """Extract the text content from a string node (strip quotes)."""
    fragment = _find_child(string_node, "string_fragment")
    if fragment is not None:
        return _node_text(fragment)
    # Fallback: decode and strip quotes
    text = _node_text(string_node)
    if len(text) >= 2 and text[0] in ('"', "'", "`"):
        return text[1:-1]
    return None
