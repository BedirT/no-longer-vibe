"""Dependency graph construction and analysis (BED-64).

Builds a directed graph where nodes are source files and edges are import
relationships. Provides adjacency list representation, cycle detection,
dependency depth computation, reverse dependencies, and derived metrics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from nlv.plugins import ParseResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileNode:
    """A node in the dependency graph representing a single source file.

    Attributes:
        path: Relative file path (forward slashes).
        imports: Sorted tuple of file paths this file imports.
        imported_by: Sorted tuple of file paths that import this file.
        fan_in: Number of files that import this file.
        fan_out: Number of files this file imports.
        depth: Longest dependency chain depth (0 for root nodes).
        is_leaf: True if nothing imports this file (fan_in == 0).
        is_root: True if this file imports nothing (fan_out == 0).
    """

    path: str
    imports: tuple[str, ...]
    imported_by: tuple[str, ...]
    fan_in: int
    fan_out: int
    depth: int
    is_leaf: bool
    is_root: bool


@dataclass(frozen=True)
class ExternalDep:
    """An external dependency (stdlib, third-party) tracked but not graphed.

    Attributes:
        source: The import source string (e.g. ``"os.path"``).
        imported_by: Sorted tuple of file paths that import this.
    """

    source: str
    imported_by: tuple[str, ...]


@dataclass(frozen=True)
class DependencyGraph:
    """The complete dependency graph for a codebase.

    Attributes:
        nodes: Mapping of file path to FileNode.
        external_deps: Tuple of external dependencies.
        cycles: Tuple of detected cycles, each a tuple of file paths.
    """

    nodes: dict[str, FileNode]
    external_deps: tuple[ExternalDep, ...]
    cycles: tuple[tuple[str, ...], ...]


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph(
    *,
    parse_results: dict[str, ParseResult],
    resolved_imports: dict[tuple[str, str], str],
) -> DependencyGraph:
    """Build a dependency graph from parsed file data.

    Args:
        parse_results: Mapping of relative file paths to their ParseResult.
        resolved_imports: Mapping of ``(from_file, import_source)`` to the
            resolved relative file path. Only local (in-project) resolved
            imports should be included. Unresolved or external imports are
            detected by their absence from this mapping.

    Returns:
        A DependencyGraph with all nodes, external deps, and cycles.
    """
    known_files = set(parse_results)

    adjacency = _build_adjacency(parse_results, resolved_imports, known_files)
    external_map = _collect_external_deps(
        parse_results, resolved_imports, known_files,
    )
    cycles = _detect_cycles(adjacency)
    cycle_edges = _cycle_edge_set(cycles)
    depths = _compute_depths(adjacency, cycle_edges)

    nodes = _assemble_nodes(adjacency, depths)
    external_deps = _assemble_external_deps(external_map)

    return DependencyGraph(
        nodes=nodes,
        external_deps=external_deps,
        cycles=cycles,
    )


# ---------------------------------------------------------------------------
# Adjacency list construction
# ---------------------------------------------------------------------------


def _build_adjacency(
    parse_results: dict[str, ParseResult],
    resolved_imports: dict[tuple[str, str], str],
    known_files: set[str],
) -> dict[str, set[str]]:
    """Build a forward adjacency list: file -> set of files it imports.

    Only includes edges where the target is a known (parsed) file.
    """
    adjacency: dict[str, set[str]] = {f: set() for f in known_files}

    for from_file, result in sorted(parse_results.items()):
        for imp in result.imports:
            resolved = resolved_imports.get((from_file, imp.source))
            if resolved is not None and resolved in known_files:
                adjacency[from_file].add(resolved)

    return adjacency


# ---------------------------------------------------------------------------
# External dependency collection
# ---------------------------------------------------------------------------


def _collect_external_deps(
    parse_results: dict[str, ParseResult],
    resolved_imports: dict[tuple[str, str], str],
    known_files: set[str],
) -> dict[str, set[str]]:
    """Collect external dependencies: source -> set of importing files.

    An import is external if it either has no resolved path or resolves
    to a file outside the known file set.
    """
    external_map: dict[str, set[str]] = {}

    for from_file, result in sorted(parse_results.items()):
        for imp in result.imports:
            resolved = resolved_imports.get((from_file, imp.source))
            if resolved is None or resolved not in known_files:
                if imp.source not in external_map:
                    external_map[imp.source] = set()
                external_map[imp.source].add(from_file)

    return external_map


# ---------------------------------------------------------------------------
# Cycle detection (Tarjan's algorithm for SCCs)
# ---------------------------------------------------------------------------


def _detect_cycles(
    adjacency: dict[str, set[str]],
) -> tuple[tuple[str, ...], ...]:
    """Detect all cycles using Tarjan's strongly connected components.

    Returns a tuple of cycles, where each cycle is a sorted tuple of
    file paths. Only SCCs with more than one node, or single-node SCCs
    with a self-edge, are reported as cycles.
    """
    sccs = _find_sccs(adjacency)
    return _filter_cyclic_sccs(sccs, adjacency)


def _find_sccs(
    adjacency: dict[str, set[str]],
) -> list[list[str]]:
    """Find all strongly connected components using Tarjan's algorithm."""
    index_counter = [0]
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    sccs: list[list[str]] = []

    def strongconnect(node: str) -> None:
        indices[node] = index_counter[0]
        lowlinks[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        on_stack.add(node)

        for neighbor in sorted(adjacency.get(node, set())):
            if neighbor not in indices:
                strongconnect(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[neighbor])

        if lowlinks[node] == indices[node]:
            scc: list[str] = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                scc.append(w)
                if w == node:
                    break
            sccs.append(scc)

    for node in sorted(adjacency):
        if node not in indices:
            strongconnect(node)

    return sccs


def _filter_cyclic_sccs(
    sccs: list[list[str]],
    adjacency: dict[str, set[str]],
) -> tuple[tuple[str, ...], ...]:
    """Filter SCCs to only those representing actual cycles."""
    cycles: list[tuple[str, ...]] = []
    for scc in sccs:
        if len(scc) > 1:
            cycles.append(tuple(sorted(scc)))
        elif len(scc) == 1 and scc[0] in adjacency.get(scc[0], set()):
            # Self-loop
            cycles.append((scc[0],))
    return tuple(sorted(cycles))


def _cycle_edge_set(
    cycles: tuple[tuple[str, ...], ...],
) -> set[tuple[str, str]]:
    """Build a set of edges that participate in cycles.

    Used by depth computation to break cycles: edges within an SCC
    are ignored when computing longest path.
    """
    edges: set[tuple[str, str]] = set()
    for cycle in cycles:
        members = set(cycle)
        for a in members:
            for b in members:
                if a != b:
                    edges.add((a, b))
        # Self-loops
        if len(cycle) == 1:
            edges.add((cycle[0], cycle[0]))

    return edges


# ---------------------------------------------------------------------------
# Depth computation (longest path from roots, breaking cycles)
# ---------------------------------------------------------------------------


def _compute_depths(
    adjacency: dict[str, set[str]],
    cycle_edges: set[tuple[str, str]],
) -> dict[str, int]:
    """Compute dependency depth for each file.

    Depth is the longest path from a root (file with no imports) to this
    file, ignoring back-edges within cycles. Uses memoized DFS.
    """
    depths: dict[str, int] = {}

    def dfs(node: str, visiting: set[str]) -> int:
        if node in depths:
            return depths[node]

        neighbors = adjacency.get(node, set())
        if not neighbors:
            depths[node] = 0
            return 0

        visiting.add(node)
        max_dep = 0
        for neighbor in sorted(neighbors):
            # Skip cycle back-edges
            if (node, neighbor) in cycle_edges:
                continue
            # Skip if currently visiting (safety against missed cycles)
            if neighbor in visiting:
                continue
            dep = dfs(neighbor, visiting)
            max_dep = max(max_dep, dep + 1)

        visiting.discard(node)
        depths[node] = max_dep
        return max_dep

    for node in sorted(adjacency):
        if node not in depths:
            dfs(node, set())

    return depths


# ---------------------------------------------------------------------------
# Assembly helpers
# ---------------------------------------------------------------------------


def _build_reverse_adjacency(
    adjacency: dict[str, set[str]],
) -> dict[str, set[str]]:
    """Build the reverse adjacency list: file -> set of files that import it."""
    reverse: dict[str, set[str]] = {f: set() for f in adjacency}
    for from_file, targets in adjacency.items():
        for target in targets:
            if target in reverse:
                reverse[target].add(from_file)
    return reverse


def _assemble_nodes(
    adjacency: dict[str, set[str]],
    depths: dict[str, int],
) -> dict[str, FileNode]:
    """Assemble FileNode objects from adjacency lists and depths."""
    reverse = _build_reverse_adjacency(adjacency)
    nodes: dict[str, FileNode] = {}

    for path in sorted(adjacency):
        imports = tuple(sorted(adjacency[path]))
        imported_by = tuple(sorted(reverse.get(path, set())))
        fan_out = len(imports)
        fan_in = len(imported_by)

        nodes[path] = FileNode(
            path=path,
            imports=imports,
            imported_by=imported_by,
            fan_in=fan_in,
            fan_out=fan_out,
            depth=depths.get(path, 0),
            is_leaf=(fan_in == 0),
            is_root=(fan_out == 0),
        )

    return nodes


def _assemble_external_deps(
    external_map: dict[str, set[str]],
) -> tuple[ExternalDep, ...]:
    """Assemble ExternalDep objects from the external dependency map."""
    deps: list[ExternalDep] = []
    for source in sorted(external_map):
        imported_by = tuple(sorted(external_map[source]))
        deps.append(ExternalDep(source=source, imported_by=imported_by))
    return tuple(deps)
