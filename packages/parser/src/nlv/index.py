"""Pipeline orchestrator for /read-index (BED-74).

Chains all parser components in sequence to generate map.json and
initialize progress.json:

1. Walk source files
2. Parse each file with the appropriate language plugin
3. Resolve imports
4. Build the dependency graph
5. Classify architectural layers
6. Compute three-pass reading order
7. Compute content hashes
8. Write map.json
9. Initialize progress.json
10. Format a human-readable summary
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from nlv.analysis import compute_complexity
from nlv.graph import DependencyGraph, build_graph
from nlv.hashing import compute_content_hashes
from nlv.layers import Layer, LayerClassification, classify_layers
from nlv.output import write_map_json
from nlv.plugins import ParseResult, PluginRegistry
from nlv.plugins.python import PythonPlugin
from nlv.progress import ProgressManager
from nlv.reading_order import (
    ReadingOrderEntry,
    compute_reading_order,
)
from nlv.walker import SourceFile, walk_tree

logger = logging.getLogger(__name__)

_GUIDE_DIR_NAME = ".codebase-guide"


@dataclass(frozen=True)
class IndexResult:
    """Result of running the index pipeline.

    Attributes:
        total_files: Number of files indexed.
        layer_counts: File count per architectural layer.
        reading_order: The computed reading order entries.
        summary: Human-readable summary string.
    """

    total_files: int
    layer_counts: dict[Layer, int]
    reading_order: tuple[ReadingOrderEntry, ...]
    summary: str


def run_index(root: Path) -> IndexResult:
    """Run the full parser pipeline and produce map.json + progress.json.

    Args:
        root: Root directory of the project to index.

    Returns:
        An IndexResult with stats and a human-readable summary.

    Raises:
        NotADirectoryError: If root does not exist or is not a directory.
    """
    root = root.resolve()

    # 1. Set up plugin registry
    registry = _setup_registry()
    extensions = registry.get_supported_extensions()

    # 2. Walk source files
    source_files = walk_tree(root, extensions=extensions)
    if not source_files:
        return _empty_result()

    # 3. Parse each file
    parse_results = _parse_files(root, source_files, registry)

    # 4. Resolve imports
    resolved_imports = _resolve_imports(root, parse_results, registry)

    # 5. Build dependency graph
    graph = build_graph(
        parse_results=parse_results,
        resolved_imports=resolved_imports,
    )

    # 6. Detect entry points
    entry_points = _detect_entry_points(parse_results)

    # 7. Classify layers
    classification = classify_layers(
        graph=graph,
        entry_points=entry_points,
    )

    # 8. Compute reading order with complexity
    reading_order = _compute_order_with_complexity(
        root=root,
        graph=graph,
        classification=classification,
        parse_results=parse_results,
    )

    # 9. Compute content hashes
    file_paths = [root / sf.path for sf in source_files]
    content_hashes = compute_content_hashes(file_paths, root=root)

    # 10. Write map.json
    guide_dir = root / _GUIDE_DIR_NAME
    map_path = write_map_json(
        output_dir=guide_dir,
        repo_root=str(root),
        graph=graph,
        classification=classification,
        reading_order=reading_order,
        content_hashes=content_hashes,
    )

    # 11. Initialize progress.json
    _init_progress(guide_dir, map_path)

    # 12. Build result
    layer_counts = _count_layers(classification)
    summary = _format_summary(
        total_files=len(reading_order),
        layer_counts=layer_counts,
    )

    return IndexResult(
        total_files=len(reading_order),
        layer_counts=layer_counts,
        reading_order=reading_order,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------


def _setup_registry() -> PluginRegistry:
    """Create and populate the plugin registry."""
    registry = PluginRegistry()
    registry.register(PythonPlugin())
    return registry


def _parse_files(
    root: Path,
    source_files: list[SourceFile],
    registry: PluginRegistry,
) -> dict[str, ParseResult]:
    """Parse all source files using the appropriate plugin."""
    results: dict[str, ParseResult] = {}
    for sf in source_files:
        rel_path = sf.path
        abs_path = root / rel_path
        plugin = registry.get_plugin_for_file(abs_path)
        if plugin is None:
            logger.debug("No plugin for %s, skipping", rel_path)
            continue
        try:
            result = plugin.parse_file(abs_path)
        except FileNotFoundError:
            logger.warning("File not found during parse: %s", rel_path)
            continue
        results[rel_path] = result
    return results


def _resolve_imports(
    root: Path,
    parse_results: dict[str, ParseResult],
    registry: PluginRegistry,
) -> dict[tuple[str, str], str]:
    """Resolve all imports to file paths."""
    resolved: dict[tuple[str, str], str] = {}
    for from_file, result in sorted(parse_results.items()):
        abs_from = root / from_file
        plugin = registry.get_plugin_for_file(abs_from)
        if plugin is None:
            continue
        for imp in result.imports:
            target = plugin.resolve_import(imp, abs_from)
            if target is not None:
                try:
                    rel_target = target.relative_to(root).as_posix()
                except ValueError:
                    continue
                resolved[(from_file, imp.source)] = rel_target
    return resolved


def _detect_entry_points(
    parse_results: dict[str, ParseResult],
) -> set[str]:
    """Collect file paths flagged as entry points by their plugin."""
    return {
        path for path, result in parse_results.items()
        if result.entry_point
    }


def _compute_order_with_complexity(
    *,
    root: Path,
    graph: DependencyGraph,
    classification: LayerClassification,
    parse_results: dict[str, ParseResult],
) -> tuple[ReadingOrderEntry, ...]:
    """Compute reading order, then enrich with complexity data."""
    base_order = compute_reading_order(
        graph=graph,
        classification=classification,
        parse_results=parse_results,
    )

    enriched: list[ReadingOrderEntry] = []
    for entry in base_order:
        abs_path = root / entry.path
        try:
            comp = compute_complexity(abs_path)
        except FileNotFoundError:
            enriched.append(entry)
            continue

        enriched.append(ReadingOrderEntry(
            index=entry.index,
            path=entry.path,
            layer=entry.layer,
            reading_pass=entry.reading_pass,
            reason=entry.reason,
            complexity=comp.complexity.value,
            line_count=comp.line_count,
            imports=entry.imports,
            imported_by=entry.imported_by,
            exports=entry.exports,
            paired_with=entry.paired_with,
        ))

    return tuple(enriched)


def _init_progress(
    guide_dir: Path,
    map_path: Path,
) -> None:
    """Initialize progress.json from the generated map.json."""
    map_content = map_path.read_text()
    map_data = json.loads(map_content)
    map_hash = hashlib.sha256(map_content.encode()).hexdigest()

    mgr = ProgressManager(guide_dir)
    mgr.create(map_data, map_hash, force=True)


def _count_layers(
    classification: LayerClassification,
) -> dict[Layer, int]:
    """Count files per layer."""
    return {
        layer: len(files)
        for layer, files in classification.layer_groups.items()
    }


# ---------------------------------------------------------------------------
# Summary formatting
# ---------------------------------------------------------------------------


def _empty_result() -> IndexResult:
    """Return an IndexResult for a project with no source files."""
    layer_counts = {layer: 0 for layer in Layer}
    return IndexResult(
        total_files=0,
        layer_counts=layer_counts,
        reading_order=(),
        summary="Indexed 0 files. No supported source files found.",
    )


_LAYER_EXAMPLE_WORDS: dict[Layer, str] = {
    Layer.FOUNDATION: "config, constants, types",
    Layer.CORE: "models, services, data",
    Layer.FEATURES: "components, routes, hooks",
    Layer.INTEGRATION: "api, middleware, pipeline",
    Layer.ENTRY: "pages, app, main",
}


def _format_summary(
    total_files: int,
    layer_counts: dict[Layer, int],
) -> str:
    """Format the human-readable summary shown after indexing.

    Follows the output format from SPEC.md.
    """
    active_layers = {
        layer: count
        for layer, count in layer_counts.items()
        if count > 0
    }
    layer_count = len(active_layers)

    lines: list[str] = []
    file_word = "file" if total_files == 1 else "files"
    layer_word = "layer" if layer_count == 1 else "layers"
    lines.append(
        f"Indexed {total_files} {file_word} across "
        f"{layer_count} {layer_word}:"
    )

    for layer in Layer:
        count = layer_counts.get(layer, 0)
        if count > 0:
            examples = _LAYER_EXAMPLE_WORDS[layer]
            lines.append(f"  {layer.value}: {count} files ({examples})")

    lines.append("Reading order computed. Run /read-next to start.")
    return "\n".join(lines)
