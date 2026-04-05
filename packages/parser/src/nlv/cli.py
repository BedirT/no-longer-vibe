"""CLI entry point for nlv (BED-71).

Wires the full pipeline together: walk source files, parse with language
plugins, build dependency graph, classify layers, compute reading order,
hash content, score complexity, and write map.json.

Usage::

    nlv [path] [--verbose]
    python -m nlv [path] [--verbose]

The ``path`` argument defaults to the current working directory.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from nlv.analysis import compute_complexity, detect_entry_point
from nlv.graph import DependencyGraph, build_graph
from nlv.hashing import compute_content_hashes
from nlv.layers import Layer, LayerClassification, classify_layers
from nlv.output import write_map_json
from nlv.plugins import ParseResult, PluginRegistry
from nlv.plugins.python import PythonPlugin
from nlv.reading_order import ReadingOrderEntry, compute_reading_order
from nlv.walker import SourceFile, walk_tree

logger = logging.getLogger(__name__)

_OUTPUT_DIR_NAME = ".codebase-guide"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse argument parser."""
    parser = argparse.ArgumentParser(
        prog="nlv",
        description=(
            "Deterministic codebase reading order tool. "
            "Indexes source files, builds a dependency graph, "
            "and generates .codebase-guide/map.json."
        ),
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path to the project directory (defaults to current directory).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose (DEBUG) logging output.",
    )
    return parser


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------


def _setup_logging(*, verbose: bool) -> None:
    """Configure the logging level for the nlv package."""
    level = logging.DEBUG if verbose else logging.WARNING
    nlv_logger = logging.getLogger("nlv")
    nlv_logger.setLevel(level)
    if not nlv_logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        nlv_logger.addHandler(handler)


def _resolve_path(raw_path: str | None) -> Path:
    """Resolve and validate the target path.

    Args:
        raw_path: User-supplied path string, or None for cwd.

    Returns:
        Resolved absolute Path.

    Raises:
        SystemExit: If the path does not exist or is not a directory.
    """
    if raw_path is None:
        target = Path.cwd()
    else:
        target = Path(raw_path)

    if not target.exists():
        logger.error("Path does not exist: %s", target)
        raise SystemExit(1)

    if not target.is_dir():
        logger.error("Path is not a directory: %s", target)
        raise SystemExit(1)

    return target.resolve()


def _run_pipeline(root: Path) -> None:
    """Run the full indexing pipeline and write map.json.

    Steps:
    1. Walk source files
    2. Parse each file with the appropriate language plugin
    3. Build the dependency graph
    4. Classify files into layers
    5. Compute reading order
    6. Compute content hashes and complexity
    7. Generate and write map.json
    8. Print summary

    Args:
        root: Resolved absolute path to the project root.
    """
    registry = _setup_registry()
    extensions = registry.get_supported_extensions()

    # Step 1: Walk
    source_files = walk_tree(root, extensions)
    logger.debug("Walked %d source files", len(source_files))

    # Step 2: Parse
    parse_results, resolved_imports = _parse_files(
        root=root, source_files=source_files, registry=registry,
    )

    # Step 3: Build dependency graph
    graph = build_graph(
        parse_results=parse_results,
        resolved_imports=resolved_imports,
    )
    logger.debug("Built graph with %d nodes", len(graph.nodes))

    # Step 4: Detect entry points and classify layers
    entry_points = _detect_entry_points(root=root, graph=graph)
    classification = classify_layers(
        graph=graph, entry_points=entry_points,
    )

    # Step 5: Compute reading order
    reading_order = compute_reading_order(
        graph=graph,
        classification=classification,
        parse_results=parse_results,
    )

    # Step 6: Content hashes and complexity
    file_paths = [root / sf.path for sf in source_files]
    content_hashes = compute_content_hashes(file_paths, root=root)
    _enrich_reading_order_complexity(root=root, reading_order=reading_order)

    # Step 7: Write map.json
    output_dir = root / _OUTPUT_DIR_NAME
    write_map_json(
        output_dir=output_dir,
        repo_root=str(root),
        graph=graph,
        classification=classification,
        reading_order=reading_order,
        content_hashes=content_hashes,
    )

    # Step 8: Print summary
    _print_summary(
        total_files=len(source_files),
        classification=classification,
    )


def _setup_registry() -> PluginRegistry:
    """Create and configure the plugin registry."""
    registry = PluginRegistry()
    registry.register(PythonPlugin())
    return registry


def _parse_files(
    *,
    root: Path,
    source_files: list[SourceFile],
    registry: PluginRegistry,
) -> tuple[dict[str, ParseResult], dict[tuple[str, str], str]]:
    """Parse all source files and resolve imports.

    Returns:
        Tuple of (parse_results, resolved_imports).
    """
    parse_results: dict[str, ParseResult] = {}
    resolved_imports: dict[tuple[str, str], str] = {}

    for sf in source_files:
        abs_path = root / sf.path
        plugin = registry.get_plugin_for_file(abs_path)
        if plugin is None:
            logger.debug("No plugin for %s, skipping", sf.path)
            continue

        try:
            result = plugin.parse_file(abs_path)
        except Exception:
            logger.warning("Failed to parse %s, skipping", sf.path)
            continue

        parse_results[sf.path] = result

        # Resolve imports
        for imp in result.imports:
            resolved = plugin.resolve_import(imp, abs_path)
            if resolved is not None:
                try:
                    rel = resolved.relative_to(root).as_posix()
                    resolved_imports[(sf.path, imp.source)] = rel
                except ValueError:
                    # Resolved path is outside the project root
                    pass

    logger.debug("Parsed %d files", len(parse_results))
    return parse_results, resolved_imports


def _detect_entry_points(
    *,
    root: Path,
    graph: DependencyGraph,
) -> set[str]:
    """Detect entry points for all files in the graph.

    Returns:
        Set of relative file paths that are entry points.
    """
    entry_points: set[str] = set()

    for path, node in sorted(graph.nodes.items()):
        abs_path = root / path
        if not abs_path.exists():
            continue
        importers = set(node.imported_by)
        try:
            if detect_entry_point(abs_path, importers=importers):
                entry_points.add(path)
        except Exception:
            logger.debug("Entry point detection failed for %s", path)

    logger.debug("Detected %d entry points", len(entry_points))
    return entry_points


def _enrich_reading_order_complexity(
    *,
    root: Path,
    reading_order: tuple[ReadingOrderEntry, ...],
) -> None:
    """Compute complexity for each file in the reading order.

    Mutates nothing -- complexity was already integrated into the
    reading order entries as placeholders. For the CLI summary this
    is informational only; the real complexity data goes into map.json
    via the reading_order entries.

    Note: ReadingOrderEntry is frozen, so we log complexity but cannot
    mutate the entries. The output module uses the entry's line_count
    and complexity fields which are placeholders from reading_order.
    Full complexity data can be added in a future iteration.
    """
    for entry in reading_order:
        abs_path = root / entry.path
        if abs_path.exists():
            try:
                result = compute_complexity(abs_path)
                logger.debug(
                    "%s: %s (%d lines)",
                    entry.path, result.complexity.value, result.line_count,
                )
            except Exception:
                logger.debug(
                    "Complexity computation failed for %s", entry.path,
                )


# ---------------------------------------------------------------------------
# Summary output
# ---------------------------------------------------------------------------


def _print_summary(
    *,
    total_files: int,
    classification: LayerClassification,
) -> None:
    """Print the indexing summary to stdout.

    Format matches the /read-index spec output.
    """
    lines: list[str] = []
    lines.append(f"Indexed {total_files} files across 5 layers:")

    for layer in Layer:
        files = classification.layer_groups.get(layer, ())
        lines.append(f"  {layer.value}: {len(files)} files")

    lines.append(f"Output: {_OUTPUT_DIR_NAME}/map.json")

    sys.stdout.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Run the nlv CLI.

    Args:
        argv: Command-line arguments. Defaults to sys.argv[1:].
    """
    if argv is None:
        argv = sys.argv[1:]

    parser = _build_parser()
    args = parser.parse_args(argv)

    _setup_logging(verbose=args.verbose)

    root = _resolve_path(args.path)
    logger.debug("Target path: %s", root)

    _run_pipeline(root)
