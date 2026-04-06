"""Tests for reading order integration with ReadingConfig (BED-92).

Tests that compute_reading_order respects configuration for:
- Test file handling modes (skip, separate pass, paired, utility)
- Custom pass overrides via glob patterns
- Tie-breaking strategy changes
- Layer threshold customization
"""

from __future__ import annotations

from nlv.config import ReadingConfig, TestFileMode, TieBreaking
from nlv.graph import DependencyGraph, build_graph
from nlv.layers import LayerClassification, classify_layers
from nlv.plugins import ExportKind, ExportRef, ImportRef, ParseResult
from nlv.reading_order import (
    ReadingPass,
    compute_reading_order,
    detect_test_file,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_result() -> ParseResult:
    return ParseResult(imports=(), exports=(), functions=(), entry_point=False)


def _result_with_imports(*sources: tuple[str, bool]) -> ParseResult:
    imports = tuple(
        ImportRef(source=s, specifiers=(), is_relative=rel)
        for s, rel in sources
    )
    return ParseResult(
        imports=imports, exports=(), functions=(), entry_point=False,
    )


def _type_heavy_result() -> ParseResult:
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
    return ParseResult(
        imports=(),
        exports=(
            ExportRef(name="process", kind=ExportKind.FUNCTION, line=1),
            ExportRef(name="validate", kind=ExportKind.FUNCTION, line=10),
        ),
        functions=(),
        entry_point=False,
    )


def _build_graph_and_classification(
    results: dict[str, ParseResult],
    resolved: dict[tuple[str, str], str],
    entry_points: set[str] | None = None,
) -> tuple[DependencyGraph, LayerClassification]:
    graph = build_graph(parse_results=results, resolved_imports=resolved)
    classification = classify_layers(
        graph=graph, entry_points=entry_points or set(),
    )
    return graph, classification


# ---------------------------------------------------------------------------
# Test file skip behavior
# ---------------------------------------------------------------------------


class TestSkipTests:
    """Tests for skip_tests config option."""

    def test_skip_tests_excludes_test_files(self) -> None:
        """When skip_tests=True, test files are excluded from the order."""
        results = {
            "config.py": _empty_result(),
            "test_config.py": _result_with_imports(("config", False)),
        }
        resolved = {("test_config.py", "config"): "config.py"}
        graph, classification = _build_graph_and_classification(
            results, resolved,
        )

        cfg = ReadingConfig(skip_tests=True)
        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
            config=cfg,
        )

        paths = [e.path for e in order]
        assert "config.py" in paths
        assert "test_config.py" not in paths

    def test_skip_tests_false_includes_test_files(self) -> None:
        """When skip_tests=False (default), test files are included."""
        results = {
            "config.py": _empty_result(),
            "test_config.py": _result_with_imports(("config", False)),
        }
        resolved = {("test_config.py", "config"): "config.py"}
        graph, classification = _build_graph_and_classification(
            results, resolved,
        )

        cfg = ReadingConfig(skip_tests=False)
        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
            config=cfg,
        )

        paths = [e.path for e in order]
        assert "test_config.py" in paths


# ---------------------------------------------------------------------------
# Test file separate pass
# ---------------------------------------------------------------------------


class TestTestFileSeparatePass:
    """Tests for test_pass="separate" mode."""

    def test_separate_pass_puts_tests_after_all_passes(self) -> None:
        """In 'separate' mode, all test files come after all non-test files."""
        results = {
            "types.py": _type_heavy_result(),
            "model.py": _result_with_imports(("types", False)),
            "utils/helpers.py": _empty_result(),
            "test_model.py": _result_with_imports(("model", False)),
            "test_types.py": _result_with_imports(("types", False)),
        }
        resolved = {
            ("model.py", "types"): "types.py",
            ("test_model.py", "model"): "model.py",
            ("test_types.py", "types"): "types.py",
        }
        graph, classification = _build_graph_and_classification(
            results, resolved,
        )

        cfg = ReadingConfig(test_pass=TestFileMode.SEPARATE)
        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
            config=cfg,
        )

        paths = [e.path for e in order]
        non_test_paths = [p for p in paths if not detect_test_file(p)]
        test_paths = [p for p in paths if detect_test_file(p)]

        # All non-test files should come before all test files
        if non_test_paths and test_paths:
            last_non_test_idx = max(paths.index(p) for p in non_test_paths)
            first_test_idx = min(paths.index(p) for p in test_paths)
            assert last_non_test_idx < first_test_idx


# ---------------------------------------------------------------------------
# Test file mode: put tests in specific pass
# ---------------------------------------------------------------------------


class TestTestPassMode:
    """Tests for test_pass mode directing tests to a specific pass."""

    def test_test_pass_contracts(self) -> None:
        """test_pass='contracts' puts unpaired tests in contracts pass."""
        results = {
            "config.py": _empty_result(),
            "test_orphan.py": _empty_result(),
        }
        graph, classification = _build_graph_and_classification(
            results, resolved={},
        )

        cfg = ReadingConfig(test_pass=TestFileMode.CONTRACTS)
        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
            config=cfg,
        )

        orphan = next(e for e in order if e.path == "test_orphan.py")
        assert orphan.reading_pass == ReadingPass.CONTRACTS

    def test_test_pass_skip_excludes_all_tests(self) -> None:
        """test_pass='skip' excludes all test files."""
        results = {
            "config.py": _empty_result(),
            "test_config.py": _result_with_imports(("config", False)),
            "conftest.py": _empty_result(),
        }
        resolved = {("test_config.py", "config"): "config.py"}
        graph, classification = _build_graph_and_classification(
            results, resolved,
        )

        cfg = ReadingConfig(test_pass=TestFileMode.SKIP)
        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
            config=cfg,
        )

        paths = [e.path for e in order]
        assert "test_config.py" not in paths
        assert "conftest.py" not in paths
        assert "config.py" in paths


# ---------------------------------------------------------------------------
# Custom pass overrides
# ---------------------------------------------------------------------------


class TestCustomPassOverrides:
    """Tests for custom_pass_overrides with glob patterns."""

    def test_glob_overrides_default_classification(self) -> None:
        """Files matching a glob override get that pass instead of heuristic."""
        results = {
            "src/types/user.py": _function_heavy_result(),
            "src/models/user.py": _empty_result(),
        }
        graph, classification = _build_graph_and_classification(
            results, resolved={},
        )

        cfg = ReadingConfig(
            custom_pass_overrides={"src/types/**": "contracts"},
        )
        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
            config=cfg,
        )

        types_entry = next(
            e for e in order if e.path == "src/types/user.py"
        )
        assert types_entry.reading_pass == ReadingPass.CONTRACTS

    def test_override_utility_to_data_flow(self) -> None:
        """Override a utility-path file to data_flow via glob."""
        results = {"utils/important.py": _empty_result()}
        graph, classification = _build_graph_and_classification(
            results, resolved={},
        )

        cfg = ReadingConfig(
            custom_pass_overrides={"utils/important.py": "data_flow"},
        )
        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
            config=cfg,
        )

        entry = next(e for e in order if e.path == "utils/important.py")
        assert entry.reading_pass == ReadingPass.DATA_FLOW


# ---------------------------------------------------------------------------
# Tie-breaking strategies
# ---------------------------------------------------------------------------


class TestTieBreaking:
    """Tests for configurable tie-breaking strategies."""

    def test_alphabetical_tie_breaking(self) -> None:
        """Default alphabetical tie-breaking: 'a' before 'z'."""
        results = {
            "z_file.py": _empty_result(),
            "a_file.py": _empty_result(),
        }
        graph, classification = _build_graph_and_classification(
            results, resolved={},
        )

        cfg = ReadingConfig(tie_breaking=TieBreaking.ALPHABETICAL)
        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
            config=cfg,
        )

        non_test = [e for e in order if not detect_test_file(e.path)]
        paths = [e.path for e in non_test]
        assert paths.index("a_file.py") < paths.index("z_file.py")

    def test_fan_out_tie_breaking_prefers_more_dependents(self) -> None:
        """fan_out tie-breaking: files with more dependents come first."""
        # popular.py is imported by 3 files; lonely.py by none
        results = {
            "popular.py": _empty_result(),
            "lonely.py": _empty_result(),
            "a.py": _result_with_imports(("popular", False)),
            "b.py": _result_with_imports(("popular", False)),
            "c.py": _result_with_imports(("popular", False)),
        }
        resolved = {
            ("a.py", "popular"): "popular.py",
            ("b.py", "popular"): "popular.py",
            ("c.py", "popular"): "popular.py",
        }
        graph, classification = _build_graph_and_classification(
            results, resolved,
        )

        # Default tie-breaking already uses fan_in; this tests the
        # behavior when configured explicitly
        cfg = ReadingConfig(tie_breaking=TieBreaking.ALPHABETICAL)
        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
            config=cfg,
        )

        # popular.py has higher fan_in (3 files import it) so it should
        # come before lonely.py when they're in the same pass/layer
        non_test = [e for e in order if not detect_test_file(e.path)]
        pass_files = [
            e for e in non_test
            if e.reading_pass == ReadingPass.CONTRACTS
        ]
        if len(pass_files) >= 2:
            popular_idx = next(
                i for i, e in enumerate(pass_files)
                if e.path == "popular.py"
            )
            lonely_idx = next(
                i for i, e in enumerate(pass_files)
                if e.path == "lonely.py"
            )
            assert popular_idx < lonely_idx


# ---------------------------------------------------------------------------
# Backward compatibility — no config
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Tests that compute_reading_order works without a config argument."""

    def test_no_config_uses_defaults(self) -> None:
        """Calling without config= should produce the same result as default config."""
        results = {
            "types.py": _type_heavy_result(),
            "model.py": _result_with_imports(("types", False)),
            "test_model.py": _result_with_imports(("model", False)),
        }
        resolved = {
            ("model.py", "types"): "types.py",
            ("test_model.py", "model"): "model.py",
        }
        graph, classification = _build_graph_and_classification(
            results, resolved,
        )

        # Without config
        order_no_cfg = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        # With default config
        order_default = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
            config=ReadingConfig(),
        )

        paths_no_cfg = [e.path for e in order_no_cfg]
        paths_default = [e.path for e in order_default]
        assert paths_no_cfg == paths_default


# ---------------------------------------------------------------------------
# Enhanced contract surface heuristics
# ---------------------------------------------------------------------------


class TestEnhancedContractHeuristics:
    """Tests for improved contract surface classification."""

    def test_init_file_reexporting_is_contract(self) -> None:
        """__init__.py files that re-export are contract surfaces."""
        results = {
            "pkg/__init__.py": ParseResult(
                imports=(
                    ImportRef(source=".module", specifiers=("Foo",), is_relative=True),
                ),
                exports=(
                    ExportRef(name="Foo", kind=ExportKind.CLASS, line=1),
                ),
                functions=(),
                entry_point=False,
            ),
            "pkg/module.py": ParseResult(
                imports=(),
                exports=(
                    ExportRef(name="Foo", kind=ExportKind.CLASS, line=1),
                ),
                functions=(),
                entry_point=False,
            ),
        }
        resolved = {("pkg/__init__.py", ".module"): "pkg/module.py"}
        graph, classification = _build_graph_and_classification(
            results, resolved,
        )

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        init_entry = next(
            e for e in order if e.path == "pkg/__init__.py"
        )
        assert init_entry.reading_pass == ReadingPass.CONTRACTS

    def test_types_file_by_name_is_contract(self) -> None:
        """Files named types.py are contract surfaces even without exports."""
        results = {"src/types.py": _empty_result()}
        graph, classification = _build_graph_and_classification(
            results, resolved={},
        )

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        entry = next(e for e in order if e.path == "src/types.py")
        assert entry.reading_pass == ReadingPass.CONTRACTS

    def test_constants_file_by_name_is_contract(self) -> None:
        """Files named constants.py are contract surfaces."""
        results = {"constants.py": _empty_result()}
        graph, classification = _build_graph_and_classification(
            results, resolved={},
        )

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        entry = next(e for e in order if e.path == "constants.py")
        assert entry.reading_pass == ReadingPass.CONTRACTS

    def test_schema_file_by_name_is_contract(self) -> None:
        """Files named schema.py are contract surfaces."""
        results = {"schema.py": _empty_result()}
        graph, classification = _build_graph_and_classification(
            results, resolved={},
        )

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        entry = next(e for e in order if e.path == "schema.py")
        assert entry.reading_pass == ReadingPass.CONTRACTS

    def test_interfaces_file_by_name_is_contract(self) -> None:
        """Files named interfaces.py are contract surfaces."""
        results = {"interfaces.py": _empty_result()}
        graph, classification = _build_graph_and_classification(
            results, resolved={},
        )

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        entry = next(e for e in order if e.path == "interfaces.py")
        assert entry.reading_pass == ReadingPass.CONTRACTS

    def test_models_file_by_name_is_contract(self) -> None:
        """Files named models.py are contract surfaces."""
        results = {"models.py": _empty_result()}
        graph, classification = _build_graph_and_classification(
            results, resolved={},
        )

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        entry = next(e for e in order if e.path == "models.py")
        assert entry.reading_pass == ReadingPass.CONTRACTS


# ---------------------------------------------------------------------------
# exclude_from_reading integration
# ---------------------------------------------------------------------------


class TestExcludeFromReadingOrder:
    """Tests that exclude_from_reading filters files from reading order."""

    def test_exclude_init_files(self) -> None:
        """__init__.py files matching the exclude pattern are removed."""
        results = {
            "pkg/__init__.py": _empty_result(),
            "pkg/core.py": _empty_result(),
            "pkg/utils.py": _empty_result(),
        }
        graph, classification = _build_graph_and_classification(
            results, resolved={},
        )

        cfg = ReadingConfig(exclude_from_reading=("**/__init__.py",))
        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
            config=cfg,
        )

        paths = [e.path for e in order]
        assert "pkg/__init__.py" not in paths
        assert "pkg/core.py" in paths
        assert "pkg/utils.py" in paths

    def test_exclude_multiple_patterns(self) -> None:
        """Multiple exclude patterns are all applied."""
        results = {
            "pkg/__init__.py": _empty_result(),
            "conftest.py": _empty_result(),
            "src/app.py": _empty_result(),
        }
        graph, classification = _build_graph_and_classification(
            results, resolved={},
        )

        cfg = ReadingConfig(
            exclude_from_reading=("**/__init__.py", "conftest.py"),
        )
        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
            config=cfg,
        )

        paths = [e.path for e in order]
        assert "pkg/__init__.py" not in paths
        assert "conftest.py" not in paths
        assert "src/app.py" in paths

    def test_empty_exclude_keeps_all_non_trivial_files(self) -> None:
        """Empty exclude_from_reading preserves all non-trivial files."""
        results = {
            "pkg/utils.py": _empty_result(),
            "pkg/core.py": _empty_result(),
        }
        graph, classification = _build_graph_and_classification(
            results, resolved={},
        )

        cfg = ReadingConfig(exclude_from_reading=())
        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
            config=cfg,
        )

        paths = [e.path for e in order]
        assert len(paths) == 2

    def test_exclude_updates_indices(self) -> None:
        """Indices are sequential after exclusion (no gaps)."""
        results = {
            "a/__init__.py": _empty_result(),
            "a/first.py": _empty_result(),
            "a/second.py": _empty_result(),
        }
        graph, classification = _build_graph_and_classification(
            results, resolved={},
        )

        cfg = ReadingConfig(exclude_from_reading=("**/__init__.py",))
        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
            config=cfg,
        )

        indices = [e.index for e in order]
        assert indices == list(range(len(order)))


# ---------------------------------------------------------------------------
# Trivial __init__.py auto-exclusion
# ---------------------------------------------------------------------------


class TestTrivialInitAutoExclusion:
    """Trivial __init__.py files are auto-excluded from reading order."""

    def test_empty_init_excluded(self) -> None:
        """Empty __init__.py with no functions is auto-excluded."""
        results = {
            "pkg/__init__.py": _empty_result(),
            "pkg/core.py": _function_heavy_result(),
        }
        graph, classification = _build_graph_and_classification(
            results, resolved={},
        )

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        paths = [e.path for e in order]
        assert "pkg/__init__.py" not in paths
        assert "pkg/core.py" in paths

    def test_init_with_functions_kept(self) -> None:
        """__init__.py with real functions is kept in reading order."""
        from nlv.plugins import FunctionRef

        result_with_fn = ParseResult(
            imports=(),
            exports=(),
            functions=(
                FunctionRef(name="init_app", line=1, end_line=10, calls=()),
            ),
            entry_point=False,
        )
        results = {
            "pkg/__init__.py": result_with_fn,
            "pkg/core.py": _empty_result(),
        }
        graph, classification = _build_graph_and_classification(
            results, resolved={},
        )

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        paths = [e.path for e in order]
        assert "pkg/__init__.py" in paths

    def test_non_init_files_unaffected(self) -> None:
        """Regular .py files are never auto-excluded."""
        results = {
            "pkg/empty.py": _empty_result(),
            "pkg/core.py": _empty_result(),
        }
        graph, classification = _build_graph_and_classification(
            results, resolved={},
        )

        order = compute_reading_order(
            graph=graph,
            classification=classification,
            parse_results=results,
        )

        paths = [e.path for e in order]
        assert "pkg/empty.py" in paths
