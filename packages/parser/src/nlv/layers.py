"""Layer classifier — assign files to architectural layers (BED-65).

Classifies each file into one of five layers based on its position in the
dependency graph:

- **foundation**: No or minimal internal dependencies (depth 0).
- **core**: Depends only on foundation (depth 1).
- **features**: Business logic, depends on core (depth 2, or depth 3+ with low fanIn).
- **integration**: Composes features, high fanIn (depth 3+ with high fanIn).
- **entry**: App entry points.

The algorithm is deterministic: same graph always produces the same
classification.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import AbstractSet

from nlv.graph import DependencyGraph

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum fan_in to qualify as an "integration" node at depth 3+.
# Below this threshold, depth 3+ files stay in "features".
_INTEGRATION_FAN_IN_THRESHOLD = 3

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class Layer(enum.Enum):
    """Architectural layer for a source file."""

    FOUNDATION = "foundation"
    CORE = "core"
    FEATURES = "features"
    INTEGRATION = "integration"
    ENTRY = "entry"


@dataclass(frozen=True)
class LayerClassification:
    """Result of classifying files into layers.

    Attributes:
        layers: Mapping of file path to its assigned Layer.
        layer_groups: Mapping of Layer to sorted tuple of file paths
            in that layer. All five layers are always present.
    """

    layers: dict[str, Layer]
    layer_groups: dict[Layer, tuple[str, ...]]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_layers(
    *,
    graph: DependencyGraph,
    entry_points: AbstractSet[str],
) -> LayerClassification:
    """Classify every file in the graph into an architectural layer.

    Args:
        graph: The dependency graph (from ``build_graph``).
        entry_points: Set of file paths identified as entry points
            (from ``detect_entry_point`` or other heuristics).

    Returns:
        A LayerClassification with per-file layers and grouped output.
    """
    layers: dict[str, Layer] = {}

    for path in sorted(graph.nodes):
        layers[path] = _classify_file(
            path=path,
            graph=graph,
            entry_points=entry_points,
        )

    layer_groups = _build_layer_groups(layers)

    return LayerClassification(layers=layers, layer_groups=layer_groups)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _classify_file(
    *,
    path: str,
    graph: DependencyGraph,
    entry_points: AbstractSet[str],
) -> Layer:
    """Classify a single file into a layer.

    Priority:
    1. Entry points -> ENTRY (overrides depth-based classification).
    2. Depth 0 -> FOUNDATION
    3. Depth 1 -> CORE
    4. Depth 2 -> FEATURES
    5. Depth 3+ with high fanIn -> INTEGRATION
    6. Depth 3+ with low fanIn -> FEATURES (bias toward deeper layer)
    """
    # Entry points always override
    if path in entry_points:
        return Layer.ENTRY

    node = graph.nodes[path]
    return _layer_from_depth_and_fan_in(depth=node.depth, fan_in=node.fan_in)


def _layer_from_depth_and_fan_in(*, depth: int, fan_in: int) -> Layer:
    """Map depth and fan_in to a layer.

    Depth ranges:
    - 0 -> foundation
    - 1 -> core
    - 2 -> features
    - 3+ with high fanIn -> integration (composes features)
    - 3+ with low fanIn -> features (spec: bias toward deeper layer)
    """
    if depth == 0:
        return Layer.FOUNDATION
    if depth == 1:
        return Layer.CORE
    if depth == 2:
        return Layer.FEATURES
    # depth >= 3
    if fan_in >= _INTEGRATION_FAN_IN_THRESHOLD:
        return Layer.INTEGRATION
    return Layer.FEATURES


def _build_layer_groups(
    layers: dict[str, Layer],
) -> dict[Layer, tuple[str, ...]]:
    """Group files by their assigned layer.

    Returns a dict with all five Layer keys, each mapping to a sorted
    tuple of file paths. Empty layers get empty tuples.
    """
    groups: dict[Layer, list[str]] = {layer: [] for layer in Layer}
    for path, layer in sorted(layers.items()):
        groups[layer].append(path)
    return {layer: tuple(files) for layer, files in groups.items()}
