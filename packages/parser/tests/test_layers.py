"""Tests for the layer classifier (BED-65).

Tests the classification of files into foundation/core/features/integration/entry
layers based on their position in the dependency graph.
"""

from __future__ import annotations

import pytest

from nlv.graph import (
    DependencyGraph,
    build_graph,
)
from nlv.layers import (
    Layer,
    LayerClassification,
    classify_layers,
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


def _entry_result() -> ParseResult:
    """Return a ParseResult marked as an entry point."""
    return ParseResult(imports=(), exports=(), functions=(), entry_point=True)


def _entry_result_with_imports(*sources: tuple[str, bool]) -> ParseResult:
    """Return an entry-point ParseResult with imports."""
    imports = tuple(
        ImportRef(source=s, specifiers=(), is_relative=rel)
        for s, rel in sources
    )
    return ParseResult(
        imports=imports, exports=(), functions=(), entry_point=True,
    )


def _build_test_graph(
    results: dict[str, ParseResult],
    resolved: dict[tuple[str, str], str],
) -> DependencyGraph:
    """Build a DependencyGraph from test data."""
    return build_graph(parse_results=results, resolved_imports=resolved)


# ---------------------------------------------------------------------------
# Layer enum tests
# ---------------------------------------------------------------------------


class TestLayerEnum:
    """Tests for the Layer enum values."""

    def test_all_five_layers_exist(self) -> None:
        assert Layer.FOUNDATION.value == "foundation"
        assert Layer.CORE.value == "core"
        assert Layer.FEATURES.value == "features"
        assert Layer.INTEGRATION.value == "integration"
        assert Layer.ENTRY.value == "entry"

    def test_layer_count(self) -> None:
        assert len(Layer) == 5


# ---------------------------------------------------------------------------
# LayerClassification dataclass tests
# ---------------------------------------------------------------------------


class TestLayerClassification:
    """Tests for the LayerClassification result dataclass."""

    def test_create_classification(self) -> None:
        classification = LayerClassification(
            layers={
                "src/config.py": Layer.FOUNDATION,
                "src/app.py": Layer.ENTRY,
            },
            layer_groups={
                Layer.FOUNDATION: ("src/config.py",),
                Layer.CORE: (),
                Layer.FEATURES: (),
                Layer.INTEGRATION: (),
                Layer.ENTRY: ("src/app.py",),
            },
        )
        assert classification.layers["src/config.py"] == Layer.FOUNDATION
        assert classification.layers["src/app.py"] == Layer.ENTRY
        assert "src/config.py" in classification.layer_groups[Layer.FOUNDATION]

    def test_frozen_dataclass(self) -> None:
        classification = LayerClassification(
            layers={},
            layer_groups={
                Layer.FOUNDATION: (),
                Layer.CORE: (),
                Layer.FEATURES: (),
                Layer.INTEGRATION: (),
                Layer.ENTRY: (),
            },
        )
        with pytest.raises(AttributeError):
            classification.layers = {}  # type: ignore[misc]


# ---------------------------------------------------------------------------
# classify_layers — depth-based classification
# ---------------------------------------------------------------------------


class TestClassifyLayersDepth:
    """Tests for depth-based layer assignment."""

    def test_depth_zero_is_foundation(self) -> None:
        """Files with no dependencies (depth 0) -> foundation."""
        graph = _build_test_graph(
            results={"config.py": _empty_result()},
            resolved={},
        )
        result = classify_layers(graph=graph, entry_points=set())

        assert result.layers["config.py"] == Layer.FOUNDATION

    def test_depth_one_is_core(self) -> None:
        """Files at depth 1 -> core."""
        results = {
            "types.py": _empty_result(),
            "model.py": _result_with_imports(("types", False)),
        }
        resolved = {("model.py", "types"): "types.py"}
        graph = _build_test_graph(results, resolved)
        result = classify_layers(graph=graph, entry_points=set())

        assert result.layers["types.py"] == Layer.FOUNDATION
        assert result.layers["model.py"] == Layer.CORE

    def test_depth_two_is_features(self) -> None:
        """Files at depth 2 -> features."""
        results = {
            "types.py": _empty_result(),
            "model.py": _result_with_imports(("types", False)),
            "component.py": _result_with_imports(("model", False)),
        }
        resolved = {
            ("model.py", "types"): "types.py",
            ("component.py", "model"): "model.py",
        }
        graph = _build_test_graph(results, resolved)
        result = classify_layers(graph=graph, entry_points=set())

        assert result.layers["component.py"] == Layer.FEATURES

    def test_depth_three_low_fan_in_is_features(self) -> None:
        """Files at depth 3 with low fanIn -> features."""
        results = {
            "types.py": _empty_result(),
            "model.py": _result_with_imports(("types", False)),
            "service.py": _result_with_imports(("model", False)),
            "route.py": _result_with_imports(("service", False)),
        }
        resolved = {
            ("model.py", "types"): "types.py",
            ("service.py", "model"): "model.py",
            ("route.py", "service"): "service.py",
        }
        graph = _build_test_graph(results, resolved)
        result = classify_layers(graph=graph, entry_points=set())

        assert result.layers["route.py"] == Layer.FEATURES

    def test_depth_three_with_high_fan_in_is_integration(self) -> None:
        """Files at depth 3 with high fanIn -> integration."""
        results = {
            "types.py": _empty_result(),
            "model.py": _result_with_imports(("types", False)),
            "service.py": _result_with_imports(("model", False)),
            "middleware.py": _result_with_imports(("service", False)),
            # Three consumers to hit threshold
            "consumer_a.py": _result_with_imports(("middleware", False)),
            "consumer_b.py": _result_with_imports(("middleware", False)),
            "consumer_c.py": _result_with_imports(("middleware", False)),
        }
        resolved = {
            ("model.py", "types"): "types.py",
            ("service.py", "model"): "model.py",
            ("middleware.py", "service"): "service.py",
            ("consumer_a.py", "middleware"): "middleware.py",
            ("consumer_b.py", "middleware"): "middleware.py",
            ("consumer_c.py", "middleware"): "middleware.py",
        }
        graph = _build_test_graph(results, resolved)
        result = classify_layers(graph=graph, entry_points=set())

        # middleware.py: depth 3, fan_in 3 -> integration
        assert result.layers["middleware.py"] == Layer.INTEGRATION

    def test_depth_four_plus_with_high_fan_in_is_integration(self) -> None:
        """Files at depth 4+ with high fanIn -> integration."""
        # Build: types -> model -> service -> handler -> middleware
        # middleware also imported by several files to get high fan_in
        results = {
            "types.py": _empty_result(),
            "model.py": _result_with_imports(("types", False)),
            "service.py": _result_with_imports(("model", False)),
            "handler.py": _result_with_imports(("service", False)),
            "middleware.py": _result_with_imports(("handler", False)),
            # Extra files to import middleware (boost fan_in)
            "consumer_a.py": _result_with_imports(("middleware", False)),
            "consumer_b.py": _result_with_imports(("middleware", False)),
            "consumer_c.py": _result_with_imports(("middleware", False)),
        }
        resolved = {
            ("model.py", "types"): "types.py",
            ("service.py", "model"): "model.py",
            ("handler.py", "service"): "service.py",
            ("middleware.py", "handler"): "handler.py",
            ("consumer_a.py", "middleware"): "middleware.py",
            ("consumer_b.py", "middleware"): "middleware.py",
            ("consumer_c.py", "middleware"): "middleware.py",
        }
        graph = _build_test_graph(results, resolved)
        result = classify_layers(graph=graph, entry_points=set())

        assert result.layers["middleware.py"] == Layer.INTEGRATION

    def test_depth_four_plus_low_fan_in_is_features(self) -> None:
        """Files at depth 4+ but low fanIn -> features (bias deeper)."""
        results = {
            "a.py": _empty_result(),
            "b.py": _result_with_imports(("a", False)),
            "c.py": _result_with_imports(("b", False)),
            "d.py": _result_with_imports(("c", False)),
            "e.py": _result_with_imports(("d", False)),
        }
        resolved = {
            ("b.py", "a"): "a.py",
            ("c.py", "b"): "b.py",
            ("d.py", "c"): "c.py",
            ("e.py", "d"): "d.py",
        }
        graph = _build_test_graph(results, resolved)
        result = classify_layers(graph=graph, entry_points=set())

        # depth 4, fan_in=0 -> not integration, should be features
        assert result.layers["e.py"] == Layer.FEATURES


# ---------------------------------------------------------------------------
# classify_layers — entry point handling
# ---------------------------------------------------------------------------


class TestClassifyLayersEntryPoints:
    """Tests for entry point classification."""

    def test_entry_point_overrides_depth(self) -> None:
        """Entry points should be classified as 'entry' regardless of depth."""
        results = {
            "config.py": _empty_result(),
            "main.py": _result_with_imports(("config", False)),
        }
        resolved = {("main.py", "config"): "config.py"}
        graph = _build_test_graph(results, resolved)
        result = classify_layers(
            graph=graph,
            entry_points={"main.py"},
        )

        assert result.layers["main.py"] == Layer.ENTRY

    def test_entry_point_at_depth_zero(self) -> None:
        """Entry point with no deps is still entry, not foundation."""
        graph = _build_test_graph(
            results={"main.py": _empty_result()},
            resolved={},
        )
        result = classify_layers(
            graph=graph,
            entry_points={"main.py"},
        )

        assert result.layers["main.py"] == Layer.ENTRY

    def test_entry_point_deep_in_graph(self) -> None:
        """Entry point deep in the dependency chain is still entry."""
        results = {
            "types.py": _empty_result(),
            "model.py": _result_with_imports(("types", False)),
            "service.py": _result_with_imports(("model", False)),
            "app.py": _result_with_imports(("service", False)),
        }
        resolved = {
            ("model.py", "types"): "types.py",
            ("service.py", "model"): "model.py",
            ("app.py", "service"): "service.py",
        }
        graph = _build_test_graph(results, resolved)
        result = classify_layers(
            graph=graph,
            entry_points={"app.py"},
        )

        assert result.layers["app.py"] == Layer.ENTRY

    def test_multiple_entry_points(self) -> None:
        """Multiple entry points should all be classified as entry."""
        results = {
            "config.py": _empty_result(),
            "main.py": _result_with_imports(("config", False)),
            "cli.py": _result_with_imports(("config", False)),
        }
        resolved = {
            ("main.py", "config"): "config.py",
            ("cli.py", "config"): "config.py",
        }
        graph = _build_test_graph(results, resolved)
        result = classify_layers(
            graph=graph,
            entry_points={"main.py", "cli.py"},
        )

        assert result.layers["main.py"] == Layer.ENTRY
        assert result.layers["cli.py"] == Layer.ENTRY


# ---------------------------------------------------------------------------
# classify_layers — layer_groups output
# ---------------------------------------------------------------------------


class TestClassifyLayersGroups:
    """Tests for the layer_groups output."""

    def test_all_five_layers_present_in_groups(self) -> None:
        """layer_groups should contain all five layers, even if empty."""
        graph = _build_test_graph(
            results={"config.py": _empty_result()},
            resolved={},
        )
        result = classify_layers(graph=graph, entry_points=set())

        for layer in Layer:
            assert layer in result.layer_groups

    def test_groups_contain_correct_files(self) -> None:
        """Files should appear in the group matching their layer."""
        results = {
            "types.py": _empty_result(),
            "model.py": _result_with_imports(("types", False)),
            "main.py": _result_with_imports(("model", False)),
        }
        resolved = {
            ("model.py", "types"): "types.py",
            ("main.py", "model"): "model.py",
        }
        graph = _build_test_graph(results, resolved)
        result = classify_layers(
            graph=graph,
            entry_points={"main.py"},
        )

        assert "types.py" in result.layer_groups[Layer.FOUNDATION]
        assert "model.py" in result.layer_groups[Layer.CORE]
        assert "main.py" in result.layer_groups[Layer.ENTRY]

    def test_groups_tuples_are_sorted(self) -> None:
        """File lists in layer_groups should be sorted for determinism."""
        results = {
            "z_config.py": _empty_result(),
            "a_types.py": _empty_result(),
            "m_const.py": _empty_result(),
        }
        graph = _build_test_graph(results, resolved={})
        result = classify_layers(graph=graph, entry_points=set())

        foundation_files = result.layer_groups[Layer.FOUNDATION]
        assert foundation_files == tuple(sorted(foundation_files))


# ---------------------------------------------------------------------------
# classify_layers — empty and edge cases
# ---------------------------------------------------------------------------


class TestClassifyLayersEdgeCases:
    """Tests for edge cases in layer classification."""

    def test_empty_graph(self) -> None:
        """Empty graph produces empty classification with all layer keys."""
        graph = _build_test_graph(results={}, resolved={})
        result = classify_layers(graph=graph, entry_points=set())

        assert result.layers == {}
        for layer in Layer:
            assert result.layer_groups[layer] == ()

    def test_single_isolated_file(self) -> None:
        """Single file with no deps -> foundation."""
        graph = _build_test_graph(
            results={"standalone.py": _empty_result()},
            resolved={},
        )
        result = classify_layers(graph=graph, entry_points=set())

        assert result.layers["standalone.py"] == Layer.FOUNDATION

    def test_cycle_members_get_classified(self) -> None:
        """Files in a cycle should still get a layer assignment."""
        results = {
            "a.py": _result_with_imports(("b", False)),
            "b.py": _result_with_imports(("a", False)),
        }
        resolved = {
            ("a.py", "b"): "b.py",
            ("b.py", "a"): "a.py",
        }
        graph = _build_test_graph(results, resolved)
        result = classify_layers(graph=graph, entry_points=set())

        assert "a.py" in result.layers
        assert "b.py" in result.layers
        # Both should have a valid Layer value
        assert isinstance(result.layers["a.py"], Layer)
        assert isinstance(result.layers["b.py"], Layer)

    def test_entry_point_not_in_graph_ignored(self) -> None:
        """Entry points not present in the graph should be ignored."""
        graph = _build_test_graph(
            results={"config.py": _empty_result()},
            resolved={},
        )
        result = classify_layers(
            graph=graph,
            entry_points={"nonexistent.py"},
        )

        assert result.layers["config.py"] == Layer.FOUNDATION
        assert "nonexistent.py" not in result.layers


# ---------------------------------------------------------------------------
# classify_layers — determinism
# ---------------------------------------------------------------------------


class TestClassifyLayersDeterminism:
    """Tests that classify_layers produces deterministic output."""

    def test_same_input_same_output(self) -> None:
        """Running classify_layers twice with same input must give same result."""
        results = {
            "types.py": _empty_result(),
            "model.py": _result_with_imports(("types", False)),
            "service.py": _result_with_imports(("model", False)),
            "main.py": _result_with_imports(("service", False)),
        }
        resolved = {
            ("model.py", "types"): "types.py",
            ("service.py", "model"): "model.py",
            ("main.py", "service"): "service.py",
        }
        graph = _build_test_graph(results, resolved)
        entry_points = {"main.py"}

        r1 = classify_layers(graph=graph, entry_points=entry_points)
        r2 = classify_layers(graph=graph, entry_points=entry_points)

        assert r1.layers == r2.layers
        assert r1.layer_groups == r2.layer_groups


# ---------------------------------------------------------------------------
# classify_layers — ambiguity resolution
# ---------------------------------------------------------------------------


class TestClassifyLayersAmbiguity:
    """Tests for ambiguous cases — spec says bias toward deeper layer."""

    def test_depth_four_without_high_fan_in_biases_features(self) -> None:
        """Depth 4+ without high fanIn should stay features, not integration."""
        results = {
            "a.py": _empty_result(),
            "b.py": _result_with_imports(("a", False)),
            "c.py": _result_with_imports(("b", False)),
            "d.py": _result_with_imports(("c", False)),
            "e.py": _result_with_imports(("d", False)),
        }
        resolved = {
            ("b.py", "a"): "a.py",
            ("c.py", "b"): "b.py",
            ("d.py", "c"): "c.py",
            ("e.py", "d"): "d.py",
        }
        graph = _build_test_graph(results, resolved)
        result = classify_layers(graph=graph, entry_points=set())

        # e.py is depth 4 with fan_in 0 — should be features, not integration
        assert result.layers["e.py"] == Layer.FEATURES


# ---------------------------------------------------------------------------
# classify_layers — realistic scenario
# ---------------------------------------------------------------------------


class TestClassifyLayersRealistic:
    """Integration-style tests with a realistic project layout."""

    def test_small_project(self) -> None:
        """Simulate a small project with all layers represented."""
        results = {
            # Foundation: no deps
            "config.py": _empty_result(),
            "types.py": _empty_result(),
            # Core: depends on foundation
            "model.py": _result_with_imports(
                ("config", False), ("types", False),
            ),
            "db.py": _result_with_imports(("config", False)),
            # Features: depends on core
            "dashboard.py": _result_with_imports(("model", False)),
            "profile.py": _result_with_imports(("model", False)),
            # Integration: high fanIn, depth 4+
            "api.py": _result_with_imports(
                ("dashboard", False), ("profile", False), ("db", False),
            ),
            # More consumers for api to boost fan_in
            "client_a.py": _result_with_imports(("api", False)),
            "client_b.py": _result_with_imports(("api", False)),
            "client_c.py": _result_with_imports(("api", False)),
            # Entry point
            "main.py": _entry_result_with_imports(("api", False)),
        }
        resolved = {
            ("model.py", "config"): "config.py",
            ("model.py", "types"): "types.py",
            ("db.py", "config"): "config.py",
            ("dashboard.py", "model"): "model.py",
            ("profile.py", "model"): "model.py",
            ("api.py", "dashboard"): "dashboard.py",
            ("api.py", "profile"): "profile.py",
            ("api.py", "db"): "db.py",
            ("client_a.py", "api"): "api.py",
            ("client_b.py", "api"): "api.py",
            ("client_c.py", "api"): "api.py",
            ("main.py", "api"): "api.py",
        }
        graph = _build_test_graph(results, resolved)
        result = classify_layers(
            graph=graph,
            entry_points={"main.py"},
        )

        # Foundation
        assert result.layers["config.py"] == Layer.FOUNDATION
        assert result.layers["types.py"] == Layer.FOUNDATION

        # Core
        assert result.layers["model.py"] == Layer.CORE
        assert result.layers["db.py"] == Layer.CORE

        # Features
        assert result.layers["dashboard.py"] == Layer.FEATURES
        assert result.layers["profile.py"] == Layer.FEATURES

        # Entry
        assert result.layers["main.py"] == Layer.ENTRY

        # api.py: depth 3, high fan_in (4: client_a, client_b, client_c, main)
        # This is a composing/integration file
        assert result.layers["api.py"] == Layer.INTEGRATION
