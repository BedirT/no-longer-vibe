"""Tests for the dependency graph builder (BED-64).

Tests the directed graph construction from parsed imports, cycle detection,
dependency depth computation, reverse dependencies, and derived metrics.
"""

from __future__ import annotations

import pytest

from nlv.graph import (
    DependencyGraph,
    ExternalDep,
    FileNode,
    build_graph,
)
from nlv.plugins import ImportRef, ParseResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_result() -> ParseResult:
    """Return an empty ParseResult (no imports, no exports)."""
    return ParseResult(imports=(), exports=(), functions=(), entry_point=False)


def _result_with_imports(*sources: tuple[str, bool]) -> ParseResult:
    """Return a ParseResult with the given imports.

    Each source is (module_source, is_relative).
    """
    imports = tuple(
        ImportRef(source=s, specifiers=(), is_relative=rel)
        for s, rel in sources
    )
    return ParseResult(
        imports=imports, exports=(), functions=(), entry_point=False,
    )


# ---------------------------------------------------------------------------
# FileNode dataclass tests
# ---------------------------------------------------------------------------


class TestFileNode:
    """Tests for the FileNode dataclass."""

    def test_create_file_node(self) -> None:
        node = FileNode(
            path="src/config.py",
            imports=("src/utils.py",),
            imported_by=("src/app.py",),
            fan_in=1,
            fan_out=1,
            depth=0,
            is_leaf=False,
            is_root=False,
        )
        assert node.path == "src/config.py"
        assert node.imports == ("src/utils.py",)
        assert node.imported_by == ("src/app.py",)
        assert node.fan_in == 1
        assert node.fan_out == 1
        assert node.depth == 0
        assert node.is_leaf is False
        assert node.is_root is False

    def test_root_node_has_no_imports(self) -> None:
        node = FileNode(
            path="src/constants.py",
            imports=(),
            imported_by=("src/config.py",),
            fan_in=1,
            fan_out=0,
            depth=0,
            is_leaf=False,
            is_root=True,
        )
        assert node.is_root is True
        assert node.fan_out == 0

    def test_leaf_node_has_no_importers(self) -> None:
        node = FileNode(
            path="src/main.py",
            imports=("src/app.py",),
            imported_by=(),
            fan_in=0,
            fan_out=1,
            depth=1,
            is_leaf=True,
            is_root=False,
        )
        assert node.is_leaf is True
        assert node.fan_in == 0

    def test_frozen_dataclass(self) -> None:
        node = FileNode(
            path="src/x.py",
            imports=(),
            imported_by=(),
            fan_in=0,
            fan_out=0,
            depth=0,
            is_leaf=True,
            is_root=True,
        )
        with pytest.raises(AttributeError):
            node.path = "src/y.py"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ExternalDep dataclass tests
# ---------------------------------------------------------------------------


class TestExternalDep:
    """Tests for the ExternalDep dataclass."""

    def test_create_external_dep(self) -> None:
        dep = ExternalDep(
            source="os.path",
            imported_by=("src/utils.py", "src/config.py"),
        )
        assert dep.source == "os.path"
        assert dep.imported_by == ("src/utils.py", "src/config.py")

    def test_frozen_dataclass(self) -> None:
        dep = ExternalDep(source="sys", imported_by=("src/main.py",))
        with pytest.raises(AttributeError):
            dep.source = "os"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DependencyGraph dataclass tests
# ---------------------------------------------------------------------------


class TestDependencyGraph:
    """Tests for the DependencyGraph result dataclass."""

    def test_create_graph(self) -> None:
        node = FileNode(
            path="src/a.py",
            imports=(),
            imported_by=(),
            fan_in=0,
            fan_out=0,
            depth=0,
            is_leaf=True,
            is_root=True,
        )
        graph = DependencyGraph(
            nodes={"src/a.py": node},
            external_deps=(),
            cycles=(),
        )
        assert "src/a.py" in graph.nodes
        assert graph.external_deps == ()
        assert graph.cycles == ()


# ---------------------------------------------------------------------------
# build_graph — basic construction
# ---------------------------------------------------------------------------


class TestBuildGraphBasic:
    """Tests for basic graph construction from parse results."""

    def test_empty_input_returns_empty_graph(self) -> None:
        graph = build_graph(
            parse_results={},
            resolved_imports={},
        )
        assert graph.nodes == {}
        assert graph.external_deps == ()
        assert graph.cycles == ()

    def test_single_file_no_imports(self) -> None:
        graph = build_graph(
            parse_results={"src/config.py": _empty_result()},
            resolved_imports={},
        )
        assert "src/config.py" in graph.nodes
        node = graph.nodes["src/config.py"]
        assert node.imports == ()
        assert node.imported_by == ()
        assert node.fan_in == 0
        assert node.fan_out == 0
        assert node.is_leaf is True
        assert node.is_root is True
        assert node.depth == 0

    def test_two_files_one_imports_the_other(self) -> None:
        results = {
            "src/config.py": _empty_result(),
            "src/app.py": _result_with_imports(("config", False)),
        }
        resolved = {
            ("src/app.py", "config"): "src/config.py",
        }
        graph = build_graph(
            parse_results=results,
            resolved_imports=resolved,
        )
        # app imports config
        app_node = graph.nodes["src/app.py"]
        assert "src/config.py" in app_node.imports
        assert app_node.fan_out == 1
        assert app_node.is_leaf is True  # nothing imports app

        # config is imported by app
        config_node = graph.nodes["src/config.py"]
        assert "src/app.py" in config_node.imported_by
        assert config_node.fan_in == 1
        assert config_node.is_root is True  # config imports nothing

    def test_diamond_dependency(self) -> None:
        """A -> B, A -> C, B -> D, C -> D (diamond shape)."""
        results = {
            "d.py": _empty_result(),
            "b.py": _result_with_imports(("d", False)),
            "c.py": _result_with_imports(("d", False)),
            "a.py": _result_with_imports(("b", False), ("c", False)),
        }
        resolved = {
            ("a.py", "b"): "b.py",
            ("a.py", "c"): "c.py",
            ("b.py", "d"): "d.py",
            ("c.py", "d"): "d.py",
        }
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        assert graph.nodes["d.py"].fan_in == 2
        assert graph.nodes["d.py"].is_root is True
        assert graph.nodes["a.py"].fan_out == 2
        assert graph.nodes["a.py"].is_leaf is True

    def test_chain_dependency(self) -> None:
        """a -> b -> c -> d (linear chain)."""
        results = {
            "d.py": _empty_result(),
            "c.py": _result_with_imports(("d", False)),
            "b.py": _result_with_imports(("c", False)),
            "a.py": _result_with_imports(("b", False)),
        }
        resolved = {
            ("a.py", "b"): "b.py",
            ("b.py", "c"): "c.py",
            ("c.py", "d"): "d.py",
        }
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        assert graph.nodes["a.py"].fan_out == 1
        assert graph.nodes["d.py"].fan_in == 1
        assert graph.nodes["d.py"].is_root is True
        assert graph.nodes["a.py"].is_leaf is True


# ---------------------------------------------------------------------------
# build_graph — dependency depth
# ---------------------------------------------------------------------------


class TestBuildGraphDepth:
    """Tests for dependency depth computation."""

    def test_single_file_depth_zero(self) -> None:
        graph = build_graph(
            parse_results={"a.py": _empty_result()},
            resolved_imports={},
        )
        assert graph.nodes["a.py"].depth == 0

    def test_chain_depth_increments(self) -> None:
        """a -> b -> c: depths should be c=0, b=1, a=2."""
        results = {
            "c.py": _empty_result(),
            "b.py": _result_with_imports(("c", False)),
            "a.py": _result_with_imports(("b", False)),
        }
        resolved = {
            ("a.py", "b"): "b.py",
            ("b.py", "c"): "c.py",
        }
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        assert graph.nodes["c.py"].depth == 0
        assert graph.nodes["b.py"].depth == 1
        assert graph.nodes["a.py"].depth == 2

    def test_diamond_depth_takes_longest_path(self) -> None:
        """a -> b -> d, a -> c -> d: d=0, b=1, c=1, a=2."""
        results = {
            "d.py": _empty_result(),
            "b.py": _result_with_imports(("d", False)),
            "c.py": _result_with_imports(("d", False)),
            "a.py": _result_with_imports(("b", False), ("c", False)),
        }
        resolved = {
            ("a.py", "b"): "b.py",
            ("a.py", "c"): "c.py",
            ("b.py", "d"): "d.py",
            ("c.py", "d"): "d.py",
        }
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        assert graph.nodes["d.py"].depth == 0
        assert graph.nodes["b.py"].depth == 1
        assert graph.nodes["c.py"].depth == 1
        assert graph.nodes["a.py"].depth == 2

    def test_asymmetric_diamond_takes_longest_path(self) -> None:
        """a -> b -> c -> d, a -> d: a's depth should be 3 (longest path)."""
        results = {
            "d.py": _empty_result(),
            "c.py": _result_with_imports(("d", False)),
            "b.py": _result_with_imports(("c", False)),
            "a.py": _result_with_imports(("b", False), ("d", False)),
        }
        resolved = {
            ("a.py", "b"): "b.py",
            ("a.py", "d"): "d.py",
            ("b.py", "c"): "c.py",
            ("c.py", "d"): "d.py",
        }
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        assert graph.nodes["d.py"].depth == 0
        assert graph.nodes["c.py"].depth == 1
        assert graph.nodes["b.py"].depth == 2
        assert graph.nodes["a.py"].depth == 3


# ---------------------------------------------------------------------------
# build_graph — circular dependency handling
# ---------------------------------------------------------------------------


class TestBuildGraphCycles:
    """Tests for cycle detection and handling."""

    def test_two_file_cycle_detected(self) -> None:
        """a -> b -> a: should detect the cycle and not crash."""
        results = {
            "a.py": _result_with_imports(("b", False)),
            "b.py": _result_with_imports(("a", False)),
        }
        resolved = {
            ("a.py", "b"): "b.py",
            ("b.py", "a"): "a.py",
        }
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        # Both nodes must exist
        assert "a.py" in graph.nodes
        assert "b.py" in graph.nodes

        # Cycle must be reported
        assert len(graph.cycles) >= 1
        # Each cycle is a tuple of file paths
        cycle_files = set()
        for cycle in graph.cycles:
            cycle_files.update(cycle)
        assert "a.py" in cycle_files
        assert "b.py" in cycle_files

    def test_three_file_cycle_detected(self) -> None:
        """a -> b -> c -> a: should detect the cycle."""
        results = {
            "a.py": _result_with_imports(("b", False)),
            "b.py": _result_with_imports(("c", False)),
            "c.py": _result_with_imports(("a", False)),
        }
        resolved = {
            ("a.py", "b"): "b.py",
            ("b.py", "c"): "c.py",
            ("c.py", "a"): "a.py",
        }
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        assert len(graph.cycles) >= 1
        cycle_files = set()
        for cycle in graph.cycles:
            cycle_files.update(cycle)
        assert {"a.py", "b.py", "c.py"} <= cycle_files

    def test_self_import_cycle(self) -> None:
        """a -> a: self-import should be a cycle."""
        results = {
            "a.py": _result_with_imports(("a", False)),
        }
        resolved = {
            ("a.py", "a"): "a.py",
        }
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        assert "a.py" in graph.nodes
        assert len(graph.cycles) >= 1

    def test_cycle_nodes_get_finite_depth(self) -> None:
        """Nodes in cycles must not get infinite depth."""
        results = {
            "a.py": _result_with_imports(("b", False)),
            "b.py": _result_with_imports(("a", False)),
        }
        resolved = {
            ("a.py", "b"): "b.py",
            ("b.py", "a"): "a.py",
        }
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        # Depths should be finite non-negative integers
        assert graph.nodes["a.py"].depth >= 0
        assert graph.nodes["b.py"].depth >= 0

    def test_cycle_with_tail(self) -> None:
        """d -> a -> b -> c -> a: d depends on a cycle, d should still work."""
        results = {
            "a.py": _result_with_imports(("b", False)),
            "b.py": _result_with_imports(("c", False)),
            "c.py": _result_with_imports(("a", False)),
            "d.py": _result_with_imports(("a", False)),
        }
        resolved = {
            ("a.py", "b"): "b.py",
            ("b.py", "c"): "c.py",
            ("c.py", "a"): "a.py",
            ("d.py", "a"): "a.py",
        }
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        assert "d.py" in graph.nodes
        assert graph.nodes["d.py"].depth >= 0
        # d has higher depth than cycle members since it depends on them
        assert graph.nodes["d.py"].depth > 0


# ---------------------------------------------------------------------------
# build_graph — external dependencies
# ---------------------------------------------------------------------------


class TestBuildGraphExternalDeps:
    """Tests for external dependency tracking."""

    def test_unresolved_import_tracked_as_external(self) -> None:
        """Imports that don't resolve to local files are external."""
        results = {
            "a.py": _result_with_imports(("os.path", False), ("requests", False)),
        }
        # No resolved imports — both are external
        resolved: dict[tuple[str, str], str] = {}
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        assert len(graph.external_deps) == 2
        ext_sources = {dep.source for dep in graph.external_deps}
        assert "os.path" in ext_sources
        assert "requests" in ext_sources

    def test_external_deps_not_included_as_nodes(self) -> None:
        """External dependencies should not appear as graph nodes."""
        results = {
            "a.py": _result_with_imports(("os", False)),
        }
        resolved: dict[tuple[str, str], str] = {}
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        assert "os" not in graph.nodes
        assert len(graph.nodes) == 1  # only a.py

    def test_external_dep_imported_by_multiple_files(self) -> None:
        """External dep should list all importing files."""
        results = {
            "a.py": _result_with_imports(("requests", False)),
            "b.py": _result_with_imports(("requests", False)),
        }
        resolved: dict[tuple[str, str], str] = {}
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        req_deps = [d for d in graph.external_deps if d.source == "requests"]
        assert len(req_deps) == 1
        assert set(req_deps[0].imported_by) == {"a.py", "b.py"}

    def test_mix_of_local_and_external_imports(self) -> None:
        """File importing both local and external modules."""
        results = {
            "config.py": _empty_result(),
            "app.py": _result_with_imports(
                ("config", False), ("flask", False),
            ),
        }
        resolved = {
            ("app.py", "config"): "config.py",
        }
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        # config.py is a local node
        assert "config.py" in graph.nodes
        assert "config.py" in graph.nodes["app.py"].imports

        # flask is external
        ext_sources = {d.source for d in graph.external_deps}
        assert "flask" in ext_sources


# ---------------------------------------------------------------------------
# build_graph — reverse dependencies (imported_by)
# ---------------------------------------------------------------------------


class TestBuildGraphReverseDeps:
    """Tests for reverse dependency (imported_by) computation."""

    def test_imported_by_populated(self) -> None:
        results = {
            "config.py": _empty_result(),
            "app.py": _result_with_imports(("config", False)),
            "cli.py": _result_with_imports(("config", False)),
        }
        resolved = {
            ("app.py", "config"): "config.py",
            ("cli.py", "config"): "config.py",
        }
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        config_node = graph.nodes["config.py"]
        assert set(config_node.imported_by) == {"app.py", "cli.py"}
        assert config_node.fan_in == 2

    def test_imported_by_empty_for_leaf(self) -> None:
        results = {
            "config.py": _empty_result(),
            "app.py": _result_with_imports(("config", False)),
        }
        resolved = {
            ("app.py", "config"): "config.py",
        }
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        app_node = graph.nodes["app.py"]
        assert app_node.imported_by == ()
        assert app_node.fan_in == 0
        assert app_node.is_leaf is True


# ---------------------------------------------------------------------------
# build_graph — derived metrics
# ---------------------------------------------------------------------------


class TestBuildGraphMetrics:
    """Tests for derived metrics (fanIn, fanOut, isLeaf, isRoot)."""

    def test_fan_in_matches_imported_by_count(self) -> None:
        results = {
            "x.py": _empty_result(),
            "a.py": _result_with_imports(("x", False)),
            "b.py": _result_with_imports(("x", False)),
            "c.py": _result_with_imports(("x", False)),
        }
        resolved = {
            ("a.py", "x"): "x.py",
            ("b.py", "x"): "x.py",
            ("c.py", "x"): "x.py",
        }
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        assert graph.nodes["x.py"].fan_in == 3
        assert len(graph.nodes["x.py"].imported_by) == 3

    def test_fan_out_matches_imports_count(self) -> None:
        results = {
            "x.py": _empty_result(),
            "y.py": _empty_result(),
            "z.py": _empty_result(),
            "a.py": _result_with_imports(
                ("x", False), ("y", False), ("z", False),
            ),
        }
        resolved = {
            ("a.py", "x"): "x.py",
            ("a.py", "y"): "y.py",
            ("a.py", "z"): "z.py",
        }
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        assert graph.nodes["a.py"].fan_out == 3
        assert len(graph.nodes["a.py"].imports) == 3

    def test_is_leaf_when_nothing_imports_it(self) -> None:
        results = {
            "config.py": _empty_result(),
            "app.py": _result_with_imports(("config", False)),
        }
        resolved = {("app.py", "config"): "config.py"}
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        assert graph.nodes["app.py"].is_leaf is True
        assert graph.nodes["config.py"].is_leaf is False

    def test_is_root_when_imports_nothing(self) -> None:
        results = {
            "config.py": _empty_result(),
            "app.py": _result_with_imports(("config", False)),
        }
        resolved = {("app.py", "config"): "config.py"}
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        assert graph.nodes["config.py"].is_root is True
        assert graph.nodes["app.py"].is_root is False

    def test_isolated_file_is_both_leaf_and_root(self) -> None:
        results = {"standalone.py": _empty_result()}
        graph = build_graph(parse_results=results, resolved_imports={})

        node = graph.nodes["standalone.py"]
        assert node.is_leaf is True
        assert node.is_root is True
        assert node.fan_in == 0
        assert node.fan_out == 0


# ---------------------------------------------------------------------------
# build_graph — determinism
# ---------------------------------------------------------------------------


class TestBuildGraphDeterminism:
    """Tests that build_graph produces deterministic output."""

    def test_same_input_same_output(self) -> None:
        """Running build_graph twice with same input must give same result."""
        results = {
            "c.py": _empty_result(),
            "b.py": _result_with_imports(("c", False)),
            "a.py": _result_with_imports(("b", False), ("c", False)),
        }
        resolved = {
            ("a.py", "b"): "b.py",
            ("a.py", "c"): "c.py",
            ("b.py", "c"): "c.py",
        }
        graph1 = build_graph(parse_results=results, resolved_imports=resolved)
        graph2 = build_graph(parse_results=results, resolved_imports=resolved)

        for path in results:
            n1 = graph1.nodes[path]
            n2 = graph2.nodes[path]
            assert n1.imports == n2.imports
            assert n1.imported_by == n2.imported_by
            assert n1.fan_in == n2.fan_in
            assert n1.fan_out == n2.fan_out
            assert n1.depth == n2.depth
            assert n1.is_leaf == n2.is_leaf
            assert n1.is_root == n2.is_root

    def test_tuples_are_sorted(self) -> None:
        """imports and imported_by tuples should be sorted for determinism."""
        results = {
            "z.py": _empty_result(),
            "a.py": _empty_result(),
            "m.py": _result_with_imports(("z", False), ("a", False)),
        }
        resolved = {
            ("m.py", "z"): "z.py",
            ("m.py", "a"): "a.py",
        }
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        # imports should be sorted
        assert graph.nodes["m.py"].imports == ("a.py", "z.py")
        # imported_by for z.py and a.py should be sorted
        assert graph.nodes["z.py"].imported_by == ("m.py",)
        assert graph.nodes["a.py"].imported_by == ("m.py",)


# ---------------------------------------------------------------------------
# build_graph — edge cases
# ---------------------------------------------------------------------------


class TestBuildGraphEdgeCases:
    """Tests for edge cases in graph construction."""

    def test_import_resolves_to_unknown_file(self) -> None:
        """If resolved path is not in parse_results, treat as external."""
        results = {
            "a.py": _result_with_imports(("missing", False)),
        }
        resolved = {
            ("a.py", "missing"): "missing.py",
        }
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        # missing.py is not in parse_results, so it's not a node
        assert "missing.py" not in graph.nodes
        # a.py should not list it as a local import
        assert "missing.py" not in graph.nodes["a.py"].imports
        assert graph.nodes["a.py"].fan_out == 0

    def test_duplicate_imports_deduplicated(self) -> None:
        """If a file imports the same module twice, only one edge."""
        results = {
            "b.py": _empty_result(),
            "a.py": _result_with_imports(("b", False), ("b", False)),
        }
        resolved = {
            ("a.py", "b"): "b.py",
        }
        graph = build_graph(parse_results=results, resolved_imports=resolved)

        assert graph.nodes["a.py"].fan_out == 1
        assert graph.nodes["b.py"].fan_in == 1

    def test_large_graph(self) -> None:
        """Graph with 100 files in a chain does not crash or hang."""
        n = 100
        files = [f"f{i}.py" for i in range(n)]
        results: dict[str, ParseResult] = {}
        resolved: dict[tuple[str, str], str] = {}

        results[files[0]] = _empty_result()
        for i in range(1, n):
            results[files[i]] = _result_with_imports(
                (f"f{i-1}", False),
            )
            resolved[(files[i], f"f{i-1}")] = files[i - 1]

        graph = build_graph(parse_results=results, resolved_imports=resolved)

        assert len(graph.nodes) == n
        assert graph.nodes[files[0]].depth == 0
        assert graph.nodes[files[-1]].depth == n - 1
        assert graph.nodes[files[0]].is_root is True
        assert graph.nodes[files[-1]].is_leaf is True
