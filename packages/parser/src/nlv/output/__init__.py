"""map.json generation (BED-70).

Assembles all parser outputs into the final ``.codebase-guide/map.json``
file matching the schema from SPEC.md. All file paths in the output use
POSIX forward slashes relative to repo_root.

The output is deterministic: sorted keys, sorted file lists, and stable
ordering ensure that the same inputs always produce the same JSON
(modulo ``generated_at``).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from nlv.graph import DependencyGraph
from nlv.layers import Layer, LayerClassification
from nlv.reading_order import ReadingOrderEntry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAP_VERSION = "1.0.0"
_MAP_FILENAME = "map.json"
_JSON_INDENT = 2

# Layer descriptions matching the SPEC.md schema.
_LAYER_DESCRIPTIONS: dict[Layer, str] = {
    Layer.FOUNDATION: "No or minimal internal dependencies",
    Layer.CORE: "Depends only on foundation",
    Layer.FEATURES: "Business logic, depends on core",
    Layer.INTEGRATION: "Composes features, middleware, API routes",
    Layer.ENTRY: "App entry points, page-level composition",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_map_json(
    *,
    repo_root: str,
    graph: DependencyGraph,
    classification: LayerClassification,
    reading_order: tuple[ReadingOrderEntry, ...],
    content_hashes: dict[str, str],
) -> dict[str, object]:
    """Assemble all parser outputs into the map.json dict.

    Args:
        repo_root: Absolute path to the repository root.
        graph: The dependency graph.
        classification: Layer classification for every file.
        reading_order: Tuple of ReadingOrderEntry in reading order.
        content_hashes: Mapping of relative file paths to SHA-256 hashes.

    Returns:
        A dict matching the map.json schema, ready for JSON serialization.
        Keys are sorted for deterministic output.
    """
    return {
        "content_hashes": dict(sorted(content_hashes.items())),
        "dependency_graph": _build_dependency_graph(graph),
        "generated_at": _utc_timestamp(),
        "layers": _build_layers(classification),
        "reading_order": _build_reading_order(reading_order),
        "repo_root": repo_root,
        "total_files": len(graph.nodes),
        "version": _MAP_VERSION,
    }


def write_map_json(
    *,
    output_dir: Path,
    repo_root: str,
    graph: DependencyGraph,
    classification: LayerClassification,
    reading_order: tuple[ReadingOrderEntry, ...],
    content_hashes: dict[str, str],
) -> Path:
    """Generate map.json and write it to disk.

    Creates the output directory if it does not exist. Overwrites any
    existing map.json file.

    Args:
        output_dir: Path to the ``.codebase-guide/`` directory.
        repo_root: Absolute path to the repository root.
        graph: The dependency graph.
        classification: Layer classification for every file.
        reading_order: Tuple of ReadingOrderEntry in reading order.
        content_hashes: Mapping of relative file paths to SHA-256 hashes.

    Returns:
        Path to the written map.json file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    data = generate_map_json(
        repo_root=repo_root,
        graph=graph,
        classification=classification,
        reading_order=reading_order,
        content_hashes=content_hashes,
    )

    map_path = output_dir / _MAP_FILENAME
    map_path.write_text(
        json.dumps(data, indent=_JSON_INDENT, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    logger.info("Wrote %s (%d files)", map_path, len(graph.nodes))
    return map_path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utc_timestamp() -> str:
    """Return the current UTC time as an ISO 8601 string ending in 'Z'."""
    now = datetime.now(tz=timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_layers(
    classification: LayerClassification,
) -> dict[str, dict[str, object]]:
    """Build the ``layers`` section of map.json.

    All five layers are always present, even if empty.
    """
    result: dict[str, dict[str, object]] = {}
    for layer in Layer:
        files = classification.layer_groups.get(layer, ())
        result[layer.value] = {
            "description": _LAYER_DESCRIPTIONS[layer],
            "files": sorted(files),
        }
    return result


def _build_reading_order(
    reading_order: tuple[ReadingOrderEntry, ...],
) -> list[dict[str, object]]:
    """Build the ``reading_order`` section of map.json."""
    return [_entry_to_dict(entry) for entry in reading_order]


def _entry_to_dict(entry: ReadingOrderEntry) -> dict[str, object]:
    """Convert a ReadingOrderEntry to a JSON-serializable dict."""
    return {
        "complexity": entry.complexity,
        "exports": list(entry.exports),
        "imported_by": list(entry.imported_by),
        "imports": list(entry.imports),
        "index": entry.index,
        "layer": entry.layer.value,
        "line_count": entry.line_count,
        "path": entry.path,
        "reason": entry.reason,
    }


def _build_dependency_graph(
    graph: DependencyGraph,
) -> dict[str, dict[str, list[str]]]:
    """Build the ``dependency_graph`` section of map.json."""
    result: dict[str, dict[str, list[str]]] = {}
    for path in sorted(graph.nodes):
        node = graph.nodes[path]
        result[path] = {
            "imported_by": list(node.imported_by),
            "imports": list(node.imports),
        }
    return result
