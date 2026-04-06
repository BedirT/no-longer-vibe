"""Pipeline orchestrator for /read-index (BED-74).

Extracts the full parser pipeline into a reusable function that can be
called from both the CLI and the Claude Code skill. Chains all parser
components in sequence to generate map.json, initialize progress.json,
and produce a structured result with a human-readable summary.

Pipeline steps:
1. Walk source files
2. Parse each file with the appropriate language plugin
3. Resolve imports
4. Build the dependency graph
5. Detect entry points and classify layers
6. Compute three-pass reading order
7. Enrich with complexity data
8. Compute content hashes
9. Write map.json
10. Initialize progress.json
11. Format summary
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from nlv.analysis import compute_complexity, detect_entry_point
from nlv.config import ReadingConfig, load_config
from nlv.graph import DependencyGraph, build_graph
from nlv.hashing import compute_content_hashes
from nlv.layers import Layer, LayerClassification, classify_layers
from nlv.output import write_map_json
from nlv.plugins import ParseResult, PluginRegistry
from nlv.plugins.go import GoPlugin
from nlv.plugins.python import PythonPlugin
from nlv.plugins.typescript import TypeScriptPlugin
from nlv.progress import ProgressManager
from nlv.refresh import RefreshResult, refresh_progress
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

    # Load reading config from .codebase-guide/ if present
    guide_dir = root / _GUIDE_DIR_NAME
    config = load_config(guide_dir)

    # Set up plugin registry
    registry = _setup_registry()
    extensions = registry.get_supported_extensions()

    # Walk source files
    source_files = walk_tree(root, extensions=extensions)

    # Parse and resolve
    if source_files:
        parse_results, resolved_imports = _parse_and_resolve(
            root, source_files, registry,
        )
    else:
        parse_results = {}
        resolved_imports = {}

    # Build dependency graph
    graph = build_graph(
        parse_results=parse_results,
        resolved_imports=resolved_imports,
    )

    # Detect entry points and classify layers
    entry_points = _detect_entry_points(root=root, graph=graph)
    classification = classify_layers(
        graph=graph,
        entry_points=entry_points,
        config=config,
    )

    # Compute reading order with complexity
    reading_order = _compute_order_with_complexity(
        root=root,
        graph=graph,
        classification=classification,
        parse_results=parse_results,
        config=config,
    )

    # Compute content hashes
    file_paths = [root / sf.path for sf in source_files]
    content_hashes = compute_content_hashes(file_paths, root=root)

    # Capture old content hashes before overwriting map.json
    guide_dir = root / _GUIDE_DIR_NAME
    old_content_hashes = _read_old_content_hashes(guide_dir)

    # Write map.json
    map_path = write_map_json(
        output_dir=guide_dir,
        repo_root=str(root),
        graph=graph,
        classification=classification,
        reading_order=reading_order,
        content_hashes=content_hashes,
    )

    # Initialize or refresh progress.json
    _init_progress(guide_dir, map_path, old_content_hashes)

    # Build result
    layer_counts = _count_layers(classification)
    summary = format_summary(
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
    registry.register(TypeScriptPlugin())
    registry.register(GoPlugin())
    return registry


def _parse_and_resolve(
    root: Path,
    source_files: list[SourceFile],
    registry: PluginRegistry,
) -> tuple[dict[str, ParseResult], dict[tuple[str, str], str]]:
    """Parse all source files and resolve their imports.

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

        for imp in result.imports:
            resolved = plugin.resolve_import(imp, abs_path)
            if resolved is not None:
                try:
                    rel = resolved.relative_to(root).as_posix()
                    resolved_imports[(sf.path, imp.source)] = rel
                except ValueError:
                    pass

    return parse_results, resolved_imports


def _detect_entry_points(
    *,
    root: Path,
    graph: DependencyGraph,
) -> set[str]:
    """Detect entry points for all files in the graph."""
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

    return entry_points


def _compute_order_with_complexity(
    *,
    root: Path,
    graph: DependencyGraph,
    classification: LayerClassification,
    parse_results: dict[str, ParseResult],
    config: ReadingConfig,
) -> tuple[ReadingOrderEntry, ...]:
    """Compute reading order, then enrich with complexity data."""
    base_order = compute_reading_order(
        graph=graph,
        classification=classification,
        parse_results=parse_results,
        config=config,
    )

    enriched: list[ReadingOrderEntry] = []
    for entry in base_order:
        abs_path = root / entry.path
        try:
            comp = compute_complexity(abs_path)
        except (FileNotFoundError, Exception):
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


def _read_old_content_hashes(guide_dir: Path) -> dict[str, str]:
    """Read content hashes from the existing map.json before it's overwritten.

    Args:
        guide_dir: Path to the .codebase-guide directory.

    Returns:
        Content hashes dict, or empty dict if no map.json exists.
    """
    map_path = guide_dir / "map.json"
    if not map_path.exists():
        return {}
    try:
        data = json.loads(map_path.read_text())
        result: dict[str, str] = data.get("content_hashes", {})
        return result
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read old map.json for hash comparison")
        return {}


def _init_progress(
    guide_dir: Path,
    map_path: Path,
    old_content_hashes: dict[str, str],
) -> None:
    """Initialize or refresh progress.json from the generated map.json.

    If progress.json does not exist, creates a fresh one. If it does
    exist, runs the refresh logic to preserve reading progress on
    unchanged files (BED-102).
    """
    map_content = map_path.read_text()
    map_data = json.loads(map_content)
    map_hash = hashlib.sha256(map_content.encode()).hexdigest()

    progress_path = guide_dir / "progress.json"
    if progress_path.exists():
        refresh_progress(
            guide_dir,
            map_data,
            map_hash,
            old_content_hashes=old_content_hashes,
        )
    else:
        mgr = ProgressManager(guide_dir)
        mgr.create(map_data, map_hash)


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


_LAYER_EXAMPLE_WORDS: dict[Layer, str] = {
    Layer.FOUNDATION: "config, constants, types",
    Layer.CORE: "models, services, data",
    Layer.FEATURES: "components, routes, hooks",
    Layer.INTEGRATION: "api, middleware, pipeline",
    Layer.ENTRY: "pages, app, main",
}


def format_summary(
    total_files: int,
    layer_counts: dict[Layer, int],
) -> str:
    """Format the human-readable summary shown after indexing.

    Follows the output format from SPEC.md.
    """
    if total_files == 0:
        return "Indexed 0 files. No supported source files found."

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
