"""Tests for the language plugin architecture (BED-62).

Tests the plugin interface (Protocol), data types (ImportRef, ExportRef,
FunctionRef, ParseResult), and the plugin registry with auto-detection.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nlv.plugins import (
    ExportKind,
    ExportRef,
    FunctionRef,
    ImportRef,
    LanguagePlugin,
    ParseResult,
    PluginRegistry,
)

# ---------------------------------------------------------------------------
# Fake plugin for testing the Protocol contract
# ---------------------------------------------------------------------------


class FakePythonPlugin:
    """A minimal plugin that satisfies the LanguagePlugin protocol."""

    @property
    def name(self) -> str:
        return "python"

    @property
    def extensions(self) -> list[str]:
        return [".py", ".pyi"]

    def parse_file(self, path: Path) -> ParseResult:
        return ParseResult(imports=[], exports=[], functions=[], entry_point=False)

    def resolve_import(self, import_ref: ImportRef, from_file: Path) -> Path | None:
        return None


class FakeTypeScriptPlugin:
    """Another minimal plugin for testing multi-plugin registry."""

    @property
    def name(self) -> str:
        return "typescript"

    @property
    def extensions(self) -> list[str]:
        return [".ts", ".tsx", ".js", ".jsx"]

    def parse_file(self, path: Path) -> ParseResult:
        return ParseResult(imports=[], exports=[], functions=[], entry_point=False)

    def resolve_import(self, import_ref: ImportRef, from_file: Path) -> Path | None:
        return None


class IncompletePlugin:
    """Plugin missing required methods — should NOT satisfy the protocol."""

    @property
    def name(self) -> str:
        return "broken"


# ---------------------------------------------------------------------------
# Data type tests
# ---------------------------------------------------------------------------


class TestImportRef:
    """Tests for the ImportRef dataclass."""

    def test_create_relative_import(self) -> None:
        ref = ImportRef(source=".utils", specifiers=["helper"], is_relative=True)
        assert ref.source == ".utils"
        assert ref.specifiers == ["helper"]
        assert ref.is_relative is True

    def test_create_absolute_import(self) -> None:
        ref = ImportRef(
            source="os.path", specifiers=["join", "exists"], is_relative=False,
        )
        assert ref.source == "os.path"
        assert ref.specifiers == ["join", "exists"]
        assert ref.is_relative is False

    def test_empty_specifiers(self) -> None:
        ref = ImportRef(source="os", specifiers=[], is_relative=False)
        assert ref.specifiers == []

    def test_equality(self) -> None:
        a = ImportRef(source="os", specifiers=["path"], is_relative=False)
        b = ImportRef(source="os", specifiers=["path"], is_relative=False)
        assert a == b

    def test_inequality(self) -> None:
        a = ImportRef(source="os", specifiers=["path"], is_relative=False)
        b = ImportRef(source="sys", specifiers=["path"], is_relative=False)
        assert a != b


class TestExportRef:
    """Tests for the ExportRef dataclass."""

    def test_function_export(self) -> None:
        ref = ExportRef(name="main", kind=ExportKind.FUNCTION, line=10)
        assert ref.name == "main"
        assert ref.kind == ExportKind.FUNCTION
        assert ref.line == 10

    def test_class_export(self) -> None:
        ref = ExportRef(name="UserModel", kind=ExportKind.CLASS, line=25)
        assert ref.kind == ExportKind.CLASS

    def test_type_export(self) -> None:
        ref = ExportRef(name="Config", kind=ExportKind.TYPE, line=1)
        assert ref.kind == ExportKind.TYPE

    def test_variable_export(self) -> None:
        ref = ExportRef(name="VERSION", kind=ExportKind.VARIABLE, line=3)
        assert ref.kind == ExportKind.VARIABLE

    def test_default_export(self) -> None:
        ref = ExportRef(name="default", kind=ExportKind.DEFAULT, line=50)
        assert ref.kind == ExportKind.DEFAULT

    def test_all_export_kinds_exist(self) -> None:
        expected = {"FUNCTION", "CLASS", "TYPE", "VARIABLE", "DEFAULT"}
        actual = {k.name for k in ExportKind}
        assert actual == expected

    def test_equality(self) -> None:
        a = ExportRef(name="main", kind=ExportKind.FUNCTION, line=10)
        b = ExportRef(name="main", kind=ExportKind.FUNCTION, line=10)
        assert a == b


class TestFunctionRef:
    """Tests for the FunctionRef dataclass."""

    def test_create_function_ref(self) -> None:
        ref = FunctionRef(
            name="process", line=10, end_line=25, calls=["validate", "save"],
        )
        assert ref.name == "process"
        assert ref.line == 10
        assert ref.end_line == 25
        assert ref.calls == ["validate", "save"]

    def test_no_calls(self) -> None:
        ref = FunctionRef(name="noop", line=1, end_line=2, calls=[])
        assert ref.calls == []

    def test_equality(self) -> None:
        a = FunctionRef(name="f", line=1, end_line=5, calls=["g"])
        b = FunctionRef(name="f", line=1, end_line=5, calls=["g"])
        assert a == b


class TestParseResult:
    """Tests for the ParseResult dataclass."""

    def test_empty_result(self) -> None:
        result = ParseResult(imports=[], exports=[], functions=[], entry_point=False)
        assert result.imports == []
        assert result.exports == []
        assert result.functions == []
        assert result.entry_point is False

    def test_populated_result(self) -> None:
        imp = ImportRef(source="os", specifiers=["path"], is_relative=False)
        exp = ExportRef(name="main", kind=ExportKind.FUNCTION, line=10)
        func = FunctionRef(name="main", line=10, end_line=20, calls=["print"])
        result = ParseResult(
            imports=[imp],
            exports=[exp],
            functions=[func],
            entry_point=True,
        )
        assert len(result.imports) == 1
        assert len(result.exports) == 1
        assert len(result.functions) == 1
        assert result.entry_point is True

    def test_entry_point_detection(self) -> None:
        result = ParseResult(imports=[], exports=[], functions=[], entry_point=True)
        assert result.entry_point is True


# ---------------------------------------------------------------------------
# Protocol conformance tests
# ---------------------------------------------------------------------------


class TestLanguagePluginProtocol:
    """Tests that the LanguagePlugin protocol works correctly."""

    def test_fake_plugin_satisfies_protocol(self) -> None:
        plugin: LanguagePlugin = FakePythonPlugin()
        assert plugin.name == "python"
        assert ".py" in plugin.extensions

    def test_parse_file_returns_parse_result(self, tmp_path: Path) -> None:
        plugin: LanguagePlugin = FakePythonPlugin()
        result = plugin.parse_file(tmp_path / "test.py")
        assert isinstance(result, ParseResult)

    def test_resolve_import_returns_path_or_none(self, tmp_path: Path) -> None:
        plugin: LanguagePlugin = FakePythonPlugin()
        ref = ImportRef(source="os", specifiers=[], is_relative=False)
        result = plugin.resolve_import(ref, tmp_path / "test.py")
        assert result is None or isinstance(result, Path)

    def test_incomplete_plugin_does_not_satisfy_protocol(self) -> None:
        plugin = IncompletePlugin()
        assert not isinstance(plugin, LanguagePlugin)


# ---------------------------------------------------------------------------
# Plugin registry tests
# ---------------------------------------------------------------------------


class TestPluginRegistry:
    """Tests for the PluginRegistry."""

    def test_register_and_retrieve_plugin(self) -> None:
        registry = PluginRegistry()
        plugin = FakePythonPlugin()
        registry.register(plugin)
        assert registry.get_plugin_for_file(Path("main.py")) is plugin

    def test_get_plugin_for_unknown_extension_returns_none(self) -> None:
        registry = PluginRegistry()
        registry.register(FakePythonPlugin())
        assert registry.get_plugin_for_file(Path("data.csv")) is None

    def test_multiple_plugins_dispatch_correctly(self) -> None:
        registry = PluginRegistry()
        py_plugin = FakePythonPlugin()
        ts_plugin = FakeTypeScriptPlugin()
        registry.register(py_plugin)
        registry.register(ts_plugin)

        assert registry.get_plugin_for_file(Path("app.py")) is py_plugin
        assert registry.get_plugin_for_file(Path("app.ts")) is ts_plugin
        assert registry.get_plugin_for_file(Path("app.tsx")) is ts_plugin
        assert registry.get_plugin_for_file(Path("app.pyi")) is py_plugin

    def test_get_supported_extensions(self) -> None:
        registry = PluginRegistry()
        registry.register(FakePythonPlugin())
        registry.register(FakeTypeScriptPlugin())
        extensions = registry.get_supported_extensions()
        assert extensions == {".py", ".pyi", ".ts", ".tsx", ".js", ".jsx"}

    def test_empty_registry_returns_none(self) -> None:
        registry = PluginRegistry()
        assert registry.get_plugin_for_file(Path("main.py")) is None

    def test_empty_registry_has_no_extensions(self) -> None:
        registry = PluginRegistry()
        assert registry.get_supported_extensions() == set()

    def test_duplicate_extension_raises_error(self) -> None:
        registry = PluginRegistry()
        registry.register(FakePythonPlugin())
        with pytest.raises(ValueError, match=r"\.py"):
            registry.register(FakePythonPlugin())

    def test_get_plugin_by_name(self) -> None:
        registry = PluginRegistry()
        plugin = FakePythonPlugin()
        registry.register(plugin)
        assert registry.get_plugin_by_name("python") is plugin

    def test_get_plugin_by_name_unknown_returns_none(self) -> None:
        registry = PluginRegistry()
        assert registry.get_plugin_by_name("rust") is None

    def test_list_plugins(self) -> None:
        registry = PluginRegistry()
        py = FakePythonPlugin()
        ts = FakeTypeScriptPlugin()
        registry.register(py)
        registry.register(ts)
        plugins = registry.list_plugins()
        assert len(plugins) == 2
        assert py in plugins
        assert ts in plugins
