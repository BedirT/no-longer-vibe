"""Tests for the Go language plugin (BED-91).

Tests tree-sitter-based parsing, import extraction, export extraction
(capitalized = exported), function/method declarations, type declarations,
call relationships, and import resolution with go.mod awareness.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nlv.plugins import (
    ExportKind,
    ImportRef,
    LanguagePlugin,
    ParseResult,
    PluginRegistry,
)
from nlv.plugins.go import GoPlugin

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def plugin() -> GoPlugin:
    """Return a fresh GoPlugin instance."""
    return GoPlugin()


@pytest.fixture()
def go_project(tmp_path: Path) -> Path:
    """Create a minimal Go project for resolution tests.

    Layout::

        go.mod  (module github.com/example/myproject)
        main.go
        internal/
            config/
                config.go
            util/
                helpers.go
    """
    (tmp_path / "go.mod").write_text(
        "module github.com/example/myproject\n\ngo 1.21\n"
    )
    (tmp_path / "main.go").write_text(
        'package main\n\n'
        'import (\n'
        '    "fmt"\n'
        '    "github.com/example/myproject/internal/config"\n'
        ')\n\n'
        'func main() {\n'
        '    cfg := config.Load()\n'
        '    fmt.Println(cfg)\n'
        '}\n'
    )

    config_dir = tmp_path / "internal" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "config.go").write_text(
        "package config\n\n"
        "type Config struct {\n"
        "    Port string\n"
        "}\n\n"
        "func Load() *Config {\n"
        '    return &Config{Port: "8080"}\n'
        "}\n"
    )

    util_dir = tmp_path / "internal" / "util"
    util_dir.mkdir(parents=True)
    (util_dir / "helpers.go").write_text(
        "package util\n\n"
        "func FormatName(name string) string {\n"
        "    return name\n"
        "}\n"
    )

    return tmp_path


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """Verify GoPlugin satisfies the LanguagePlugin protocol."""

    def test_satisfies_protocol(self, plugin: GoPlugin) -> None:
        assert isinstance(plugin, LanguagePlugin)

    def test_name(self, plugin: GoPlugin) -> None:
        assert plugin.name == "go"

    def test_extensions(self, plugin: GoPlugin) -> None:
        exts = plugin.extensions
        assert ".go" in exts

    def test_registers_in_registry(self, plugin: GoPlugin) -> None:
        registry = PluginRegistry()
        registry.register(plugin)
        assert registry.get_plugin_for_file(Path("main.go")) is plugin


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------


class TestImportExtraction:
    """Tests for extracting import statements from Go files."""

    def test_single_import(self, plugin: GoPlugin, tmp_path: Path) -> None:
        """Extract `import "fmt"`."""
        f = tmp_path / "a.go"
        f.write_text('package main\n\nimport "fmt"\n\nfunc main() {}\n')
        result = plugin.parse_file(f)
        expected = ImportRef(source="fmt", specifiers=(), is_relative=False)
        assert expected in result.imports

    def test_grouped_imports(self, plugin: GoPlugin) -> None:
        """Extract grouped imports from fixture."""
        result = plugin.parse_file(FIXTURES / "grouped_imports.go")
        sources = {ref.source for ref in result.imports}
        assert "fmt" in sources
        assert "net/http" in sources
        assert "os" in sources
        assert "github.com/example/myproject/internal/config" in sources
        assert "github.com/gorilla/mux" in sources

    def test_named_import(self, plugin: GoPlugin) -> None:
        """Extract named/aliased imports."""
        result = plugin.parse_file(FIXTURES / "named_imports.go")
        # Find the aliased import: mylog "log"
        log_imports = [
            ref for ref in result.imports if ref.source == "log"
        ]
        assert len(log_imports) == 1
        assert log_imports[0].specifiers == ("mylog",)

    def test_dot_import(self, plugin: GoPlugin) -> None:
        """Extract dot import: . "strings"."""
        result = plugin.parse_file(FIXTURES / "named_imports.go")
        str_imports = [
            ref for ref in result.imports if ref.source == "strings"
        ]
        assert len(str_imports) == 1
        assert str_imports[0].specifiers == (".",)

    def test_blank_import(self, plugin: GoPlugin) -> None:
        """Extract blank import: _ "net/http/pprof"."""
        result = plugin.parse_file(FIXTURES / "named_imports.go")
        pprof_imports = [
            ref for ref in result.imports if ref.source == "net/http/pprof"
        ]
        assert len(pprof_imports) == 1
        assert pprof_imports[0].specifiers == ("_",)

    def test_import_count(self, plugin: GoPlugin) -> None:
        """All imports from grouped_imports.go are captured."""
        result = plugin.parse_file(FIXTURES / "grouped_imports.go")
        assert len(result.imports) == 5

    def test_imports_sorted_for_determinism(
        self, plugin: GoPlugin, tmp_path: Path,
    ) -> None:
        """Import results are sorted by source for deterministic output."""
        f = tmp_path / "a.go"
        f.write_text(
            'package main\n\n'
            'import (\n'
            '    "os"\n'
            '    "fmt"\n'
            '    "net/http"\n'
            ')\n\n'
            'func main() {}\n'
        )
        result = plugin.parse_file(f)
        sources = [ref.source for ref in result.imports]
        assert sources == sorted(sources)


# ---------------------------------------------------------------------------
# Export extraction (capitalized = exported in Go)
# ---------------------------------------------------------------------------


class TestExportExtraction:
    """Tests for extracting exported symbols (capitalized names)."""

    def test_exported_function(self, plugin: GoPlugin) -> None:
        """Capitalized functions are exports."""
        result = plugin.parse_file(FIXTURES / "exports.go")
        names = {e.name for e in result.exports}
        assert "NewUser" in names

    def test_unexported_function_not_in_exports(
        self, plugin: GoPlugin,
    ) -> None:
        """Lowercase functions are NOT exports."""
        result = plugin.parse_file(FIXTURES / "exports.go")
        names = {e.name for e in result.exports}
        assert "validate" not in names

    def test_exported_struct(self, plugin: GoPlugin) -> None:
        """Exported struct types are exports with CLASS kind."""
        result = plugin.parse_file(FIXTURES / "exports.go")
        user_exports = [
            e for e in result.exports
            if e.name == "User"
        ]
        assert len(user_exports) == 1
        assert user_exports[0].kind == ExportKind.CLASS

    def test_unexported_struct_not_exported(self, plugin: GoPlugin) -> None:
        """Unexported struct types are not exports."""
        result = plugin.parse_file(FIXTURES / "exports.go")
        names = {e.name for e in result.exports}
        assert "cache" not in names

    def test_exported_interface(self, plugin: GoPlugin) -> None:
        """Exported interfaces are exports with TYPE kind."""
        result = plugin.parse_file(FIXTURES / "exports.go")
        repo_exports = [
            e for e in result.exports
            if e.name == "Repository"
        ]
        assert len(repo_exports) == 1
        assert repo_exports[0].kind == ExportKind.TYPE

    def test_exported_const(self, plugin: GoPlugin) -> None:
        """Exported constants are exports with VARIABLE kind."""
        result = plugin.parse_file(FIXTURES / "exports.go")
        names = {e.name for e in result.exports}
        assert "MaxRetries" in names

    def test_unexported_const_not_exported(self, plugin: GoPlugin) -> None:
        """Unexported constants are not exports."""
        result = plugin.parse_file(FIXTURES / "exports.go")
        names = {e.name for e in result.exports}
        assert "defaultTimeout" not in names

    def test_exported_var(self, plugin: GoPlugin) -> None:
        """Exported variables are exports."""
        result = plugin.parse_file(FIXTURES / "exports.go")
        names = {e.name for e in result.exports}
        assert "Version" in names

    def test_unexported_var_not_exported(self, plugin: GoPlugin) -> None:
        """Unexported variables are not exports."""
        result = plugin.parse_file(FIXTURES / "exports.go")
        names = {e.name for e in result.exports}
        assert "internal" not in names

    def test_exported_method(self, plugin: GoPlugin) -> None:
        """Exported methods on exported types are exports."""
        result = plugin.parse_file(FIXTURES / "exports.go")
        names = {e.name for e in result.exports}
        assert "User.FullName" in names

    def test_unexported_method_not_exported(self, plugin: GoPlugin) -> None:
        """Unexported methods are not exports."""
        result = plugin.parse_file(FIXTURES / "exports.go")
        names = {e.name for e in result.exports}
        assert "cache.get" not in names

    def test_init_not_exported(self, plugin: GoPlugin) -> None:
        """init() functions are not exports."""
        result = plugin.parse_file(FIXTURES / "exports.go")
        names = {e.name for e in result.exports}
        assert "init" not in names

    def test_const_block_exports(self, plugin: GoPlugin) -> None:
        """Exported constants from const blocks are captured."""
        result = plugin.parse_file(FIXTURES / "interfaces.go")
        names = {e.name for e in result.exports}
        assert "StatusOK" in names
        assert "StatusError" in names

    def test_var_block_exports(self, plugin: GoPlugin) -> None:
        """Exported variables from var blocks are captured."""
        result = plugin.parse_file(FIXTURES / "interfaces.go")
        names = {e.name for e in result.exports}
        assert "DefaultReader" in names
        assert "internalState" not in names

    def test_type_alias_export(self, plugin: GoPlugin) -> None:
        """Type aliases (func types) are exported."""
        result = plugin.parse_file(FIXTURES / "interfaces.go")
        names = {e.name for e in result.exports}
        assert "HandlerFunc" in names


# ---------------------------------------------------------------------------
# Function/method extraction
# ---------------------------------------------------------------------------


class TestFunctionExtraction:
    """Tests for extracting function declarations and call relationships."""

    def test_simple_function(self, plugin: GoPlugin) -> None:
        """Simple function declarations are captured."""
        result = plugin.parse_file(FIXTURES / "simple.go")
        names = {fn.name for fn in result.functions}
        assert "main" in names

    def test_function_line_range(
        self, plugin: GoPlugin, tmp_path: Path,
    ) -> None:
        """Function line and end_line are captured."""
        f = tmp_path / "a.go"
        f.write_text(
            "package main\n\n"
            "func greet(name string) string {\n"
            "    return name\n"
            "}\n"
        )
        result = plugin.parse_file(f)
        func = next(fn for fn in result.functions if fn.name == "greet")
        assert func.line == 3
        assert func.end_line == 5

    def test_method_with_receiver(self, plugin: GoPlugin) -> None:
        """Methods with receivers use 'Receiver.Method' naming."""
        result = plugin.parse_file(FIXTURES / "methods.go")
        names = {fn.name for fn in result.functions}
        assert "Service.Run" in names
        assert "Service.process" in names
        assert "Service.String" in names

    def test_function_calls_extracted(self, plugin: GoPlugin) -> None:
        """Function/method calls within a function body are captured."""
        result = plugin.parse_file(FIXTURES / "methods.go")
        run_fn = next(
            fn for fn in result.functions if fn.name == "Service.Run"
        )
        assert "s.db.Query" in run_fn.calls or "db.Query" in run_fn.calls
        assert "s.process" in run_fn.calls

    def test_init_function(self, plugin: GoPlugin) -> None:
        """init() functions are captured in the function list."""
        result = plugin.parse_file(FIXTURES / "exports.go")
        names = {fn.name for fn in result.functions}
        assert "init" in names

    def test_calls_sorted_and_deduped(
        self, plugin: GoPlugin, tmp_path: Path,
    ) -> None:
        """Calls are sorted and deduplicated for determinism."""
        f = tmp_path / "a.go"
        f.write_text(
            "package main\n\n"
            "func run() {\n"
            "    save()\n"
            "    validate()\n"
            "    save()\n"
            "}\n\n"
            "func save() {}\n"
            "func validate() {}\n"
        )
        result = plugin.parse_file(f)
        func = next(fn for fn in result.functions if fn.name == "run")
        assert func.calls == ("save", "validate")

    def test_standalone_function(self, plugin: GoPlugin) -> None:
        """Non-method functions have no receiver prefix."""
        result = plugin.parse_file(FIXTURES / "methods.go")
        names = {fn.name for fn in result.functions}
        assert "NewService" in names

    def test_multiple_interfaces_functions(self, plugin: GoPlugin) -> None:
        """Interface files have no function declarations (only type specs)."""
        result = plugin.parse_file(FIXTURES / "interfaces.go")
        # interfaces.go has no func declarations, only type specs
        assert len(result.functions) == 0


# ---------------------------------------------------------------------------
# Entry point detection
# ---------------------------------------------------------------------------


class TestEntryPointDetection:
    """Tests for detecting Go entry points."""

    def test_main_func_in_main_package(self, plugin: GoPlugin) -> None:
        """package main with func main() is an entry point."""
        result = plugin.parse_file(FIXTURES / "simple.go")
        assert result.entry_point is True

    def test_non_main_package(self, plugin: GoPlugin) -> None:
        """Non-main packages are not entry points."""
        result = plugin.parse_file(FIXTURES / "exports.go")
        assert result.entry_point is False

    def test_main_package_without_main_func(
        self, plugin: GoPlugin, tmp_path: Path,
    ) -> None:
        """package main without func main() is not an entry point."""
        f = tmp_path / "helper.go"
        f.write_text("package main\n\nfunc helper() {}\n")
        result = plugin.parse_file(f)
        assert result.entry_point is False


# ---------------------------------------------------------------------------
# Import resolution
# ---------------------------------------------------------------------------


class TestImportResolution:
    """Tests for resolving Go imports with go.mod awareness."""

    def test_stdlib_returns_none(
        self, plugin: GoPlugin, go_project: Path,
    ) -> None:
        """Standard library imports return None."""
        ref = ImportRef(source="fmt", specifiers=(), is_relative=False)
        from_file = go_project / "main.go"
        resolved = plugin.resolve_import(ref, from_file)
        assert resolved is None

    def test_stdlib_subpackage_returns_none(
        self, plugin: GoPlugin, go_project: Path,
    ) -> None:
        """Standard library sub-packages return None."""
        ref = ImportRef(source="net/http", specifiers=(), is_relative=False)
        from_file = go_project / "main.go"
        resolved = plugin.resolve_import(ref, from_file)
        assert resolved is None

    def test_local_import_resolves(
        self, plugin: GoPlugin, go_project: Path,
    ) -> None:
        """Module-relative imports resolve to the local directory."""
        ref = ImportRef(
            source="github.com/example/myproject/internal/config",
            specifiers=(),
            is_relative=False,
        )
        from_file = go_project / "main.go"
        resolved = plugin.resolve_import(ref, from_file)
        assert resolved is not None
        assert resolved == go_project / "internal" / "config"

    def test_third_party_returns_none(
        self, plugin: GoPlugin, go_project: Path,
    ) -> None:
        """Third-party imports (not in go.mod module path) return None."""
        ref = ImportRef(
            source="github.com/gorilla/mux",
            specifiers=(),
            is_relative=False,
        )
        from_file = go_project / "main.go"
        resolved = plugin.resolve_import(ref, from_file)
        assert resolved is None

    def test_no_gomod_all_external(
        self, plugin: GoPlugin, tmp_path: Path,
    ) -> None:
        """Without go.mod, all non-stdlib imports return None."""
        f = tmp_path / "a.go"
        f.write_text(
            'package main\n\nimport "github.com/some/pkg"\n\nfunc main() {}\n'
        )
        ref = ImportRef(
            source="github.com/some/pkg",
            specifiers=(),
            is_relative=False,
        )
        resolved = plugin.resolve_import(ref, f)
        assert resolved is None

    def test_local_import_nested_path(
        self, plugin: GoPlugin, go_project: Path,
    ) -> None:
        """Module-relative imports at deeper nesting resolve correctly."""
        ref = ImportRef(
            source="github.com/example/myproject/internal/util",
            specifiers=(),
            is_relative=False,
        )
        from_file = go_project / "internal" / "config" / "config.go"
        resolved = plugin.resolve_import(ref, from_file)
        assert resolved is not None
        assert resolved == go_project / "internal" / "util"


# ---------------------------------------------------------------------------
# Test files
# ---------------------------------------------------------------------------


class TestGoTestFiles:
    """Tests that _test.go files are parsed normally."""

    def test_test_file_parsed(self, plugin: GoPlugin) -> None:
        """Test files (*_test.go) should still be parsed."""
        result = plugin.parse_file(FIXTURES / "sample_test.go")
        assert isinstance(result, ParseResult)

    def test_test_file_imports(self, plugin: GoPlugin) -> None:
        """Test file imports are captured."""
        result = plugin.parse_file(FIXTURES / "sample_test.go")
        sources = {ref.source for ref in result.imports}
        assert "testing" in sources

    def test_test_functions_captured(self, plugin: GoPlugin) -> None:
        """Test functions are captured in the function list."""
        result = plugin.parse_file(FIXTURES / "sample_test.go")
        names = {fn.name for fn in result.functions}
        assert "TestNewService" in names
        assert "TestServiceRun" in names


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_file(self, plugin: GoPlugin, tmp_path: Path) -> None:
        """Files with only a package clause parse to minimal results."""
        f = tmp_path / "empty.go"
        f.write_text("package empty\n")
        result = plugin.parse_file(f)
        assert result.imports == ()
        assert result.exports == ()
        assert result.functions == ()
        assert result.entry_point is False

    def test_file_not_found(self, plugin: GoPlugin, tmp_path: Path) -> None:
        """Nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            plugin.parse_file(tmp_path / "nonexistent.go")

    def test_parse_is_deterministic(
        self, plugin: GoPlugin,
    ) -> None:
        """Parsing the same file twice produces identical results."""
        r1 = plugin.parse_file(FIXTURES / "exports.go")
        r2 = plugin.parse_file(FIXTURES / "exports.go")
        assert r1 == r2

    def test_syntax_error_file(
        self, plugin: GoPlugin, tmp_path: Path,
    ) -> None:
        """Files with syntax errors return best-effort results (no crash)."""
        f = tmp_path / "bad.go"
        f.write_text("package main\n\nfunc broken( {\n}\n")
        result = plugin.parse_file(f)
        # tree-sitter is error-tolerant, so we get a result
        assert isinstance(result, ParseResult)

    def test_encoding_utf8(
        self, plugin: GoPlugin, tmp_path: Path,
    ) -> None:
        """UTF-8 files parse correctly."""
        f = tmp_path / "a.go"
        f.write_text(
            "package main\n\n"
            "// Greet says hello\n"
            "func Greet() string {\n"
            '    return "Hallo Welt"\n'
            "}\n"
        )
        result = plugin.parse_file(f)
        names = {fn.name for fn in result.functions}
        assert "Greet" in names

    def test_can_handle_go_extension(self, plugin: GoPlugin) -> None:
        """can_handle returns True for .go files, False otherwise."""
        assert ".go" in plugin.extensions
        assert ".py" not in plugin.extensions
        assert ".js" not in plugin.extensions
