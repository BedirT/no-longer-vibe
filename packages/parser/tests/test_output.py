"""Tests for map.json output generation (BED-70)."""

from __future__ import annotations

import json
from pathlib import Path

from nlv.graph import DependencyGraph, FileNode
from nlv.layers import Layer, LayerClassification
from nlv.output import generate_map_json, write_map_json
from nlv.reading_order import ReadingOrderEntry, ReadingPass

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_file_node(
    path: str,
    *,
    imports: tuple[str, ...] = (),
    imported_by: tuple[str, ...] = (),
    depth: int = 0,
) -> FileNode:
    """Create a FileNode for testing."""
    return FileNode(
        path=path,
        imports=imports,
        imported_by=imported_by,
        fan_in=len(imported_by),
        fan_out=len(imports),
        depth=depth,
        is_leaf=(len(imported_by) == 0),
        is_root=(len(imports) == 0),
    )


def _make_graph(nodes: dict[str, FileNode]) -> DependencyGraph:
    """Create a DependencyGraph for testing."""
    return DependencyGraph(
        nodes=nodes,
        external_deps=(),
        cycles=(),
    )


def _make_classification(
    layers: dict[str, Layer],
) -> LayerClassification:
    """Create a LayerClassification for testing."""
    layer_groups: dict[Layer, list[str]] = {layer: [] for layer in Layer}
    for path, layer in sorted(layers.items()):
        layer_groups[layer].append(path)
    return LayerClassification(
        layers=layers,
        layer_groups={k: tuple(v) for k, v in layer_groups.items()},
    )


def _make_reading_order_entry(
    *,
    index: int,
    path: str,
    layer: Layer = Layer.FOUNDATION,
    reading_pass: ReadingPass = ReadingPass.CONTRACTS,
    reason: str = "Test reason.",
    complexity: str = "low",
    line_count: int = 10,
    imports: tuple[str, ...] = (),
    imported_by: tuple[str, ...] = (),
    exports: tuple[str, ...] = (),
    paired_with: str | None = None,
) -> ReadingOrderEntry:
    """Create a ReadingOrderEntry for testing."""
    return ReadingOrderEntry(
        index=index,
        path=path,
        layer=layer,
        reading_pass=reading_pass,
        reason=reason,
        complexity=complexity,
        line_count=line_count,
        imports=imports,
        imported_by=imported_by,
        exports=exports,
        paired_with=paired_with,
    )


# ---------------------------------------------------------------------------
# Tests: generate_map_json
# ---------------------------------------------------------------------------


class TestGenerateMapJson:
    """Tests for the generate_map_json function."""

    def test_returns_dict_with_required_keys(self) -> None:
        """Output dict contains all top-level keys from the schema."""
        node = _make_file_node("src/config.py")
        graph = _make_graph({"src/config.py": node})
        classification = _make_classification(
            {"src/config.py": Layer.FOUNDATION},
        )
        reading_order = (
            _make_reading_order_entry(
                index=0,
                path="src/config.py",
                exports=("AppConfig",),
            ),
        )
        content_hashes = {"src/config.py": "a3f2b8c1"}

        result = generate_map_json(
            repo_root="/path/to/repo",
            graph=graph,
            classification=classification,
            reading_order=reading_order,
            content_hashes=content_hashes,
        )

        assert "version" in result
        assert "repo_root" in result
        assert "generated_at" in result
        assert "content_hashes" in result
        assert "total_files" in result
        assert "layers" in result
        assert "reading_order" in result
        assert "dependency_graph" in result

    def test_version_is_1_0_0(self) -> None:
        """Version field matches the spec."""
        graph = _make_graph({})
        classification = _make_classification({})
        result = generate_map_json(
            repo_root="/repo",
            graph=graph,
            classification=classification,
            reading_order=(),
            content_hashes={},
        )
        assert result["version"] == "1.0.0"

    def test_repo_root_passthrough(self) -> None:
        """repo_root is passed through as-is."""
        graph = _make_graph({})
        classification = _make_classification({})
        result = generate_map_json(
            repo_root="/my/project",
            graph=graph,
            classification=classification,
            reading_order=(),
            content_hashes={},
        )
        assert result["repo_root"] == "/my/project"

    def test_generated_at_is_iso8601_utc(self) -> None:
        """generated_at is a valid ISO 8601 UTC timestamp."""
        from datetime import datetime, timezone

        graph = _make_graph({})
        classification = _make_classification({})
        result = generate_map_json(
            repo_root="/repo",
            graph=graph,
            classification=classification,
            reading_order=(),
            content_hashes={},
        )
        ts = result["generated_at"]
        assert isinstance(ts, str)
        # Must end with Z (UTC)
        assert ts.endswith("Z")
        # Must be parseable
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None
        assert parsed.tzinfo == timezone.utc

    def test_total_files_counts_all_graph_nodes(self) -> None:
        """total_files equals the number of nodes in the graph."""
        nodes = {
            "a.py": _make_file_node("a.py"),
            "b.py": _make_file_node("b.py"),
            "c.py": _make_file_node("c.py"),
        }
        graph = _make_graph(nodes)
        classification = _make_classification({
            "a.py": Layer.FOUNDATION,
            "b.py": Layer.CORE,
            "c.py": Layer.FEATURES,
        })
        result = generate_map_json(
            repo_root="/repo",
            graph=graph,
            classification=classification,
            reading_order=(),
            content_hashes={},
        )
        assert result["total_files"] == 3

    def test_content_hashes_passthrough(self) -> None:
        """content_hashes are passed through directly."""
        graph = _make_graph({})
        classification = _make_classification({})
        hashes = {"src/a.py": "abcd1234", "src/b.py": "efgh5678"}
        result = generate_map_json(
            repo_root="/repo",
            graph=graph,
            classification=classification,
            reading_order=(),
            content_hashes=hashes,
        )
        assert result["content_hashes"] == hashes

    def test_layers_structure(self) -> None:
        """Layers section has all five layers with description and files."""
        nodes = {
            "config.py": _make_file_node("config.py"),
            "models.py": _make_file_node(
                "models.py", imports=("config.py",), depth=1,
            ),
        }
        graph = _make_graph(nodes)
        classification = _make_classification({
            "config.py": Layer.FOUNDATION,
            "models.py": Layer.CORE,
        })
        result = generate_map_json(
            repo_root="/repo",
            graph=graph,
            classification=classification,
            reading_order=(),
            content_hashes={},
        )

        layers = result["layers"]
        # All five layers present
        assert "foundation" in layers
        assert "core" in layers
        assert "features" in layers
        assert "integration" in layers
        assert "entry" in layers

        # Each layer has description and files
        for layer_data in layers.values():
            assert "description" in layer_data
            assert "files" in layer_data
            assert isinstance(layer_data["description"], str)
            assert isinstance(layer_data["files"], list)

        # Correct files in correct layers
        assert "config.py" in layers["foundation"]["files"]
        assert "models.py" in layers["core"]["files"]

    def test_empty_layers_present(self) -> None:
        """Even layers with no files are present with empty file lists."""
        graph = _make_graph({
            "a.py": _make_file_node("a.py"),
        })
        classification = _make_classification({"a.py": Layer.FOUNDATION})
        result = generate_map_json(
            repo_root="/repo",
            graph=graph,
            classification=classification,
            reading_order=(),
            content_hashes={},
        )
        layers = result["layers"]
        assert layers["core"]["files"] == []
        assert layers["features"]["files"] == []
        assert layers["integration"]["files"] == []
        assert layers["entry"]["files"] == []

    def test_reading_order_entries(self) -> None:
        """Reading order entries match the schema."""
        entry = _make_reading_order_entry(
            index=0,
            path="src/config.py",
            layer=Layer.FOUNDATION,
            reading_pass=ReadingPass.CONTRACTS,
            reason="No dependencies. Defines core config.",
            complexity="low",
            line_count=45,
            imports=(),
            imported_by=("src/models.py",),
            exports=("AppConfig", "getConfig"),
        )
        graph = _make_graph({
            "src/config.py": _make_file_node(
                "src/config.py",
                imported_by=("src/models.py",),
            ),
        })
        classification = _make_classification(
            {"src/config.py": Layer.FOUNDATION},
        )
        result = generate_map_json(
            repo_root="/repo",
            graph=graph,
            classification=classification,
            reading_order=(entry,),
            content_hashes={},
        )

        ro = result["reading_order"]
        assert len(ro) == 1
        item = ro[0]
        assert item["index"] == 0
        assert item["path"] == "src/config.py"
        assert item["layer"] == "foundation"
        assert item["reason"] == "No dependencies. Defines core config."
        assert item["complexity"] == "low"
        assert item["line_count"] == 45
        assert item["imports"] == []
        assert item["imported_by"] == ["src/models.py"]
        assert item["exports"] == ["AppConfig", "getConfig"]

    def test_dependency_graph_section(self) -> None:
        """Dependency graph section matches the schema."""
        nodes = {
            "a.py": _make_file_node(
                "a.py",
                imported_by=("b.py",),
            ),
            "b.py": _make_file_node(
                "b.py",
                imports=("a.py",),
                depth=1,
            ),
        }
        graph = _make_graph(nodes)
        classification = _make_classification({
            "a.py": Layer.FOUNDATION,
            "b.py": Layer.CORE,
        })
        result = generate_map_json(
            repo_root="/repo",
            graph=graph,
            classification=classification,
            reading_order=(),
            content_hashes={},
        )

        dep_graph = result["dependency_graph"]
        assert "a.py" in dep_graph
        assert "b.py" in dep_graph
        assert dep_graph["a.py"]["imports"] == []
        assert dep_graph["a.py"]["imported_by"] == ["b.py"]
        assert dep_graph["b.py"]["imports"] == ["a.py"]
        assert dep_graph["b.py"]["imported_by"] == []

    def test_deterministic_output(self) -> None:
        """Same inputs produce the same output (excluding generated_at)."""
        nodes = {
            "c.py": _make_file_node("c.py", imported_by=("a.py",)),
            "a.py": _make_file_node("a.py", imports=("c.py",)),
            "b.py": _make_file_node("b.py"),
        }
        graph = _make_graph(nodes)
        classification = _make_classification({
            "a.py": Layer.CORE,
            "b.py": Layer.FOUNDATION,
            "c.py": Layer.FOUNDATION,
        })
        hashes = {"c.py": "11111111", "a.py": "22222222", "b.py": "33333333"}
        reading_order = (
            _make_reading_order_entry(index=0, path="b.py"),
            _make_reading_order_entry(index=1, path="c.py"),
            _make_reading_order_entry(index=2, path="a.py", layer=Layer.CORE),
        )

        result1 = generate_map_json(
            repo_root="/repo",
            graph=graph,
            classification=classification,
            reading_order=reading_order,
            content_hashes=hashes,
        )
        result2 = generate_map_json(
            repo_root="/repo",
            graph=graph,
            classification=classification,
            reading_order=reading_order,
            content_hashes=hashes,
        )

        # Exclude generated_at for comparison
        result1.pop("generated_at")
        result2.pop("generated_at")
        assert result1 == result2

    def test_json_serializable(self) -> None:
        """Output is fully JSON-serializable."""
        node = _make_file_node("x.py")
        graph = _make_graph({"x.py": node})
        classification = _make_classification({"x.py": Layer.FOUNDATION})
        entry = _make_reading_order_entry(index=0, path="x.py")
        result = generate_map_json(
            repo_root="/repo",
            graph=graph,
            classification=classification,
            reading_order=(entry,),
            content_hashes={"x.py": "aabbccdd"},
        )
        # Must not raise
        serialized = json.dumps(result, sort_keys=True)
        assert isinstance(serialized, str)
        # Round-trip
        deserialized = json.loads(serialized)
        # Exclude generated_at for comparison
        result.pop("generated_at")
        deserialized.pop("generated_at")
        assert result == deserialized

    def test_empty_graph(self) -> None:
        """Works with empty graph and no files."""
        graph = _make_graph({})
        classification = _make_classification({})
        result = generate_map_json(
            repo_root="/repo",
            graph=graph,
            classification=classification,
            reading_order=(),
            content_hashes={},
        )
        assert result["total_files"] == 0
        assert result["reading_order"] == []
        assert result["dependency_graph"] == {}
        assert result["content_hashes"] == {}

    def test_dependency_graph_keys_sorted(self) -> None:
        """Dependency graph keys are in sorted order."""
        nodes = {
            "z.py": _make_file_node("z.py"),
            "a.py": _make_file_node("a.py"),
            "m.py": _make_file_node("m.py"),
        }
        graph = _make_graph(nodes)
        classification = _make_classification({
            "z.py": Layer.FOUNDATION,
            "a.py": Layer.FOUNDATION,
            "m.py": Layer.FOUNDATION,
        })
        result = generate_map_json(
            repo_root="/repo",
            graph=graph,
            classification=classification,
            reading_order=(),
            content_hashes={},
        )
        keys = list(result["dependency_graph"].keys())
        assert keys == sorted(keys)

    def test_layer_files_sorted(self) -> None:
        """Files within each layer are sorted alphabetically."""
        nodes = {
            "z.py": _make_file_node("z.py"),
            "a.py": _make_file_node("a.py"),
            "m.py": _make_file_node("m.py"),
        }
        graph = _make_graph(nodes)
        classification = _make_classification({
            "z.py": Layer.FOUNDATION,
            "a.py": Layer.FOUNDATION,
            "m.py": Layer.FOUNDATION,
        })
        result = generate_map_json(
            repo_root="/repo",
            graph=graph,
            classification=classification,
            reading_order=(),
            content_hashes={},
        )
        files = result["layers"]["foundation"]["files"]
        assert files == sorted(files)


# ---------------------------------------------------------------------------
# Tests: write_map_json
# ---------------------------------------------------------------------------


class TestWriteMapJson:
    """Tests for writing map.json to disk."""

    def test_creates_output_directory(self, tmp_path: Path) -> None:
        """Creates .codebase-guide/ directory if it doesn't exist."""
        output_dir = tmp_path / ".codebase-guide"
        assert not output_dir.exists()

        graph = _make_graph({})
        classification = _make_classification({})
        write_map_json(
            output_dir=output_dir,
            repo_root=str(tmp_path),
            graph=graph,
            classification=classification,
            reading_order=(),
            content_hashes={},
        )

        assert output_dir.exists()
        assert output_dir.is_dir()

    def test_writes_valid_json_file(self, tmp_path: Path) -> None:
        """Writes a valid JSON file to the output directory."""
        output_dir = tmp_path / ".codebase-guide"
        node = _make_file_node("x.py")
        graph = _make_graph({"x.py": node})
        classification = _make_classification({"x.py": Layer.FOUNDATION})

        write_map_json(
            output_dir=output_dir,
            repo_root=str(tmp_path),
            graph=graph,
            classification=classification,
            reading_order=(),
            content_hashes={"x.py": "aabbccdd"},
        )

        map_file = output_dir / "map.json"
        assert map_file.exists()

        data = json.loads(map_file.read_text(encoding="utf-8"))
        assert data["version"] == "1.0.0"
        assert data["total_files"] == 1

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        """Overwrites an existing map.json."""
        output_dir = tmp_path / ".codebase-guide"
        output_dir.mkdir(parents=True)
        (output_dir / "map.json").write_text('{"old": true}')

        graph = _make_graph({})
        classification = _make_classification({})
        write_map_json(
            output_dir=output_dir,
            repo_root=str(tmp_path),
            graph=graph,
            classification=classification,
            reading_order=(),
            content_hashes={},
        )

        data = json.loads(
            (output_dir / "map.json").read_text(encoding="utf-8"),
        )
        assert "old" not in data
        assert data["version"] == "1.0.0"

    def test_returns_path_to_written_file(self, tmp_path: Path) -> None:
        """Returns the path to the written map.json file."""
        output_dir = tmp_path / ".codebase-guide"
        graph = _make_graph({})
        classification = _make_classification({})
        result_path = write_map_json(
            output_dir=output_dir,
            repo_root=str(tmp_path),
            graph=graph,
            classification=classification,
            reading_order=(),
            content_hashes={},
        )

        assert result_path == output_dir / "map.json"
        assert result_path.exists()

    def test_json_has_sorted_keys(self, tmp_path: Path) -> None:
        """Written JSON uses sorted keys for determinism."""
        output_dir = tmp_path / ".codebase-guide"
        graph = _make_graph({})
        classification = _make_classification({})
        write_map_json(
            output_dir=output_dir,
            repo_root=str(tmp_path),
            graph=graph,
            classification=classification,
            reading_order=(),
            content_hashes={},
        )

        raw = (output_dir / "map.json").read_text(encoding="utf-8")
        data = json.loads(raw)
        # Top-level keys should be in sorted order in the file
        keys = list(data.keys())
        assert keys == sorted(keys)

    def test_json_has_indent(self, tmp_path: Path) -> None:
        """Written JSON is indented (pretty-printed) for readability."""
        output_dir = tmp_path / ".codebase-guide"
        graph = _make_graph({})
        classification = _make_classification({})
        write_map_json(
            output_dir=output_dir,
            repo_root=str(tmp_path),
            graph=graph,
            classification=classification,
            reading_order=(),
            content_hashes={},
        )

        raw = (output_dir / "map.json").read_text(encoding="utf-8")
        # Pretty-printed JSON has newlines
        assert "\n" in raw
        # And indentation
        assert "  " in raw

    def test_full_roundtrip(self, tmp_path: Path) -> None:
        """Full roundtrip: generate, write, read back, validate schema."""
        nodes = {
            "src/config.py": _make_file_node(
                "src/config.py",
                imported_by=("src/models.py",),
            ),
            "src/models.py": _make_file_node(
                "src/models.py",
                imports=("src/config.py",),
                depth=1,
            ),
        }
        graph = _make_graph(nodes)
        classification = _make_classification({
            "src/config.py": Layer.FOUNDATION,
            "src/models.py": Layer.CORE,
        })
        reading_order = (
            _make_reading_order_entry(
                index=0,
                path="src/config.py",
                exports=("AppConfig",),
                imported_by=("src/models.py",),
            ),
            _make_reading_order_entry(
                index=1,
                path="src/models.py",
                layer=Layer.CORE,
                reading_pass=ReadingPass.DATA_FLOW,
                imports=("src/config.py",),
                exports=("User",),
            ),
        )
        hashes = {"src/config.py": "a3f2b8c1", "src/models.py": "d4e5f6a7"}

        output_dir = tmp_path / ".codebase-guide"
        write_map_json(
            output_dir=output_dir,
            repo_root=str(tmp_path),
            graph=graph,
            classification=classification,
            reading_order=reading_order,
            content_hashes=hashes,
        )

        data = json.loads(
            (output_dir / "map.json").read_text(encoding="utf-8"),
        )

        # Top-level structure
        assert data["version"] == "1.0.0"
        assert data["repo_root"] == str(tmp_path)
        assert data["total_files"] == 2
        assert data["content_hashes"] == hashes

        # Layers
        assert "src/config.py" in data["layers"]["foundation"]["files"]
        assert "src/models.py" in data["layers"]["core"]["files"]

        # Reading order
        assert len(data["reading_order"]) == 2
        assert data["reading_order"][0]["path"] == "src/config.py"
        assert data["reading_order"][1]["path"] == "src/models.py"

        # Dependency graph
        assert data["dependency_graph"]["src/config.py"]["imports"] == []
        assert data["dependency_graph"]["src/config.py"]["imported_by"] == [
            "src/models.py",
        ]
        assert data["dependency_graph"]["src/models.py"]["imports"] == [
            "src/config.py",
        ]

    def test_ends_with_newline(self, tmp_path: Path) -> None:
        """Written JSON file ends with a trailing newline."""
        output_dir = tmp_path / ".codebase-guide"
        graph = _make_graph({})
        classification = _make_classification({})
        write_map_json(
            output_dir=output_dir,
            repo_root=str(tmp_path),
            graph=graph,
            classification=classification,
            reading_order=(),
            content_hashes={},
        )

        raw = (output_dir / "map.json").read_text(encoding="utf-8")
        assert raw.endswith("\n")
