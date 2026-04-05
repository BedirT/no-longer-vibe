"""Layer classifier — assign files to architectural layers (BED-65, BED-92).

Classifies each file into one of five layers based on its position in the
dependency graph:

- **foundation**: No or minimal internal dependencies (depth 0).
- **core**: Depends only on foundation (depth 1).
- **features**: Business logic, depends on core (depth 2, or depth 3+ with low fanIn).
- **integration**: Composes features, high fanIn (depth 3+ with high fanIn).
- **entry**: App entry points.

The algorithm is deterministic: same graph always produces the same
classification.

BED-92 additions:
- Accepts an optional ``ReadingConfig`` for custom layer thresholds and
  integration fan_in threshold.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, AbstractSet

from nlv.graph import DependencyGraph

if TYPE_CHECKING:
    from nlv.config import ReadingConfig

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
    config: ReadingConfig | None = None,
) -> LayerClassification:
    """Classify every file in the graph into an architectural layer.

    Args:
        graph: The dependency graph (from ``build_graph``).
        entry_points: Set of file paths identified as entry points
            (from ``detect_entry_point`` or other heuristics).
        config: Optional reading configuration for custom thresholds.

    Returns:
        A LayerClassification with per-file layers and grouped output.
    """
    thresholds = _resolve_thresholds(config)
    fan_in_threshold = _resolve_fan_in_threshold(config)

    layers: dict[str, Layer] = {}

    for path in sorted(graph.nodes):
        layers[path] = _classify_file(
            path=path,
            graph=graph,
            entry_points=entry_points,
            thresholds=thresholds,
            fan_in_threshold=fan_in_threshold,
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
    thresholds: dict[str, int],
    fan_in_threshold: int,
) -> Layer:
    """Classify a single file into a layer.

    Priority:
    1. Entry points -> ENTRY (overrides depth-based classification).
    2. Depth-based classification using configurable thresholds.
    3. Depth >= integration threshold with high fanIn -> INTEGRATION
    4. Depth >= integration threshold with low fanIn -> FEATURES
    """
    # Entry points always override
    if path in entry_points:
        return Layer.ENTRY

    node = graph.nodes[path]
    return _layer_from_depth_and_fan_in(
        depth=node.depth,
        fan_in=node.fan_in,
        thresholds=thresholds,
        fan_in_threshold=fan_in_threshold,
    )


def _layer_from_depth_and_fan_in(
    *,
    depth: int,
    fan_in: int,
    thresholds: dict[str, int],
    fan_in_threshold: int,
) -> Layer:
    """Map depth and fan_in to a layer using configurable thresholds.

    Default depth ranges:
    - 0 -> foundation
    - 1 -> core
    - 2 -> features
    - 3+ with high fanIn -> integration (composes features)
    - 3+ with low fanIn -> features (spec: bias toward deeper layer)
    """
    foundation_depth = thresholds.get("foundation", 0)
    core_depth = thresholds.get("core", 1)
    integration_depth = thresholds.get("integration", 3)

    if depth <= foundation_depth:
        return Layer.FOUNDATION
    if depth <= core_depth:
        return Layer.CORE
    if depth < integration_depth:
        return Layer.FEATURES
    # depth >= integration threshold
    if fan_in >= fan_in_threshold:
        return Layer.INTEGRATION
    return Layer.FEATURES


def _resolve_thresholds(config: ReadingConfig | None) -> dict[str, int]:
    """Get layer thresholds from config or defaults."""
    if config is not None:
        return config.layer_thresholds
    return {
        "foundation": 0,
        "core": 1,
        "features": 2,
        "integration": 3,
    }


def _resolve_fan_in_threshold(config: ReadingConfig | None) -> int:
    """Get the integration fan_in threshold from config or default."""
    if config is not None:
        return config.integration_fan_in_threshold
    return _INTEGRATION_FAN_IN_THRESHOLD


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
