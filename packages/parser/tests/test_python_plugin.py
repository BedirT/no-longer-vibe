"""Tests for the Python language plugin (BED-63).

Tests AST-based parsing, import extraction, export extraction,
function/class declarations, call relationships, entry point detection,
and import resolution.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nlv.plugins import (
    ExportKind,
    ExportRef,
    ImportRef,
    LanguagePlugin,
    ParseResult,
    PluginRegistry,
)
from nlv.plugins.python import PythonPlugin

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def plugin() -> PythonPlugin:
    """Return a fresh PythonPlugin instance."""
    return PythonPlugin()


@pytest.fixture()
def py_project(tmp_path: Path) -> Path:
    """Create a minimal Python project for resolution tests."""
    pkg = tmp_path / "mypackage"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")

    (pkg / "config.py").write_text(
        "DB_URL = 'sqlite:///test.db'\n"
        "def get_config():\n"
        "    return {'db': DB_URL}\n"
    )

    sub = pkg / "utils"
    sub.mkdir()
    (sub / "__init__.py").write_text("from .helpers import format_name\n")
    (sub / "helpers.py").write_text("def format_name(name): return name.strip()\n")

    return tmp_path


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """Verify PythonPlugin satisfies the LanguagePlugin protocol."""

    def test_satisfies_protocol(self, plugin: PythonPlugin) -> None:
        assert isinstance(plugin, LanguagePlugin)

    def test_name(self, plugin: PythonPlugin) -> None:
        assert plugin.name == "python"

    def test_extensions(self, plugin: PythonPlugin) -> None:
        exts = plugin.extensions
        assert ".py" in exts
        assert ".pyi" in exts

    def test_registers_in_registry(self, plugin: PythonPlugin) -> None:
        registry = PluginRegistry()
        registry.register(plugin)
        assert registry.get_plugin_for_file(Path("main.py")) is plugin
        assert registry.get_plugin_for_file(Path("types.pyi")) is plugin


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------


class TestImportExtraction:
    """Tests for extracting import statements from Python files."""

    def test_import_module(self, plugin: PythonPlugin, tmp_path: Path) -> None:
        """Extract `import os`."""
        f = tmp_path / "a.py"
        f.write_text("import os\n")
        result = plugin.parse_file(f)
        expected = ImportRef(
            source="os", specifiers=(), is_relative=False,
        )
        assert expected in result.imports

    def test_import_dotted_module(self, plugin: PythonPlugin, tmp_path: Path) -> None:
        """Extract `import os.path`."""
        f = tmp_path / "a.py"
        f.write_text("import os.path\n")
        result = plugin.parse_file(f)
        assert ImportRef(
            source="os.path", specifiers=(), is_relative=False,
        ) in result.imports

    def test_from_import(self, plugin: PythonPlugin, tmp_path: Path) -> None:
        """Extract `from os.path import join, exists`."""
        f = tmp_path / "a.py"
        f.write_text("from os.path import join, exists\n")
        result = plugin.parse_file(f)
        assert ImportRef(
            source="os.path", specifiers=("exists", "join"), is_relative=False,
        ) in result.imports

    def test_relative_import_dot(self, plugin: PythonPlugin, tmp_path: Path) -> None:
        """Extract `from . import utils`."""
        f = tmp_path / "a.py"
        f.write_text("from . import utils\n")
        result = plugin.parse_file(f)
        assert ImportRef(
            source=".", specifiers=("utils",), is_relative=True,
        ) in result.imports

    def test_relative_import_dotdot(
        self, plugin: PythonPlugin, tmp_path: Path,
    ) -> None:
        """Extract `from ..utils import helper`."""
        f = tmp_path / "a.py"
        f.write_text("from ..utils import helper\n")
        result = plugin.parse_file(f)
        assert ImportRef(
            source="..utils", specifiers=("helper",), is_relative=True,
        ) in result.imports

    def test_multiple_imports(self, plugin: PythonPlugin, tmp_path: Path) -> None:
        """Multiple import statements are all captured."""
        f = tmp_path / "a.py"
        f.write_text("import os\nimport sys\nfrom pathlib import Path\n")
        result = plugin.parse_file(f)
        assert len(result.imports) == 3

    def test_star_import(self, plugin: PythonPlugin, tmp_path: Path) -> None:
        """Extract `from module import *`."""
        f = tmp_path / "a.py"
        f.write_text("from os.path import *\n")
        result = plugin.parse_file(f)
        assert ImportRef(
            source="os.path", specifiers=("*",), is_relative=False,
        ) in result.imports

    def test_conditional_import(self, plugin: PythonPlugin, tmp_path: Path) -> None:
        """Imports inside try/except are still extracted."""
        f = tmp_path / "a.py"
        f.write_text(
            "try:\n"
            "    import ujson as json\n"
            "except ImportError:\n"
            "    import json\n"
        )
        result = plugin.parse_file(f)
        sources = {ref.source for ref in result.imports}
        assert "ujson" in sources
        assert "json" in sources

    def test_import_specifiers_sorted(
        self, plugin: PythonPlugin, tmp_path: Path,
    ) -> None:
        """Specifiers within an import are sorted for determinism."""
        f = tmp_path / "a.py"
        f.write_text("from os.path import exists, join, abspath\n")
        result = plugin.parse_file(f)
        ref = result.imports[0]
        assert ref.specifiers == ("abspath", "exists", "join")

    def test_multi_name_import(self, plugin: PythonPlugin, tmp_path: Path) -> None:
        """Extract `import os, sys` as separate ImportRefs."""
        f = tmp_path / "a.py"
        f.write_text("import os, sys\n")
        result = plugin.parse_file(f)
        sources = {ref.source for ref in result.imports}
        assert "os" in sources
        assert "sys" in sources


# ---------------------------------------------------------------------------
# Export extraction
# ---------------------------------------------------------------------------


class TestExportExtraction:
    """Tests for extracting exported symbols from Python files."""

    def test_function_export(self, plugin: PythonPlugin, tmp_path: Path) -> None:
        """Module-level functions are exports."""
        f = tmp_path / "a.py"
        f.write_text("def hello():\n    pass\n")
        result = plugin.parse_file(f)
        assert ExportRef(
            name="hello", kind=ExportKind.FUNCTION, line=1,
        ) in result.exports

    def test_class_export(self, plugin: PythonPlugin, tmp_path: Path) -> None:
        """Module-level classes are exports."""
        f = tmp_path / "a.py"
        f.write_text("class MyClass:\n    pass\n")
        result = plugin.parse_file(f)
        assert ExportRef(
            name="MyClass", kind=ExportKind.CLASS, line=1,
        ) in result.exports

    def test_variable_export(self, plugin: PythonPlugin, tmp_path: Path) -> None:
        """Module-level variable assignments are exports."""
        f = tmp_path / "a.py"
        f.write_text("VERSION = '1.0'\n")
        result = plugin.parse_file(f)
        assert ExportRef(
            name="VERSION", kind=ExportKind.VARIABLE, line=1,
        ) in result.exports

    def test_dunder_all_restricts_exports(
        self, plugin: PythonPlugin, tmp_path: Path,
    ) -> None:
        """When __all__ is defined, only listed names are exported."""
        f = tmp_path / "a.py"
        f.write_text(
            "__all__ = ['public_func']\n\n"
            "def public_func():\n    pass\n\n"
            "def _private():\n    pass\n\n"
            "def unlisted():\n    pass\n"
        )
        result = plugin.parse_file(f)
        names = {e.name for e in result.exports}
        assert "public_func" in names
        assert "_private" not in names
        assert "unlisted" not in names

    def test_private_names_excluded(
        self, plugin: PythonPlugin, tmp_path: Path,
    ) -> None:
        """Names starting with _ are excluded when no __all__ is defined."""
        f = tmp_path / "a.py"
        f.write_text("def _private():\n    pass\n\ndef public():\n    pass\n")
        result = plugin.parse_file(f)
        names = {e.name for e in result.exports}
        assert "public" in names
        assert "_private" not in names

    def test_async_function_export(
        self, plugin: PythonPlugin, tmp_path: Path,
    ) -> None:
        """Async functions at module level are exports."""
        f = tmp_path / "a.py"
        f.write_text("async def fetch():\n    pass\n")
        result = plugin.parse_file(f)
        assert ExportRef(
            name="fetch", kind=ExportKind.FUNCTION, line=1,
        ) in result.exports

    def test_nested_function_not_exported(
        self, plugin: PythonPlugin, tmp_path: Path,
    ) -> None:
        """Functions defined inside other functions are not exports."""
        f = tmp_path / "a.py"
        f.write_text("def outer():\n    def inner():\n        pass\n")
        result = plugin.parse_file(f)
        names = {e.name for e in result.exports}
        assert "outer" in names
        assert "inner" not in names

    def test_type_alias_export(self, plugin: PythonPlugin, tmp_path: Path) -> None:
        """TypeAlias assignments are exports."""
        f = tmp_path / "a.py"
        f.write_text(
            "from typing import TypeAlias\n"
            "UserId: TypeAlias = int\n"
        )
        result = plugin.parse_file(f)
        names = {e.name for e in result.exports}
        assert "UserId" in names

    def test_multiple_assignment_targets(
        self, plugin: PythonPlugin, tmp_path: Path,
    ) -> None:
        """Multiple assignment targets export all simple names."""
        f = tmp_path / "a.py"
        f.write_text("X = Y = 42\n")
        result = plugin.parse_file(f)
        names = {e.name for e in result.exports}
        assert "X" in names
        assert "Y" in names


# ---------------------------------------------------------------------------
# Function/class declaration extraction
# ---------------------------------------------------------------------------


class TestFunctionExtraction:
    """Tests for extracting function declarations and call relationships."""

    def test_function_line_range(
        self, plugin: PythonPlugin, tmp_path: Path,
    ) -> None:
        """Function line and end_line are captured."""
        f = tmp_path / "a.py"
        f.write_text("def greet(name):\n    return f'Hello {name}'\n")
        result = plugin.parse_file(f)
        func = next(fn for fn in result.functions if fn.name == "greet")
        assert func.line == 1
        assert func.end_line == 2

    def test_function_calls_extracted(
        self, plugin: PythonPlugin, tmp_path: Path,
    ) -> None:
        """Function calls within a function body are captured."""
        f = tmp_path / "a.py"
        f.write_text(
            "def process():\n"
            "    validate()\n"
            "    save()\n"
        )
        result = plugin.parse_file(f)
        func = next(fn for fn in result.functions if fn.name == "process")
        assert "validate" in func.calls
        assert "save" in func.calls

    def test_method_calls_captured(
        self, plugin: PythonPlugin, tmp_path: Path,
    ) -> None:
        """Method calls like obj.method() are captured as 'obj.method'."""
        f = tmp_path / "a.py"
        f.write_text("def run():\n    db.query('SELECT 1')\n")
        result = plugin.parse_file(f)
        func = next(fn for fn in result.functions if fn.name == "run")
        assert "db.query" in func.calls

    def test_class_methods_extracted(
        self, plugin: PythonPlugin, tmp_path: Path,
    ) -> None:
        """Methods inside classes are extracted with qualified names."""
        f = tmp_path / "a.py"
        f.write_text(
            "class Service:\n"
            "    def start(self):\n"
            "        self.init()\n"
            "    def init(self):\n"
            "        pass\n"
        )
        result = plugin.parse_file(f)
        names = {fn.name for fn in result.functions}
        assert "Service.start" in names
        assert "Service.init" in names

    def test_calls_sorted_and_deduped(
        self, plugin: PythonPlugin, tmp_path: Path,
    ) -> None:
        """Calls are sorted and deduplicated for determinism."""
        f = tmp_path / "a.py"
        f.write_text(
            "def run():\n"
            "    save()\n"
            "    validate()\n"
            "    save()\n"
        )
        result = plugin.parse_file(f)
        func = next(fn for fn in result.functions if fn.name == "run")
        assert func.calls == ("save", "validate")

    def test_async_function_extracted(
        self, plugin: PythonPlugin, tmp_path: Path,
    ) -> None:
        """Async functions are extracted the same as regular functions."""
        f = tmp_path / "a.py"
        f.write_text("async def fetch():\n    await get()\n")
        result = plugin.parse_file(f)
        func = next(fn for fn in result.functions if fn.name == "fetch")
        assert func.line == 1
        assert "get" in func.calls

    def test_nested_function_extracted(
        self, plugin: PythonPlugin, tmp_path: Path,
    ) -> None:
        """Nested functions are extracted with qualified names."""
        f = tmp_path / "a.py"
        f.write_text(
            "def outer():\n"
            "    def inner():\n"
            "        pass\n"
            "    inner()\n"
        )
        result = plugin.parse_file(f)
        names = {fn.name for fn in result.functions}
        assert "outer" in names
        assert "outer.inner" in names


# ---------------------------------------------------------------------------
# Entry point detection
# ---------------------------------------------------------------------------


class TestEntryPointDetection:
    """Tests for detecting Python entry points."""

    def test_if_name_main(self, plugin: PythonPlugin, tmp_path: Path) -> None:
        """Files with `if __name__ == '__main__'` are entry points."""
        f = tmp_path / "a.py"
        f.write_text(
            "def main():\n    pass\n\n"
            "if __name__ == '__main__':\n    main()\n"
        )
        result = plugin.parse_file(f)
        assert result.entry_point is True

    def test_no_entry_point(self, plugin: PythonPlugin, tmp_path: Path) -> None:
        """Regular modules without __name__ guard are not entry points."""
        f = tmp_path / "a.py"
        f.write_text("def helper():\n    pass\n")
        result = plugin.parse_file(f)
        assert result.entry_point is False

    def test_main_py_is_entry_point(
        self, plugin: PythonPlugin, tmp_path: Path,
    ) -> None:
        """__main__.py files are entry points."""
        f = tmp_path / "__main__.py"
        f.write_text("print('hello')\n")
        result = plugin.parse_file(f)
        assert result.entry_point is True


# ---------------------------------------------------------------------------
# Import resolution
# ---------------------------------------------------------------------------


class TestImportResolution:
    """Tests for resolving imports to file paths."""

    def test_resolve_relative_import_single_dot(
        self, plugin: PythonPlugin, py_project: Path,
    ) -> None:
        """Resolve `from . import config` from a sibling module."""
        ref = ImportRef(source=".", specifiers=("config",), is_relative=True)
        # from_file is in mypackage/, so `.` resolves within mypackage/
        from_file = py_project / "mypackage" / "__init__.py"
        resolved = plugin.resolve_import(ref, from_file)
        assert resolved is not None
        assert resolved.name == "config.py"

    def test_resolve_relative_import_dotdot(
        self, plugin: PythonPlugin, py_project: Path,
    ) -> None:
        """Resolve `from ..config import DB_URL` from a subpackage."""
        ref = ImportRef(
            source="..config", specifiers=("DB_URL",), is_relative=True,
        )
        from_file = py_project / "mypackage" / "utils" / "helpers.py"
        resolved = plugin.resolve_import(ref, from_file)
        assert resolved is not None
        assert resolved.name == "config.py"

    def test_resolve_relative_import_package_init(
        self, plugin: PythonPlugin, py_project: Path,
    ) -> None:
        """Resolve `from . import utils` to utils/__init__.py."""
        ref = ImportRef(source=".", specifiers=("utils",), is_relative=True)
        from_file = py_project / "mypackage" / "config.py"
        resolved = plugin.resolve_import(ref, from_file)
        assert resolved is not None
        assert resolved.name == "__init__.py"

    def test_resolve_third_party_returns_none(
        self, plugin: PythonPlugin, py_project: Path,
    ) -> None:
        """Third-party imports that don't resolve on disk return None."""
        ref = ImportRef(source="numpy", specifiers=("array",), is_relative=False)
        from_file = py_project / "mypackage" / "config.py"
        resolved = plugin.resolve_import(ref, from_file)
        assert resolved is None

    def test_resolve_stdlib_returns_none(
        self, plugin: PythonPlugin, py_project: Path,
    ) -> None:
        """Standard library imports return None (not local files)."""
        ref = ImportRef(source="os.path", specifiers=("join",), is_relative=False)
        from_file = py_project / "mypackage" / "config.py"
        resolved = plugin.resolve_import(ref, from_file)
        assert resolved is None

    def test_resolve_sibling_module(
        self, plugin: PythonPlugin, py_project: Path,
    ) -> None:
        """Resolve `from .helpers import format_name` within subpackage."""
        ref = ImportRef(
            source=".helpers", specifiers=("format_name",), is_relative=True,
        )
        from_file = py_project / "mypackage" / "utils" / "__init__.py"
        resolved = plugin.resolve_import(ref, from_file)
        assert resolved is not None
        assert resolved.name == "helpers.py"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_file(self, plugin: PythonPlugin, tmp_path: Path) -> None:
        """Empty files parse to empty results."""
        f = tmp_path / "empty.py"
        f.write_text("")
        result = plugin.parse_file(f)
        assert result.imports == ()
        assert result.exports == ()
        assert result.functions == ()
        assert result.entry_point is False

    def test_syntax_error_file(self, plugin: PythonPlugin, tmp_path: Path) -> None:
        """Files with syntax errors return empty results (no crash)."""
        f = tmp_path / "bad.py"
        f.write_text("def broken(\n")
        result = plugin.parse_file(f)
        assert isinstance(result, ParseResult)
        assert result.imports == ()

    def test_file_not_found(self, plugin: PythonPlugin, tmp_path: Path) -> None:
        """Nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            plugin.parse_file(tmp_path / "nonexistent.py")

    def test_parse_is_deterministic(
        self, plugin: PythonPlugin, tmp_path: Path,
    ) -> None:
        """Parsing the same file twice produces identical results."""
        f = tmp_path / "a.py"
        f.write_text(
            "import os\nimport sys\n"
            "from pathlib import Path\n"
            "def main():\n    print('hello')\n"
            "class Config:\n    pass\n"
            "VERSION = '1.0'\n"
        )
        r1 = plugin.parse_file(f)
        r2 = plugin.parse_file(f)
        assert r1 == r2

    def test_dynamic_import_not_captured(
        self, plugin: PythonPlugin, tmp_path: Path,
    ) -> None:
        """Dynamic imports (importlib) are not captured as static imports."""
        f = tmp_path / "a.py"
        f.write_text("import importlib\nm = importlib.import_module('foo')\n")
        result = plugin.parse_file(f)
        sources = {ref.source for ref in result.imports}
        assert "foo" not in sources
        assert "importlib" in sources

    def test_encoding_utf8(self, plugin: PythonPlugin, tmp_path: Path) -> None:
        """UTF-8 files parse correctly."""
        f = tmp_path / "a.py"
        f.write_text("# -*- coding: utf-8 -*-\ndef grüße():\n    pass\n")
        result = plugin.parse_file(f)
        names = {fn.name for fn in result.functions}
        assert "grüße" in names

    def test_imports_sorted_for_determinism(
        self, plugin: PythonPlugin, tmp_path: Path,
    ) -> None:
        """Import results are sorted for deterministic output."""
        f = tmp_path / "a.py"
        f.write_text("import sys\nimport os\nimport pathlib\n")
        result = plugin.parse_file(f)
        sources = [ref.source for ref in result.imports]
        assert sources == sorted(sources)

    def test_decorators_do_not_affect_line_range(
        self, plugin: PythonPlugin, tmp_path: Path,
    ) -> None:
        """Function line starts at the def, not at decorators."""
        f = tmp_path / "a.py"
        f.write_text(
            "@decorator\n"
            "def func():\n"
            "    pass\n"
        )
        result = plugin.parse_file(f)
        func = next(fn for fn in result.functions if fn.name == "func")
        # The decorator is on line 1, def is on line 2
        assert func.line == 2
        assert func.end_line == 3
