"""Tests for map.json output writer (BED-74).

Covers: JSON structure, schema compliance, atomic writing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nlv.graph import DependencyGraph, FileNode
from nlv.layers import Layer, LayerClassification
from nlv.output import write_map_json
from nlv.reading_order import ReadingOrderEntry, ReadingPass

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _minimal_graph() -> DependencyGraph:
    """Build a minimal DependencyGraph for testing."""
    return DependencyGraph(
        nodes={
            "src/config.py": FileNode(
                path="src/config.py",
                imports=(),
                imported_by=("src/app.py",),
                fan_in=1,
                fan_out=0,
                depth=0,
                is_leaf=False,
                is_root=True,
            ),
            "src/app.py": FileNode(
                path="src/app.py",
                imports=("src/config.py",),
                imported_by=(),
                fan_in=0,
                fan_out=1,
                depth=1,
                is_leaf=True,
                is_root=False,
            ),
        },
        external_deps=(),
        cycles=(),
    )


def _minimal_classification() -> LayerClassification:
    """Build a minimal LayerClassification for testing."""
    return LayerClassification(
        layers={
            "src/config.py": Layer.FOUNDATION,
            "src/app.py": Layer.ENTRY,
        },
        layer_groups={
            Layer.FOUNDATION: ("src/config.py",),
            Layer.CORE: (),
            Layer.FEATURES: (),
            Layer.INTEGRATION: (),
            Layer.ENTRY: ("src/app.py",),
        },
    )


def _minimal_reading_order() -> tuple[ReadingOrderEntry, ...]:
    """Build a minimal reading order for testing."""
    return (
        ReadingOrderEntry(
            index=0,
            path="src/config.py",
            layer=Layer.FOUNDATION,
            reading_pass=ReadingPass.CONTRACTS,
            reason="No dependencies.",
            complexity="low",
            line_count=10,
            imports=(),
            imported_by=("src/app.py",),
            exports=("DB_URL",),
            paired_with=None,
        ),
        ReadingOrderEntry(
            index=1,
            path="src/app.py",
            layer=Layer.ENTRY,
            reading_pass=ReadingPass.DATA_FLOW,
            reason="Entry point.",
            complexity="low",
            line_count=20,
            imports=("src/config.py",),
            imported_by=(),
            exports=(),
            paired_with=None,
        ),
    )


def _minimal_content_hashes() -> dict[str, str]:
    """Build minimal content hashes for testing."""
    return {
        "src/config.py": "a3f2b8c1",
        "src/app.py": "d4e5f6a7",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWriteMapJson:
    """Tests for write_map_json output."""

    def test_writes_file(self, tmp_path: Path) -> None:
        """write_map_json creates the map.json file."""
        output_path = tmp_path / ".codebase-guide" / "map.json"
        write_map_json(
            output_path=output_path,
            repo_root=tmp_path,
            graph=_minimal_graph(),
            classification=_minimal_classification(),
            reading_order=_minimal_reading_order(),
            content_hashes=_minimal_content_hashes(),
        )
        assert output_path.exists()

    def test_valid_json(self, tmp_path: Path) -> None:
        """Output is valid JSON."""
        output_path = tmp_path / ".codebase-guide" / "map.json"
        write_map_json(
            output_path=output_path,
            repo_root=tmp_path,
            graph=_minimal_graph(),
            classification=_minimal_classification(),
            reading_order=_minimal_reading_order(),
            content_hashes=_minimal_content_hashes(),
        )
        data: dict[str, Any] = json.loads(output_path.read_text())
        assert isinstance(data, dict)

    def test_has_required_top_level_fields(self, tmp_path: Path) -> None:
        """map.json has all required top-level fields per SPEC.md."""
        output_path = tmp_path / ".codebase-guide" / "map.json"
        write_map_json(
            output_path=output_path,
            repo_root=tmp_path,
            graph=_minimal_graph(),
            classification=_minimal_classification(),
            reading_order=_minimal_reading_order(),
            content_hashes=_minimal_content_hashes(),
        )
        data = json.loads(output_path.read_text())
        required = {
            "version",
            "repo_root",
            "generated_at",
            "content_hashes",
            "total_files",
            "layers",
            "reading_order",
            "dependency_graph",
        }
        assert required.issubset(set(data.keys()))

    def test_layers_structure(self, tmp_path: Path) -> None:
        """Each layer has description and files list."""
        output_path = tmp_path / ".codebase-guide" / "map.json"
        write_map_json(
            output_path=output_path,
            repo_root=tmp_path,
            graph=_minimal_graph(),
            classification=_minimal_classification(),
            reading_order=_minimal_reading_order(),
            content_hashes=_minimal_content_hashes(),
        )
        data = json.loads(output_path.read_text())
        for _layer_name, layer_data in data["layers"].items():
            assert "description" in layer_data
            assert "files" in layer_data
            assert isinstance(layer_data["files"], list)

    def test_reading_order_entries(self, tmp_path: Path) -> None:
        """Each reading order entry has required fields."""
        output_path = tmp_path / ".codebase-guide" / "map.json"
        write_map_json(
            output_path=output_path,
            repo_root=tmp_path,
            graph=_minimal_graph(),
            classification=_minimal_classification(),
            reading_order=_minimal_reading_order(),
            content_hashes=_minimal_content_hashes(),
        )
        data = json.loads(output_path.read_text())
        for entry in data["reading_order"]:
            assert "index" in entry
            assert "path" in entry
            assert "layer" in entry
            assert "reason" in entry
            assert "complexity" in entry
            assert "line_count" in entry
            assert "imports" in entry
            assert "imported_by" in entry
            assert "exports" in entry

    def test_dependency_graph_structure(self, tmp_path: Path) -> None:
        """Each dependency graph entry has imports and imported_by."""
        output_path = tmp_path / ".codebase-guide" / "map.json"
        write_map_json(
            output_path=output_path,
            repo_root=tmp_path,
            graph=_minimal_graph(),
            classification=_minimal_classification(),
            reading_order=_minimal_reading_order(),
            content_hashes=_minimal_content_hashes(),
        )
        data = json.loads(output_path.read_text())
        for _path, node_data in data["dependency_graph"].items():
            assert "imports" in node_data
            assert "imported_by" in node_data

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        """write_map_json creates the parent directory if missing."""
        output_path = tmp_path / "nested" / "dir" / "map.json"
        write_map_json(
            output_path=output_path,
            repo_root=tmp_path,
            graph=_minimal_graph(),
            classification=_minimal_classification(),
            reading_order=_minimal_reading_order(),
            content_hashes=_minimal_content_hashes(),
        )
        assert output_path.exists()
