"""Tests for symbol-level usage tracking (BED-100).

Tests the join of import specifiers to export symbols, per-symbol caller
count computation, and symbol_usage emission in the dependency graph.
"""

from __future__ import annotations

import pytest

from nlv.graph import (
    SymbolUsageEntry,
    build_graph,
)
from nlv.plugins import ExportKind, ExportRef, ImportRef, ParseResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    *,
    imports: tuple[ImportRef, ...] = (),
    exports: tuple[ExportRef, ...] = (),
) -> ParseResult:
    """Create a ParseResult with specified imports and exports."""
    return ParseResult(
        imports=imports, exports=exports, functions=(), entry_point=False,
    )


# ---------------------------------------------------------------------------
# SymbolUsageEntry dataclass
# ---------------------------------------------------------------------------


class TestSymbolUsageEntry:
    """Tests for the SymbolUsageEntry dataclass."""

    def test_create_entry(self) -> None:
        entry = SymbolUsageEntry(callers=3, used_by=("a.py", "b.py", "c.py"))
        assert entry.callers == 3
        assert entry.used_by == ("a.py", "b.py", "c.py")

    def test_frozen(self) -> None:
        entry = SymbolUsageEntry(callers=0, used_by=())
        with pytest.raises(AttributeError):
            entry.callers = 1  # type: ignore[misc]

    def test_zero_callers(self) -> None:
        entry = SymbolUsageEntry(callers=0, used_by=())
        assert entry.callers == 0
        assert entry.used_by == ()

    def test_callers_must_match_used_by_length(self) -> None:
        with pytest.raises(ValueError, match="callers=2 != len"):
            SymbolUsageEntry(callers=2, used_by=("a.py",))


# ---------------------------------------------------------------------------
# Symbol usage computation via build_graph
# ---------------------------------------------------------------------------


class TestSymbolUsageComputation:
    """Tests for symbol-level usage tracking in the dependency graph."""

    def test_simple_one_importer(self) -> None:
        """B exports foo, A imports foo from B → B.foo: callers=1."""
        results = {
            "b.py": _make_result(
                exports=(
                    ExportRef(name="foo", kind=ExportKind.FUNCTION, line=1),
                ),
            ),
            "a.py": _make_result(
                imports=(
                    ImportRef(source="b", specifiers=("foo",), is_relative=False),
                ),
            ),
        }
        resolved = {("a.py", "b"): "b.py"}
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        assert "b.py" in graph.symbol_usage
        assert "foo" in graph.symbol_usage["b.py"]
        assert graph.symbol_usage["b.py"]["foo"].callers == 1
        assert graph.symbol_usage["b.py"]["foo"].used_by == ("a.py",)

    def test_multiple_importers(self) -> None:
        """B exports foo, A and C both import foo → B.foo: callers=2."""
        results = {
            "b.py": _make_result(
                exports=(
                    ExportRef(name="foo", kind=ExportKind.FUNCTION, line=1),
                ),
            ),
            "a.py": _make_result(
                imports=(
                    ImportRef(source="b", specifiers=("foo",), is_relative=False),
                ),
            ),
            "c.py": _make_result(
                imports=(
                    ImportRef(source="b", specifiers=("foo",), is_relative=False),
                ),
            ),
        }
        resolved = {
            ("a.py", "b"): "b.py",
            ("c.py", "b"): "b.py",
        }
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        usage = graph.symbol_usage["b.py"]["foo"]
        assert usage.callers == 2
        assert set(usage.used_by) == {"a.py", "c.py"}
        # used_by must be sorted for determinism
        assert usage.used_by == tuple(sorted(usage.used_by))

    def test_unused_export_has_zero_callers(self) -> None:
        """B exports foo and bar, only foo imported → bar: callers=0."""
        results = {
            "b.py": _make_result(
                exports=(
                    ExportRef(name="foo", kind=ExportKind.FUNCTION, line=1),
                    ExportRef(name="bar", kind=ExportKind.FUNCTION, line=10),
                ),
            ),
            "a.py": _make_result(
                imports=(
                    ImportRef(source="b", specifiers=("foo",), is_relative=False),
                ),
            ),
        }
        resolved = {("a.py", "b"): "b.py"}
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        assert graph.symbol_usage["b.py"]["foo"].callers == 1
        assert graph.symbol_usage["b.py"]["bar"].callers == 0
        assert graph.symbol_usage["b.py"]["bar"].used_by == ()

    def test_multiple_specifiers_from_same_import(self) -> None:
        """A does `from B import foo, bar` → both get callers=1."""
        results = {
            "b.py": _make_result(
                exports=(
                    ExportRef(name="foo", kind=ExportKind.FUNCTION, line=1),
                    ExportRef(name="bar", kind=ExportKind.CLASS, line=10),
                ),
            ),
            "a.py": _make_result(
                imports=(
                    ImportRef(
                        source="b",
                        specifiers=("foo", "bar"),
                        is_relative=False,
                    ),
                ),
            ),
        }
        resolved = {("a.py", "b"): "b.py"}
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        assert graph.symbol_usage["b.py"]["foo"].callers == 1
        assert graph.symbol_usage["b.py"]["foo"].used_by == ("a.py",)
        assert graph.symbol_usage["b.py"]["bar"].callers == 1
        assert graph.symbol_usage["b.py"]["bar"].used_by == ("a.py",)

    def test_empty_specifiers_no_symbol_matching(self) -> None:
        """Star import (empty specifiers) doesn't match individual exports."""
        results = {
            "b.py": _make_result(
                exports=(
                    ExportRef(name="foo", kind=ExportKind.FUNCTION, line=1),
                ),
            ),
            "a.py": _make_result(
                imports=(
                    ImportRef(source="b", specifiers=(), is_relative=False),
                ),
            ),
        }
        resolved = {("a.py", "b"): "b.py"}
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        # foo should still appear with callers=0 since specifiers was empty
        assert graph.symbol_usage["b.py"]["foo"].callers == 0

    def test_file_with_no_exports_has_empty_symbol_usage(self) -> None:
        """A file with no exports has an empty symbol_usage dict."""
        results = {
            "a.py": _make_result(),
        }
        graph = build_graph(parse_results=results, resolved_imports={})

        assert graph.symbol_usage["a.py"] == {}

    def test_specifier_not_matching_any_export(self) -> None:
        """Import specifier that doesn't match any export is ignored."""
        results = {
            "b.py": _make_result(
                exports=(
                    ExportRef(name="foo", kind=ExportKind.FUNCTION, line=1),
                ),
            ),
            "a.py": _make_result(
                imports=(
                    ImportRef(
                        source="b",
                        specifiers=("nonexistent",),
                        is_relative=False,
                    ),
                ),
            ),
        }
        resolved = {("a.py", "b"): "b.py"}
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        # foo still tracked, but with callers=0
        assert graph.symbol_usage["b.py"]["foo"].callers == 0
        # nonexistent is not in symbol_usage (it's not an export)
        assert "nonexistent" not in graph.symbol_usage["b.py"]

    def test_external_imports_excluded_from_symbol_usage(self) -> None:
        """External imports don't get symbol_usage entries."""
        results = {
            "a.py": _make_result(
                imports=(
                    ImportRef(
                        source="requests",
                        specifiers=("get",),
                        is_relative=False,
                    ),
                ),
            ),
        }
        graph = build_graph(parse_results=results, resolved_imports={})

        # Only a.py should have symbol_usage (empty, no exports)
        assert "requests" not in graph.symbol_usage
        assert graph.symbol_usage["a.py"] == {}

    def test_diamond_symbol_usage(self) -> None:
        """Diamond: A→B, A→C, B→D, C→D with varying symbol imports."""
        results = {
            "d.py": _make_result(
                exports=(
                    ExportRef(name="query", kind=ExportKind.FUNCTION, line=1),
                    ExportRef(name="connect", kind=ExportKind.FUNCTION, line=20),
                ),
            ),
            "b.py": _make_result(
                imports=(
                    ImportRef(
                        source="d", specifiers=("query",), is_relative=False,
                    ),
                ),
                exports=(
                    ExportRef(name="get_user", kind=ExportKind.FUNCTION, line=1),
                ),
            ),
            "c.py": _make_result(
                imports=(
                    ImportRef(
                        source="d",
                        specifiers=("query", "connect"),
                        is_relative=False,
                    ),
                ),
                exports=(
                    ExportRef(name="get_posts", kind=ExportKind.FUNCTION, line=1),
                ),
            ),
            "a.py": _make_result(
                imports=(
                    ImportRef(
                        source="b", specifiers=("get_user",), is_relative=False,
                    ),
                    ImportRef(
                        source="c", specifiers=("get_posts",), is_relative=False,
                    ),
                ),
            ),
        }
        resolved = {
            ("a.py", "b"): "b.py",
            ("a.py", "c"): "c.py",
            ("b.py", "d"): "d.py",
            ("c.py", "d"): "d.py",
        }
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        # d.query used by both b and c
        assert graph.symbol_usage["d.py"]["query"].callers == 2
        # d.connect used only by c
        assert graph.symbol_usage["d.py"]["connect"].callers == 1
        assert graph.symbol_usage["d.py"]["connect"].used_by == ("c.py",)
        # b.get_user used only by a
        assert graph.symbol_usage["b.py"]["get_user"].callers == 1
        assert graph.symbol_usage["b.py"]["get_user"].used_by == ("a.py",)
        # c.get_posts used only by a
        assert graph.symbol_usage["c.py"]["get_posts"].callers == 1

    def test_symbol_usage_deterministic(self) -> None:
        """Same input produces identical symbol_usage."""
        results = {
            "b.py": _make_result(
                exports=(
                    ExportRef(name="foo", kind=ExportKind.FUNCTION, line=1),
                    ExportRef(name="bar", kind=ExportKind.VARIABLE, line=5),
                ),
            ),
            "a.py": _make_result(
                imports=(
                    ImportRef(
                        source="b",
                        specifiers=("foo", "bar"),
                        is_relative=False,
                    ),
                ),
            ),
            "c.py": _make_result(
                imports=(
                    ImportRef(
                        source="b", specifiers=("foo",), is_relative=False,
                    ),
                ),
            ),
        }
        resolved = {
            ("a.py", "b"): "b.py",
            ("c.py", "b"): "b.py",
        }
        g1 = build_graph(parse_results=results, resolved_imports=resolved)
        g2 = build_graph(parse_results=results, resolved_imports=resolved)

        assert g1.symbol_usage == g2.symbol_usage

    def test_all_known_files_have_symbol_usage_key(self) -> None:
        """Every file in the graph has a symbol_usage entry (possibly empty)."""
        results = {
            "a.py": _make_result(),
            "b.py": _make_result(
                exports=(
                    ExportRef(name="x", kind=ExportKind.VARIABLE, line=1),
                ),
            ),
            "c.py": _make_result(
                imports=(
                    ImportRef(source="b", specifiers=("x",), is_relative=False),
                ),
            ),
        }
        resolved = {("c.py", "b"): "b.py"}
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        for path in results:
            assert path in graph.symbol_usage
