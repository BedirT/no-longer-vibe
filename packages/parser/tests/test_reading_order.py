"""Tests for three-pass reading order computation (BED-66).

Tests the compute_reading_order() function that assigns files to three
sequential passes (contract surfaces, data flow, utility), each internally
topologically sorted. Also tests test file detection and co-located pairing.
"""

from __future__ import annotations

import pytest

from nlv.graph import DependencyGraph, build_graph
from nlv.layers import Layer, LayerClassification, classify_layers
from nlv.plugins import ExportKind, ExportRef, ImportRef, ParseResult
from nlv.reading_order import (
    ReadingOrderEntry,
    ReadingPass,
    compute_reading_order,
    detect_test_file,
    find_paired_test_files,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_result() -> ParseResult:
    """Return an empty ParseResult."""
    return ParseResult(imports=(), exports=(), functions=(), entry_point=False)


def _result_with_imports(*sources: tuple[str, bool]) -> ParseResult:
    """Return a ParseResult with the given imports."""
    imports = tuple(
        ImportRef(source=s, specifiers=(), is_relative=rel)
        for s, rel in sources
    )
    return ParseResult(
        imports=imports, exports=(), functions=(), entry_point=False,
    )


def _type_heavy_result() -> ParseResult:
    """Return a ParseResult with mostly type/class exports (contract surface)."""
    return ParseResult(
        imports=(),
        exports=(
            ExportRef(name="UserType", kind=ExportKind.TYPE, line=1),
            ExportRef(name="Config", kind=ExportKind.CLASS, line=5),
            ExportRef(name="AppSettings", kind=ExportKind.TYPE, line=10),
        ),
        functions=(),
        entry_point=False,
    )


def _function_heavy_result() -> ParseResult:
    """Return a ParseResult with mostly function exports."""
    return ParseResult(
        imports=(),
        exports=(
            ExportRef(name="process_data", kind=ExportKind.FUNCTION, line=1),
            ExportRef(name="validate", kind=ExportKind.FUNCTION, line=10),
            ExportRef(name="transform", kind=ExportKind.FUNCTION, line=20),
        ),
        functions=(),
        entry_point=False,
    )


def _build_test_graph(
    results: dict[str, ParseResult],
    resolved: dict[tuple[str, str], str],
) -> DependencyGraph:
    """Build a DependencyGraph from test data."""
    return build_graph(parse_results=results, resolved_imports=resolved)


def _build_classification(
    graph: DependencyGraph,
    entry_points: set[str] | None = None,
) -> LayerClassification:
    """Build a LayerClassification from a graph."""
    return classify_layers(
        graph=graph, entry_points=entry_points or set(),
    )


# ---------------------------------------------------------------------------
# ReadingPass enum tests
# ---------------------------------------------------------------------------


class TestReadingPassEnum:
    """Tests for the ReadingPass enum values."""

    def test_all_three_passes_exist(self) -> None:
        assert ReadingPass.CONTRACTS.value == "contracts"
        assert ReadingPass.DATA_FLOW.value == "data_flow"
        assert ReadingPass.UTILITY.value == "utility"

    def test_pass_count(self) -> None:
        assert len(ReadingPass) == 3


# ---------------------------------------------------------------------------
# ReadingOrderEntry dataclass tests
# ---------------------------------------------------------------------------


class TestReadingOrderEntry:
    """Tests for the ReadingOrderEntry dataclass."""

    def test_create_entry(self) -> None:
        entry = ReadingOrderEntry(
            index=0,
            path="src/types.py",
            layer=Layer.FOUNDATION,
            reading_pass=ReadingPass.CONTRACTS,
            reason="Type definitions with high fanIn.",
            complexity="low",
            line_count=45,
            imports=(),
            imported_by=("src/model.py",),
            exports=("UserType", "Config"),
            paired_with=None,
        )
        assert entry.index == 0
        assert entry.path == "src/types.py"
        assert entry.reading_pass == ReadingPass.CONTRACTS
        assert entry.paired_with is None

    def test_create_entry_with_paired_test(self) -> None:
        entry = ReadingOrderEntry(
            index=1,
            path="tests/test_types.py",
            layer=Layer.FOUNDATION,
            reading_pass=ReadingPass.CONTRACTS,
            reason="Test file for src/types.py.",
            complexity="low",
            line_count=80,
            imports=(),
            imported_by=(),
            exports=(),
            paired_with="src/types.py",
        )
        assert entry.paired_with == "src/types.py"

    def test_frozen_dataclass(self) -> None:
        entry = ReadingOrderEntry(
            index=0,
            path="a.py",
            layer=Layer.FOUNDATION,
            reading_pass=ReadingPass.CONTRACTS,
            reason="Test",
            complexity="low",
            line_count=10,
            imports=(),
            imported_by=(),
            exports=(),
            paired_with=None,
        )
        with pytest.raises(AttributeError):
            entry.index = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# detect_test_file — test file identification
# ---------------------------------------------------------------------------


class TestDetectTestFile:
    """Tests for test file detection by naming convention."""

    def test_prefix_test_file(self) -> None:
        assert detect_test_file("test_config.py") is True

    def test_suffix_test_file(self) -> None:
        assert detect_test_file("config_test.py") is True

    def test_tests_directory(self) -> None:
        assert detect_test_file("tests/test_config.py") is True

    def test_nested_tests_directory(self) -> None:
        assert detect_test_file("src/tests/test_config.py") is True

    def test_conftest(self) -> None:
        assert detect_test_file("conftest.py") is True

    def test_nested_conftest(self) -> None:
        assert detect_test_file("tests/conftest.py") is True

    def test_regular_file(self) -> None:
        assert detect_test_file("config.py") is False

    def test_regular_file_in_src(self) -> None:
        assert detect_test_file("src/config.py") is False

    def test_file_with_test_in_middle(self) -> None:
        """Files like 'testing_utils.py' are not test files by convention."""
        assert detect_test_file("testing_utils.py") is False

    def test_file_named_test(self) -> None:
        """A file literally named 'test.py' is a test file."""
        assert detect_test_file("test.py") is True


# ---------------------------------------------------------------------------
# find_paired_test_files — test-to-implementation pairing
# ---------------------------------------------------------------------------


class TestFindPairedTestFiles:
    """Tests for pairing test files with their implementation files."""

    def test_prefix_pattern_match(self) -> None:
        """test_config.py pairs with config.py."""
        all_files = {"config.py", "test_config.py"}
        pairs = find_paired_test_files(all_files)
        assert pairs["test_config.py"] == "config.py"

    def test_suffix_pattern_match(self) -> None:
        """config_test.py pairs with config.py."""
        all_files = {"config.py", "config_test.py"}
        pairs = find_paired_test_files(all_files)
        assert pairs["config_test.py"] == "config.py"

    def test_tests_directory_match(self) -> None:
        """tests/test_config.py pairs with config.py."""
        all_files = {"config.py", "tests/test_config.py"}
        pairs = find_paired_test_files(all_files)
        assert pairs["tests/test_config.py"] == "config.py"

    def test_tests_dir_matches_src_dir(self) -> None:
        """tests/test_model.py pairs with src/model.py."""
        all_files = {"src/model.py", "tests/test_model.py"}
        pairs = find_paired_test_files(all_files)
        assert pairs["tests/test_model.py"] == "src/model.py"

    def test_no_match_returns_empty(self) -> None:
        """Test file without a matching implementation is not paired."""
        all_files = {"test_orphan.py", "config.py"}
        pairs = find_paired_test_files(all_files)
        assert "test_orphan.py" not in pairs

    def test_conftest_not_paired(self) -> None:
        """conftest.py is a standalone test utility, not paired."""
        all_files = {"config.py", "conftest.py"}
        pairs = find_paired_test_files(all_files)
        assert "conftest.py" not in pairs

    def test_non_test_files_not_in_result(self) -> None:
        """Regular files should not appear as keys in the result."""
        all_files = {"config.py", "test_config.py"}
        pairs = find_paired_test_files(all_files)
        assert "config.py" not in pairs


# ---------------------------------------------------------------------------
# compute_reading_order — pass assignment
# ---------------------------------------------------------------------------


class TestReadingOrderPassAssignment:
    """Tests for correct assignment of files to reading passes."""

    def test_type_heavy_file_in_contracts_pass(self) -> None:
        """Files predominantly exporting types go in Pass 1 (contracts)."""
        results = {"types.py": _type_heavy_result()}
        graph = _build_test_graph(results, resolved={})
        classification = _build_classification(graph)

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        types_entry = next(e for e in order if e.path == "types.py")
        assert types_entry.reading_pass == ReadingPass.CONTRACTS

    def test_high_fan_in_low_complexity_in_contracts(self) -> None:
        """Files with high fanIn but low complexity go in contracts pass."""
        results = {
            "types.py": _type_heavy_result(),
            "a.py": _result_with_imports(("types", False)),
            "b.py": _result_with_imports(("types", False)),
            "c.py": _result_with_imports(("types", False)),
            "d.py": _result_with_imports(("types", False)),
        }
        resolved = {
            ("a.py", "types"): "types.py",
            ("b.py", "types"): "types.py",
            ("c.py", "types"): "types.py",
            ("d.py", "types"): "types.py",
        }
        graph = _build_test_graph(results, resolved)
        classification = _build_classification(graph)

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        types_entry = next(e for e in order if e.path == "types.py")
        assert types_entry.reading_pass == ReadingPass.CONTRACTS

    def test_utility_path_file_in_utility_pass(self) -> None:
        """Files in utils/ directories go in Pass 3 (utility)."""
        results = {"utils/helpers.py": _function_heavy_result()}
        graph = _build_test_graph(results, resolved={})
        classification = _build_classification(graph)

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        helper_entry = next(e for e in order if e.path == "utils/helpers.py")
        assert helper_entry.reading_pass == ReadingPass.UTILITY

    def test_helpers_dir_in_utility_pass(self) -> None:
        """Files in helpers/ directories go in Pass 3."""
        results = {"helpers/format.py": _empty_result()}
        graph = _build_test_graph(results, resolved={})
        classification = _build_classification(graph)

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        entry = next(e for e in order if e.path == "helpers/format.py")
        assert entry.reading_pass == ReadingPass.UTILITY

    def test_lib_dir_in_utility_pass(self) -> None:
        """Files in lib/ directories go in Pass 3."""
        results = {"lib/common.py": _empty_result()}
        graph = _build_test_graph(results, resolved={})
        classification = _build_classification(graph)

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        entry = next(e for e in order if e.path == "lib/common.py")
        assert entry.reading_pass == ReadingPass.UTILITY

    def test_data_flow_file_on_critical_path(self) -> None:
        """Files on the critical path go in Pass 2 (data flow)."""
        # Build: types -> model -> service -> api -> main
        # model/service/api are on the critical path between entry and foundation
        results = {
            "types.py": _type_heavy_result(),
            "model.py": _result_with_imports(("types", False)),
            "service.py": _result_with_imports(("model", False)),
            "api.py": _result_with_imports(("service", False)),
            "main.py": _result_with_imports(("api", False)),
        }
        resolved = {
            ("model.py", "types"): "types.py",
            ("service.py", "model"): "model.py",
            ("api.py", "service"): "service.py",
            ("main.py", "api"): "api.py",
        }
        graph = _build_test_graph(results, resolved)
        classification = _build_classification(graph, entry_points={"main.py"})

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        # types.py has high type exports -> contracts
        types_entry = next(e for e in order if e.path == "types.py")
        assert types_entry.reading_pass == ReadingPass.CONTRACTS

        # main.py is an entry point, on the critical path -> data_flow
        main_entry = next(e for e in order if e.path == "main.py")
        assert main_entry.reading_pass == ReadingPass.DATA_FLOW


# ---------------------------------------------------------------------------
# compute_reading_order — topological sort within passes
# ---------------------------------------------------------------------------


class TestReadingOrderTopologicalSort:
    """Tests that within each pass, files respect dependency order."""

    def test_dependencies_come_before_dependents_within_pass(self) -> None:
        """Within a pass, if A depends on B, B appears first."""
        results = {
            "types.py": _type_heavy_result(),
            "config.py": _type_heavy_result(),
            "model.py": _result_with_imports(
                ("types", False), ("config", False),
            ),
        }
        resolved = {
            ("model.py", "types"): "types.py",
            ("model.py", "config"): "config.py",
        }
        graph = _build_test_graph(results, resolved)
        classification = _build_classification(graph)

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        paths = [e.path for e in order if not detect_test_file(e.path)]
        # types.py and config.py should come before model.py
        if "model.py" in paths:
            model_idx = paths.index("model.py")
            for dep in ("types.py", "config.py"):
                if dep in paths:
                    assert paths.index(dep) < model_idx

    def test_tie_breaking_by_layer_then_fan_in(self) -> None:
        """When no dependency order exists, break ties by layer, fan_in, alpha."""
        results = {
            "z_config.py": _empty_result(),
            "a_types.py": _empty_result(),
        }
        graph = _build_test_graph(results, resolved={})
        classification = _build_classification(graph)

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        non_test = [e for e in order if not detect_test_file(e.path)]
        paths = [e.path for e in non_test]
        # Same layer, same fan_in -> alphabetical
        assert paths.index("a_types.py") < paths.index("z_config.py")

    def test_foundation_before_core_in_same_pass(self) -> None:
        """Foundation files should come before core files in the same pass."""
        results = {
            "types.py": _type_heavy_result(),
            "model.py": _result_with_imports(("types", False)),
        }
        resolved = {("model.py", "types"): "types.py"}
        graph = _build_test_graph(results, resolved)
        classification = _build_classification(graph)

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        non_test = [e.path for e in order if not detect_test_file(e.path)]
        if "types.py" in non_test and "model.py" in non_test:
            assert non_test.index("types.py") < non_test.index("model.py")


# ---------------------------------------------------------------------------
# compute_reading_order — test file co-location
# ---------------------------------------------------------------------------


class TestReadingOrderTestCoLocation:
    """Tests that test files are placed immediately after their implementation."""

    def test_test_file_follows_implementation(self) -> None:
        """test_config.py should appear immediately after config.py."""
        results = {
            "config.py": _empty_result(),
            "test_config.py": _result_with_imports(("config", False)),
        }
        resolved = {("test_config.py", "config"): "config.py"}
        graph = _build_test_graph(results, resolved)
        classification = _build_classification(graph)

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        paths = [e.path for e in order]
        config_idx = paths.index("config.py")
        test_idx = paths.index("test_config.py")
        assert test_idx == config_idx + 1

    def test_test_file_inherits_pass_from_implementation(self) -> None:
        """Test files should be in the same pass as their implementation."""
        results = {
            "types.py": _type_heavy_result(),
            "test_types.py": _result_with_imports(("types", False)),
        }
        resolved = {("test_types.py", "types"): "types.py"}
        graph = _build_test_graph(results, resolved)
        classification = _build_classification(graph)

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        types_entry = next(e for e in order if e.path == "types.py")
        test_entry = next(e for e in order if e.path == "test_types.py")
        assert test_entry.reading_pass == types_entry.reading_pass

    def test_test_file_has_paired_with_field(self) -> None:
        """Test files should have paired_with pointing to their impl file."""
        results = {
            "config.py": _empty_result(),
            "test_config.py": _result_with_imports(("config", False)),
        }
        resolved = {("test_config.py", "config"): "config.py"}
        graph = _build_test_graph(results, resolved)
        classification = _build_classification(graph)

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        test_entry = next(e for e in order if e.path == "test_config.py")
        assert test_entry.paired_with == "config.py"

    def test_conftest_in_utility_pass(self) -> None:
        """conftest.py is a standalone test utility -> Pass 3."""
        results = {
            "conftest.py": _empty_result(),
            "config.py": _empty_result(),
        }
        graph = _build_test_graph(results, resolved={})
        classification = _build_classification(graph)

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        conftest_entry = next(e for e in order if e.path == "conftest.py")
        assert conftest_entry.reading_pass == ReadingPass.UTILITY

    def test_orphan_test_in_utility_pass(self) -> None:
        """Test files with no matching implementation -> Pass 3 (utility)."""
        results = {
            "test_orphan.py": _empty_result(),
            "config.py": _empty_result(),
        }
        graph = _build_test_graph(results, resolved={})
        classification = _build_classification(graph)

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        orphan_entry = next(e for e in order if e.path == "test_orphan.py")
        assert orphan_entry.reading_pass == ReadingPass.UTILITY

    def test_multiple_test_files_for_one_implementation(self) -> None:
        """Multiple test files for one impl file all follow it."""
        results = {
            "model.py": _empty_result(),
            "test_model.py": _result_with_imports(("model", False)),
            "model_test.py": _result_with_imports(("model", False)),
        }
        resolved = {
            ("test_model.py", "model"): "model.py",
            ("model_test.py", "model"): "model.py",
        }
        graph = _build_test_graph(results, resolved)
        classification = _build_classification(graph)

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        paths = [e.path for e in order]
        model_idx = paths.index("model.py")
        # Both test files should follow immediately
        test_paths = [p for p in paths if detect_test_file(p)]
        for tp in test_paths:
            tidx = paths.index(tp)
            # Test files should be right after model.py (model_idx + 1 or + 2)
            assert tidx > model_idx
            assert tidx <= model_idx + len(test_paths)


# ---------------------------------------------------------------------------
# compute_reading_order — indexing
# ---------------------------------------------------------------------------


class TestReadingOrderIndexing:
    """Tests that indices are sequential and start from 0."""

    def test_indices_sequential(self) -> None:
        results = {
            "a.py": _empty_result(),
            "b.py": _result_with_imports(("a", False)),
            "c.py": _result_with_imports(("b", False)),
        }
        resolved = {
            ("b.py", "a"): "a.py",
            ("c.py", "b"): "b.py",
        }
        graph = _build_test_graph(results, resolved)
        classification = _build_classification(graph)

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        indices = [e.index for e in order]
        assert indices == list(range(len(order)))


# ---------------------------------------------------------------------------
# compute_reading_order — pass ordering
# ---------------------------------------------------------------------------


class TestReadingOrderPassOrdering:
    """Tests that passes are sequenced: contracts -> data_flow -> utility."""

    def test_contracts_before_data_flow(self) -> None:
        """All contract files should come before data flow files."""
        results = {
            "types.py": _type_heavy_result(),
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
        classification = _build_classification(graph, entry_points={"main.py"})

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        non_test = [e for e in order if not detect_test_file(e.path)]
        last_contract_idx = -1
        first_data_flow_idx = len(non_test)
        for i, entry in enumerate(non_test):
            if entry.reading_pass == ReadingPass.CONTRACTS:
                last_contract_idx = max(last_contract_idx, i)
            if entry.reading_pass == ReadingPass.DATA_FLOW:
                first_data_flow_idx = min(first_data_flow_idx, i)

        if last_contract_idx >= 0 and first_data_flow_idx < len(non_test):
            assert last_contract_idx < first_data_flow_idx

    def test_data_flow_before_utility(self) -> None:
        """All data flow files should come before utility files."""
        results = {
            "types.py": _type_heavy_result(),
            "model.py": _result_with_imports(("types", False)),
            "main.py": _result_with_imports(("model", False)),
            "utils/helpers.py": _empty_result(),
        }
        resolved = {
            ("model.py", "types"): "types.py",
            ("main.py", "model"): "model.py",
        }
        graph = _build_test_graph(results, resolved)
        classification = _build_classification(graph, entry_points={"main.py"})

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        non_test = [e for e in order if not detect_test_file(e.path)]
        last_data_flow_idx = -1
        first_utility_idx = len(non_test)
        for i, entry in enumerate(non_test):
            if entry.reading_pass == ReadingPass.DATA_FLOW:
                last_data_flow_idx = max(last_data_flow_idx, i)
            if entry.reading_pass == ReadingPass.UTILITY:
                first_utility_idx = min(first_utility_idx, i)

        if last_data_flow_idx >= 0 and first_utility_idx < len(non_test):
            assert last_data_flow_idx < first_utility_idx


# ---------------------------------------------------------------------------
# compute_reading_order — determinism
# ---------------------------------------------------------------------------


class TestReadingOrderDeterminism:
    """Tests that compute_reading_order is deterministic."""

    def test_same_input_same_output(self) -> None:
        """Running compute_reading_order twice gives identical results."""
        results = {
            "types.py": _type_heavy_result(),
            "config.py": _empty_result(),
            "model.py": _result_with_imports(
                ("types", False), ("config", False),
            ),
            "service.py": _result_with_imports(("model", False)),
            "utils/format.py": _empty_result(),
            "main.py": _result_with_imports(("service", False)),
            "test_model.py": _result_with_imports(("model", False)),
        }
        resolved = {
            ("model.py", "types"): "types.py",
            ("model.py", "config"): "config.py",
            ("service.py", "model"): "model.py",
            ("main.py", "service"): "service.py",
            ("test_model.py", "model"): "model.py",
        }
        graph = _build_test_graph(results, resolved)
        classification = _build_classification(graph, entry_points={"main.py"})

        order1 = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )
        order2 = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        assert len(order1) == len(order2)
        for e1, e2 in zip(order1, order2):
            assert e1.index == e2.index
            assert e1.path == e2.path
            assert e1.reading_pass == e2.reading_pass
            assert e1.layer == e2.layer


# ---------------------------------------------------------------------------
# compute_reading_order — empty and edge cases
# ---------------------------------------------------------------------------


class TestReadingOrderEdgeCases:
    """Tests for edge cases in reading order computation."""

    def test_empty_input(self) -> None:
        """Empty graph produces empty reading order."""
        graph = _build_test_graph(results={}, resolved={})
        classification = _build_classification(graph)

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results={},
        )

        assert order == ()

    def test_single_file(self) -> None:
        """Single file gets index 0."""
        results = {"config.py": _empty_result()}
        graph = _build_test_graph(results, resolved={})
        classification = _build_classification(graph)

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        assert len(order) == 1
        assert order[0].index == 0
        assert order[0].path == "config.py"

    def test_all_files_accounted_for(self) -> None:
        """Every file in the graph appears exactly once in the order."""
        results = {
            "types.py": _type_heavy_result(),
            "model.py": _result_with_imports(("types", False)),
            "utils/helpers.py": _empty_result(),
            "main.py": _result_with_imports(("model", False)),
            "test_model.py": _result_with_imports(("model", False)),
        }
        resolved = {
            ("model.py", "types"): "types.py",
            ("main.py", "model"): "model.py",
            ("test_model.py", "model"): "model.py",
        }
        graph = _build_test_graph(results, resolved)
        classification = _build_classification(graph, entry_points={"main.py"})

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        order_paths = {e.path for e in order}
        assert order_paths == set(results.keys())

    def test_cycle_members_included(self) -> None:
        """Files in cycles should still appear in the reading order."""
        results = {
            "a.py": _result_with_imports(("b", False)),
            "b.py": _result_with_imports(("a", False)),
        }
        resolved = {
            ("a.py", "b"): "b.py",
            ("b.py", "a"): "a.py",
        }
        graph = _build_test_graph(results, resolved)
        classification = _build_classification(graph)

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        order_paths = {e.path for e in order}
        assert "a.py" in order_paths
        assert "b.py" in order_paths


# ---------------------------------------------------------------------------
# compute_reading_order — reason field
# ---------------------------------------------------------------------------


class TestReadingOrderReason:
    """Tests that the reason field is populated meaningfully."""

    def test_reason_is_non_empty_string(self) -> None:
        results = {"config.py": _empty_result()}
        graph = _build_test_graph(results, resolved={})
        classification = _build_classification(graph)

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        assert len(order[0].reason) > 0
        assert isinstance(order[0].reason, str)

    def test_test_file_reason_mentions_implementation(self) -> None:
        """Test file reason should mention the paired implementation file."""
        results = {
            "config.py": _empty_result(),
            "test_config.py": _result_with_imports(("config", False)),
        }
        resolved = {("test_config.py", "config"): "config.py"}
        graph = _build_test_graph(results, resolved)
        classification = _build_classification(graph)

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        test_entry = next(e for e in order if e.path == "test_config.py")
        assert "config.py" in test_entry.reason


# ---------------------------------------------------------------------------
# compute_reading_order — realistic scenario
# ---------------------------------------------------------------------------


class TestReadingOrderRealistic:
    """Integration test with a realistic project layout."""

    def test_small_project(self) -> None:
        """Simulate a small project with all three passes represented."""
        results = {
            # Contract surfaces: type-heavy foundation files
            "types.py": _type_heavy_result(),
            "config.py": _type_heavy_result(),
            # Data flow: core through entry
            "model.py": _result_with_imports(
                ("types", False), ("config", False),
            ),
            "service.py": _result_with_imports(("model", False)),
            "main.py": _result_with_imports(("service", False)),
            # Utility
            "utils/format.py": _empty_result(),
            "helpers/validate.py": _empty_result(),
            # Test files
            "test_model.py": _result_with_imports(("model", False)),
            "tests/test_service.py": _result_with_imports(
                ("service", False),
            ),
            "conftest.py": _empty_result(),
        }
        resolved = {
            ("model.py", "types"): "types.py",
            ("model.py", "config"): "config.py",
            ("service.py", "model"): "model.py",
            ("main.py", "service"): "service.py",
            ("test_model.py", "model"): "model.py",
            ("tests/test_service.py", "service"): "service.py",
        }
        graph = _build_test_graph(results, resolved)
        classification = _build_classification(graph, entry_points={"main.py"})

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        # All files present
        assert len(order) == len(results)
        order_paths = {e.path for e in order}
        assert order_paths == set(results.keys())

        # Indices are sequential
        indices = [e.index for e in order]
        assert indices == list(range(len(order)))

        # Contract files come first (types.py, config.py)
        contract_entries = [
            e for e in order
            if e.reading_pass == ReadingPass.CONTRACTS
            and not detect_test_file(e.path)
        ]
        assert any(e.path == "types.py" for e in contract_entries)

        # Utility files come last (utils/format.py, helpers/validate.py)
        utility_non_test = [
            e for e in order
            if e.reading_pass == ReadingPass.UTILITY
            and not detect_test_file(e.path)
        ]
        utility_non_test_paths = {e.path for e in utility_non_test}
        assert "utils/format.py" in utility_non_test_paths
        assert "helpers/validate.py" in utility_non_test_paths

        # conftest.py is a test utility -> utility pass (it IS a test file)
        conftest_entry = next(e for e in order if e.path == "conftest.py")
        assert conftest_entry.reading_pass == ReadingPass.UTILITY

        # test_model.py follows model.py
        paths = [e.path for e in order]
        if "model.py" in paths and "test_model.py" in paths:
            assert paths.index("test_model.py") == paths.index("model.py") + 1
