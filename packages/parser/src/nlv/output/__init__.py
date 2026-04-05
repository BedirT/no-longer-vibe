"""map.json generation — write the codebase map to disk.

Serialises the dependency graph, layer classification, reading order,
and content hashes into `.codebase-guide/map.json` following the schema
defined in SPEC.md.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from nlv.graph import DependencyGraph
from nlv.layers import Layer, LayerClassification
from nlv.reading_order import ReadingOrderEntry

logger = logging.getLogger(__name__)

_VERSION = "1.0.0"

_LAYER_DESCRIPTIONS: dict[Layer, str] = {
    Layer.FOUNDATION: "No or minimal internal dependencies",
    Layer.CORE: "Depends only on foundation",
    Layer.FEATURES: "Business logic, depends on core",
    Layer.INTEGRATION: "Composes features, middleware, API routes",
    Layer.ENTRY: "App entry points, page-level composition",
}


def write_map_json(
    *,
    output_path: Path,
    repo_root: Path,
    graph: DependencyGraph,
    classification: LayerClassification,
    reading_order: tuple[ReadingOrderEntry, ...],
    content_hashes: dict[str, str],
) -> None:
    """Write the codebase map to a JSON file.

    Creates the parent directory if it does not exist. Writes
    atomically via a temporary file + rename.

    Args:
        output_path: Path to write map.json.
        repo_root: Absolute path to the repository root.
        graph: The dependency graph.
        classification: Layer classification for every file.
        reading_order: Computed reading order entries.
        content_hashes: Mapping of relative path to 8-char hash.
    """
    data = _build_map_data(
        repo_root=repo_root,
        graph=graph,
        classification=classification,
        reading_order=reading_order,
        content_hashes=content_hashes,
    )
    _atomic_write_json(output_path, data)


def _build_map_data(
    *,
    repo_root: Path,
    graph: DependencyGraph,
    classification: LayerClassification,
    reading_order: tuple[ReadingOrderEntry, ...],
    content_hashes: dict[str, str],
) -> dict[str, object]:
    """Assemble the map.json dict from components."""
    return {
        "version": _VERSION,
        "repo_root": str(repo_root.resolve()),
        "generated_at": _now_iso(),
        "content_hashes": content_hashes,
        "total_files": len(reading_order),
        "layers": _serialize_layers(classification),
        "reading_order": _serialize_reading_order(reading_order),
        "dependency_graph": _serialize_graph(graph),
    }


def _serialize_layers(
    classification: LayerClassification,
) -> dict[str, object]:
    """Serialize layer classification to dict."""
    result: dict[str, object] = {}
    for layer in Layer:
        files = list(classification.layer_groups.get(layer, ()))
        result[layer.value] = {
            "description": _LAYER_DESCRIPTIONS[layer],
            "files": files,
        }
    return result


def _serialize_reading_order(
    reading_order: tuple[ReadingOrderEntry, ...],
) -> list[dict[str, object]]:
    """Serialize reading order entries to a list of dicts."""
    entries: list[dict[str, object]] = []
    for entry in reading_order:
        entries.append({
            "index": entry.index,
            "path": entry.path,
            "layer": entry.layer.value,
            "reason": entry.reason,
            "complexity": entry.complexity,
            "line_count": entry.line_count,
            "imports": list(entry.imports),
            "imported_by": list(entry.imported_by),
            "exports": list(entry.exports),
        })
    return entries


def _serialize_graph(graph: DependencyGraph) -> dict[str, object]:
    """Serialize the dependency graph to dict."""
    result: dict[str, object] = {}
    for path in sorted(graph.nodes):
        node = graph.nodes[path]
        result[path] = {
            "imports": list(node.imports),
            "imported_by": list(node.imported_by),
        }
    return result


def _atomic_write_json(path: Path, data: dict[str, object]) -> None:
    """Atomically write JSON data to a file.

    Creates the parent directory, writes to a temp file with
    fsync, then renames.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path_str = tempfile.mkstemp(
        suffix=".tmp", dir=path.parent,
    )
    tmp_path = Path(tmp_path_str)
    try:
        with open(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        tmp_path.replace(path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
