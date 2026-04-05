"""Three-pass reading order computation (BED-66, BED-92).

Computes a reading order for source files arranged into three sequential
passes based on Dr. Park's architect-verifying-implementation research:

- **Pass 1 (contracts)**: Interfaces, type definitions, public APIs,
  module boundaries. Pattern-matching against design intent.
- **Pass 2 (data_flow)**: Primary execution flows end-to-end. Files on
  the critical path between entry points and data stores.
- **Pass 3 (utility)**: Helper functions, error handlers, fallback logic.
  Where the AI made the most autonomous decisions.

Within each pass, files are topologically sorted so you never read a file
before its dependencies. Ties are broken by layer (foundation first),
then fanIn (most-imported first), then alphabetical.

Test files are co-located with their implementation files: after scheduling
an implementation file, its paired test files are inserted immediately
after it. Standalone test utilities go in Pass 3.

BED-92 additions:
- Accepts an optional ``ReadingConfig`` to customize behavior.
- Enhanced contract surface heuristics: name-based detection, __init__.py
  re-export detection.
- Configurable test file handling: skip, separate pass, or place in a
  specific pass.
- Custom per-file/per-glob pass overrides.
"""

from __future__ import annotations

import enum
import logging
import os
from dataclasses import dataclass

from nlv.config import (
    ReadingConfig,
    TestFileMode,
    match_custom_pass_override,
)
from nlv.graph import DependencyGraph
from nlv.layers import Layer, LayerClassification
from nlv.plugins import ExportKind, ParseResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Directories whose files are classified as utility (Pass 3).
_UTILITY_DIRS: frozenset[str] = frozenset({
    "utils",
    "helpers",
    "lib",
})

# Export kinds that count as "contract surface" (types / interfaces).
_CONTRACT_EXPORT_KINDS: frozenset[ExportKind] = frozenset({
    ExportKind.TYPE,
    ExportKind.CLASS,
})

# Minimum ratio of contract-kind exports to total exports for a file
# to qualify as a contract surface.
_CONTRACT_EXPORT_RATIO: float = 0.5

# Minimum fanIn to qualify as a contract surface when the file has
# low export information.
_CONTRACT_FAN_IN_THRESHOLD: int = 3

# File name stems that are considered contract surfaces by convention,
# regardless of their export composition.
_CONTRACT_NAME_STEMS: frozenset[str] = frozenset({
    "types",
    "interfaces",
    "models",
    "schema",
    "constants",
})

# Layer ordering for tie-breaking (lower value = earlier in reading order).
_LAYER_ORDER: dict[Layer, int] = {
    Layer.FOUNDATION: 0,
    Layer.CORE: 1,
    Layer.FEATURES: 2,
    Layer.INTEGRATION: 3,
    Layer.ENTRY: 4,
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class ReadingPass(enum.Enum):
    """Which of the three reading passes a file belongs to."""

    CONTRACTS = "contracts"
    DATA_FLOW = "data_flow"
    UTILITY = "utility"


@dataclass(frozen=True)
class ReadingOrderEntry:
    """A single entry in the reading order.

    Attributes:
        index: Zero-based sequential position.
        path: Relative file path (forward slashes).
        layer: Architectural layer from LayerClassification.
        reading_pass: Which of the three passes this file belongs to.
        reason: Human-readable reason for this position.
        complexity: Complexity level string ("low", "medium", "high").
        line_count: Number of code lines.
        imports: Sorted tuple of imported file paths.
        imported_by: Sorted tuple of files that import this one.
        exports: Tuple of exported symbol names.
        paired_with: If a test file, the implementation file it tests.
    """

    index: int
    path: str
    layer: Layer
    reading_pass: ReadingPass
    reason: str
    complexity: str
    line_count: int
    imports: tuple[str, ...]
    imported_by: tuple[str, ...]
    exports: tuple[str, ...]
    paired_with: str | None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_reading_order(
    *,
    graph: DependencyGraph,
    classification: LayerClassification,
    parse_results: dict[str, ParseResult],
    config: ReadingConfig | None = None,
) -> tuple[ReadingOrderEntry, ...]:
    """Compute the three-pass reading order for all files.

    Args:
        graph: The dependency graph.
        classification: Layer classification for every file.
        parse_results: Raw parse results for export/import data.
        config: Optional reading configuration. Uses defaults if None.

    Returns:
        A tuple of ReadingOrderEntry in reading order.
    """
    if config is None:
        config = ReadingConfig()

    if not graph.nodes:
        return ()

    all_files = set(graph.nodes)
    test_pairs = find_paired_test_files(all_files)

    # Handle skip_tests / test_pass=skip: exclude test files entirely
    should_skip_tests = config.skip_tests or config.test_pass == TestFileMode.SKIP

    # Classify each non-test file into a pass
    pass_assignments = _assign_passes(
        graph=graph,
        classification=classification,
        parse_results=parse_results,
        test_pairs=test_pairs,
        config=config,
    )

    # Sort files within each pass
    sorted_order = _sort_within_passes(
        pass_assignments=pass_assignments,
        graph=graph,
        classification=classification,
    )

    final_order, pass_assignments = _apply_test_strategy(
        config=config,
        should_skip_tests=should_skip_tests,
        sorted_order=sorted_order,
        pass_assignments=pass_assignments,
        test_pairs=test_pairs,
        graph=graph,
        classification=classification,
    )

    return _build_entries(
        ordered_paths=final_order,
        graph=graph,
        classification=classification,
        parse_results=parse_results,
        pass_assignments=pass_assignments,
        test_pairs=test_pairs,
    )


def _apply_test_strategy(
    *,
    config: ReadingConfig,
    should_skip_tests: bool,
    sorted_order: list[str],
    pass_assignments: dict[str, ReadingPass],
    test_pairs: dict[str, str],
    graph: DependencyGraph,
    classification: LayerClassification,
) -> tuple[list[str], dict[str, ReadingPass]]:
    """Apply the configured test file strategy to the sorted order."""
    if should_skip_tests:
        filtered = [p for p in sorted_order if not detect_test_file(p)]
        assignments = {
            p: rp for p, rp in pass_assignments.items()
            if not detect_test_file(p)
        }
        return filtered, assignments

    if config.test_pass == TestFileMode.SEPARATE:
        return _separate_test_files(
            sorted_order=sorted_order,
            pass_assignments=pass_assignments,
            graph=graph,
            classification=classification,
        ), pass_assignments

    return _interleave_test_files(
        sorted_order=sorted_order,
        test_pairs=test_pairs,
        pass_assignments=pass_assignments,
        graph=graph,
        classification=classification,
    ), pass_assignments


# ---------------------------------------------------------------------------
# Test file detection
# ---------------------------------------------------------------------------


def detect_test_file(path: str) -> bool:
    """Determine if a file path is a test file by naming convention.

    Matches:
    - ``test_*.py`` prefix
    - ``*_test.py`` suffix
    - ``test.py`` exact name
    - ``conftest.py`` (pytest fixture files)
    - Files in a ``tests/`` directory with test prefix

    Args:
        path: Relative file path.

    Returns:
        True if the file is a test file.
    """
    basename = os.path.basename(path)
    stem = os.path.splitext(basename)[0]

    if basename == "conftest.py":
        return True
    if stem == "test":
        return True
    if stem.startswith("test_"):
        return True
    if stem.endswith("_test"):
        return True

    return False


def find_paired_test_files(
    all_files: set[str],
) -> dict[str, str]:
    """Find test files and pair them with their implementation files.

    Pairs are found by stripping test prefixes/suffixes and searching
    for a matching implementation file. conftest.py files are standalone
    test utilities and are never paired.

    Args:
        all_files: Set of all file paths in the project.

    Returns:
        Mapping of test file path to its implementation file path.
        Only test files with a confirmed match are included.
    """
    non_test_files = {f for f in all_files if not detect_test_file(f)}
    pairs: dict[str, str] = {}

    # Build a lookup from basename stem to full paths
    stem_to_paths = _build_stem_lookup(non_test_files)

    for test_file in sorted(all_files):
        if not detect_test_file(test_file):
            continue
        basename = os.path.basename(test_file)
        if basename == "conftest.py":
            continue

        impl_stem = _extract_impl_stem(test_file)
        if impl_stem is None:
            continue

        match = _find_best_match(impl_stem, stem_to_paths)
        if match is not None:
            pairs[test_file] = match

    return pairs


# ---------------------------------------------------------------------------
# Pass assignment
# ---------------------------------------------------------------------------


def _assign_passes(
    *,
    graph: DependencyGraph,
    classification: LayerClassification,
    parse_results: dict[str, ParseResult],
    test_pairs: dict[str, str],
    config: ReadingConfig,
) -> dict[str, ReadingPass]:
    """Assign each file to one of the three reading passes.

    Test files paired with an implementation inherit its pass.
    Standalone test utilities and conftest go to UTILITY (or as
    configured by config.test_pass).
    """
    assignments: dict[str, ReadingPass] = {}

    # Determine which pass unpaired/orphan tests should go in
    test_default_pass = _test_mode_to_reading_pass(config.test_pass)

    for path in sorted(graph.nodes):
        if detect_test_file(path):
            continue  # handled after impl files
        assignments[path] = _classify_pass(
            path=path,
            graph=graph,
            classification=classification,
            parse_results=parse_results,
            config=config,
        )

    # Assign test files
    for test_path in sorted(graph.nodes):
        if not detect_test_file(test_path):
            continue
        if test_path in test_pairs:
            impl_path = test_pairs[test_path]
            assignments[test_path] = assignments.get(
                impl_path, test_default_pass,
            )
        else:
            assignments[test_path] = test_default_pass

    return assignments


def _test_mode_to_reading_pass(mode: TestFileMode) -> ReadingPass:
    """Convert a TestFileMode to the corresponding ReadingPass.

    For SEPARATE and SKIP modes, we default to UTILITY since test files
    will be handled specially (moved to end or removed).
    """
    mode_map: dict[TestFileMode, ReadingPass] = {
        TestFileMode.CONTRACTS: ReadingPass.CONTRACTS,
        TestFileMode.DATA_FLOW: ReadingPass.DATA_FLOW,
        TestFileMode.UTILITY: ReadingPass.UTILITY,
        TestFileMode.SEPARATE: ReadingPass.UTILITY,
        TestFileMode.SKIP: ReadingPass.UTILITY,
    }
    return mode_map[mode]


def _classify_pass(
    *,
    path: str,
    graph: DependencyGraph,
    classification: LayerClassification,
    parse_results: dict[str, ParseResult],
    config: ReadingConfig,
) -> ReadingPass:
    """Classify a single non-test file into a reading pass."""
    # Check custom pass overrides first (highest priority)
    override = match_custom_pass_override(path, config)
    if override is not None:
        return ReadingPass(override)

    if _is_utility_path(path):
        return ReadingPass.UTILITY

    node = graph.nodes[path]
    result = parse_results.get(path)

    if _is_contract_surface(path=path, node=node, result=result):
        return ReadingPass.CONTRACTS

    return ReadingPass.DATA_FLOW


def _is_utility_path(path: str) -> bool:
    """Check if a file resides in a utility-style directory."""
    parts = path.replace("\\", "/").split("/")
    return any(part in _UTILITY_DIRS for part in parts[:-1])


def _is_contract_surface(
    *,
    path: str,
    node: object,
    result: ParseResult | None,
) -> bool:
    """Determine if a file is a contract surface (Pass 1).

    A file qualifies if:
    1. Its name matches a known contract-surface convention
       (types.py, interfaces.py, models.py, schema.py, constants.py), OR
    2. It is an ``__init__.py`` that re-exports (imports + exports), OR
    3. It has a high ratio of type/class exports to total exports, OR
    4. It has high fanIn with low fanOut (widely imported interface).
    """
    # Check name-based contract heuristic
    basename = os.path.basename(path)
    stem = os.path.splitext(basename)[0]
    if stem in _CONTRACT_NAME_STEMS:
        return True

    # Check __init__.py that re-exports from submodules
    if basename == "__init__.py" and result is not None:
        if result.imports and result.exports:
            return True

    # Access node attributes via getattr for the frozen FileNode
    fan_in = getattr(node, "fan_in", 0)
    fan_out = getattr(node, "fan_out", 0)

    if result is not None and result.exports:
        total_exports = len(result.exports)
        contract_exports = sum(
            1 for e in result.exports if e.kind in _CONTRACT_EXPORT_KINDS
        )
        if contract_exports / total_exports >= _CONTRACT_EXPORT_RATIO:
            return True

    # High fanIn, low fanOut = widely used interface
    if fan_in >= _CONTRACT_FAN_IN_THRESHOLD and fan_out <= 1:
        return True

    return False


# ---------------------------------------------------------------------------
# Topological sort within passes
# ---------------------------------------------------------------------------


def _sort_within_passes(
    *,
    pass_assignments: dict[str, ReadingPass],
    graph: DependencyGraph,
    classification: LayerClassification,
) -> list[str]:
    """Sort files: passes in order, topological within each pass.

    Returns a flat list of non-test file paths in reading order.
    Test files are excluded here and interleaved later.
    """
    result: list[str] = []

    for reading_pass in (
        ReadingPass.CONTRACTS,
        ReadingPass.DATA_FLOW,
        ReadingPass.UTILITY,
    ):
        pass_files = [
            p for p, rp in sorted(pass_assignments.items())
            if rp == reading_pass and not detect_test_file(p)
        ]
        sorted_files = _topological_sort(
            files=pass_files,
            graph=graph,
            classification=classification,
        )
        result.extend(sorted_files)

    return result


def _topological_sort(
    *,
    files: list[str],
    graph: DependencyGraph,
    classification: LayerClassification,
) -> list[str]:
    """Topologically sort a set of files using Kahn's algorithm.

    Tie-breaking: layer order (foundation first), then fanIn
    (most-imported first), then alphabetical.
    """
    file_set = set(files)
    if not file_set:
        return []

    # Build adjacency restricted to this file set
    in_degree: dict[str, int] = {f: 0 for f in file_set}
    adj: dict[str, list[str]] = {f: [] for f in file_set}

    for f in file_set:
        node = graph.nodes.get(f)
        if node is None:
            continue
        for dep in node.imports:
            if dep in file_set:
                in_degree[f] += 1
                adj[dep].append(f)

    # Kahn's algorithm with priority-based tie-breaking
    queue = sorted(
        [f for f in file_set if in_degree[f] == 0],
        key=lambda p: _sort_key(p, graph, classification),
    )
    result: list[str] = []

    while queue:
        current = queue.pop(0)
        result.append(current)

        dependents = sorted(adj[current])
        for dep in dependents:
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)
        # Re-sort queue after adding new items
        queue.sort(key=lambda p: _sort_key(p, graph, classification))

    # Handle any remaining files (cycles) -- add in sort-key order
    remaining = sorted(
        file_set - set(result),
        key=lambda p: _sort_key(p, graph, classification),
    )
    result.extend(remaining)

    return result


def _sort_key(
    path: str,
    graph: DependencyGraph,
    classification: LayerClassification,
) -> tuple[int, int, str]:
    """Produce a sort key for tie-breaking: (layer_order, -fanIn, path)."""
    layer = classification.layers.get(path, Layer.FEATURES)
    layer_rank = _LAYER_ORDER.get(layer, 2)
    node = graph.nodes.get(path)
    fan_in = node.fan_in if node else 0
    # Negate fanIn so higher fanIn sorts first
    return (layer_rank, -fan_in, path)


# ---------------------------------------------------------------------------
# Test file interleaving
# ---------------------------------------------------------------------------


def _interleave_test_files(
    *,
    sorted_order: list[str],
    test_pairs: dict[str, str],
    pass_assignments: dict[str, ReadingPass],
    graph: DependencyGraph,
    classification: LayerClassification,
) -> list[str]:
    """Insert test files immediately after their implementation files.

    Paired test files are inserted right after their impl file.
    Unpaired test files (orphans + conftest) are appended at the end
    of the utility pass section.
    """
    # Build reverse: impl -> list of test files
    impl_to_tests: dict[str, list[str]] = {}
    for test_path, impl_path in sorted(test_pairs.items()):
        if impl_path not in impl_to_tests:
            impl_to_tests[impl_path] = []
        impl_to_tests[impl_path].append(test_path)

    # Sort test files for determinism
    for tests in impl_to_tests.values():
        tests.sort()

    result: list[str] = []
    placed_tests: set[str] = set()

    for path in sorted_order:
        result.append(path)
        if path in impl_to_tests:
            for test_path in impl_to_tests[path]:
                result.append(test_path)
                placed_tests.add(test_path)

    # Append unpaired test files at end (utility pass)
    all_test_files = sorted(
        p for p in pass_assignments if detect_test_file(p)
    )
    for test_path in all_test_files:
        if test_path not in placed_tests:
            result.append(test_path)

    return result


def _separate_test_files(
    *,
    sorted_order: list[str],
    pass_assignments: dict[str, ReadingPass],
    graph: DependencyGraph,
    classification: LayerClassification,
) -> list[str]:
    """Place all test files after all non-test files (separate pass mode).

    Non-test files appear in their normal topological order across all
    three passes. Test files are then appended in topological order.
    """
    non_test = [p for p in sorted_order if not detect_test_file(p)]
    test_files = sorted(
        p for p in pass_assignments if detect_test_file(p)
    )
    # Sort test files topologically for determinism
    sorted_tests = _topological_sort(
        files=test_files,
        graph=graph,
        classification=classification,
    )
    return non_test + sorted_tests


# ---------------------------------------------------------------------------
# Entry construction
# ---------------------------------------------------------------------------


def _build_entries(
    *,
    ordered_paths: list[str],
    graph: DependencyGraph,
    classification: LayerClassification,
    parse_results: dict[str, ParseResult],
    pass_assignments: dict[str, ReadingPass],
    test_pairs: dict[str, str],
) -> tuple[ReadingOrderEntry, ...]:
    """Build ReadingOrderEntry objects with sequential indices."""
    entries: list[ReadingOrderEntry] = []

    for index, path in enumerate(ordered_paths):
        node = graph.nodes.get(path)
        result = parse_results.get(path)
        layer = classification.layers.get(path, Layer.FEATURES)
        reading_pass = pass_assignments.get(path, ReadingPass.DATA_FLOW)
        paired_with = test_pairs.get(path)

        imports = node.imports if node else ()
        imported_by = node.imported_by if node else ()
        exports = tuple(e.name for e in result.exports) if result else ()

        reason = _build_reason(
            path=path,
            reading_pass=reading_pass,
            layer=layer,
            node=node,
            paired_with=paired_with,
        )

        entries.append(ReadingOrderEntry(
            index=index,
            path=path,
            layer=layer,
            reading_pass=reading_pass,
            reason=reason,
            complexity="low",  # placeholder; real complexity from analysis
            line_count=0,
            imports=imports,
            imported_by=imported_by,
            exports=exports,
            paired_with=paired_with,
        ))

    return tuple(entries)


def _build_reason(
    *,
    path: str,
    reading_pass: ReadingPass,
    layer: Layer,
    node: object | None,
    paired_with: str | None,
) -> str:
    """Generate a human-readable reason for a file's position."""
    if paired_with is not None:
        return f"Test file for {paired_with}."

    fan_in = getattr(node, "fan_in", 0)
    fan_out = getattr(node, "fan_out", 0)

    parts: list[str] = []

    if reading_pass == ReadingPass.CONTRACTS:
        parts.append(f"Contract surface ({layer.value} layer).")
        if fan_in > 0:
            parts.append(f"Imported by {fan_in} file(s).")
    elif reading_pass == ReadingPass.DATA_FLOW:
        parts.append(f"Data flow path ({layer.value} layer).")
        if fan_out > 0:
            parts.append(f"Depends on {fan_out} file(s).")
    else:
        parts.append(f"Utility code ({layer.value} layer).")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Internal helpers for test file pairing
# ---------------------------------------------------------------------------


def _build_stem_lookup(
    non_test_files: set[str],
) -> dict[str, list[str]]:
    """Build a mapping from file stem to full paths."""
    lookup: dict[str, list[str]] = {}
    for path in sorted(non_test_files):
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem not in lookup:
            lookup[stem] = []
        lookup[stem].append(path)
    return lookup


def _extract_impl_stem(test_path: str) -> str | None:
    """Extract the implementation file stem from a test file path.

    Examples:
        test_config.py -> config
        config_test.py -> config
        tests/test_model.py -> model
    """
    basename = os.path.basename(test_path)
    stem = os.path.splitext(basename)[0]

    if stem.startswith("test_"):
        return stem[5:]  # Remove "test_" prefix
    if stem.endswith("_test"):
        return stem[:-5]  # Remove "_test" suffix

    return None


def _find_best_match(
    impl_stem: str,
    stem_to_paths: dict[str, list[str]],
) -> str | None:
    """Find the best matching implementation file for a given stem.

    Returns the first match (deterministic due to sorted paths).
    """
    candidates = stem_to_paths.get(impl_stem)
    if candidates:
        return candidates[0]
    return None
