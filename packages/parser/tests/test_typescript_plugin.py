"""Tests for the TypeScript/JavaScript language plugin (BED-90).

Tests tree-sitter-based parsing for TS/JS files: import extraction,
export extraction, function/class declarations, call relationships,
entry point detection, and import resolution.
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
from nlv.plugins.typescript import TypeScriptPlugin

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def plugin() -> TypeScriptPlugin:
    """Return a fresh TypeScriptPlugin instance."""
    return TypeScriptPlugin()


@pytest.fixture()
def ts_project(tmp_path: Path) -> Path:
    """Create a minimal TypeScript project for resolution tests."""
    src = tmp_path / "src"
    src.mkdir()

    (src / "config.ts").write_text(
        "export const DB_URL = 'sqlite:///test.db';\n"
        "export function getConfig() { return { db: DB_URL }; }\n"
    )

    utils = src / "utils"
    utils.mkdir()
    (utils / "index.ts").write_text(
        "export { formatName } from './helpers';\n"
    )
    (utils / "helpers.ts").write_text(
        "export function formatName(name: string) { return name.trim(); }\n"
    )

    # JS files for mixed project testing
    (src / "legacy.js").write_text(
        "const path = require('path');\n"
        "module.exports = { resolve: path.resolve };\n"
    )

    return tmp_path


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """Verify TypeScriptPlugin satisfies the LanguagePlugin protocol."""

    def test_satisfies_protocol(self, plugin: TypeScriptPlugin) -> None:
        assert isinstance(plugin, LanguagePlugin)

    def test_name(self, plugin: TypeScriptPlugin) -> None:
        assert plugin.name == "typescript"

    def test_extensions(self, plugin: TypeScriptPlugin) -> None:
        exts = plugin.extensions
        for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
            assert ext in exts

    def test_registers_in_registry(self, plugin: TypeScriptPlugin) -> None:
        registry = PluginRegistry()
        registry.register(plugin)
        assert registry.get_plugin_for_file(Path("app.ts")) is plugin
        assert registry.get_plugin_for_file(Path("app.tsx")) is plugin
        assert registry.get_plugin_for_file(Path("app.js")) is plugin
        assert registry.get_plugin_for_file(Path("app.jsx")) is plugin
        assert registry.get_plugin_for_file(Path("utils.mjs")) is plugin
        assert registry.get_plugin_for_file(Path("utils.cjs")) is plugin


# ---------------------------------------------------------------------------
# ES6 Import extraction
# ---------------------------------------------------------------------------


class TestES6ImportExtraction:
    """Tests for extracting ES6 import statements."""

    def test_named_import(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `import { foo, bar } from 'module'`."""
        f = tmp_path / "a.ts"
        f.write_text("import { foo, bar } from 'module';\n")
        result = plugin.parse_file(f)
        expected = ImportRef(
            source="module", specifiers=("bar", "foo"), is_relative=False,
        )
        assert expected in result.imports

    def test_default_import(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `import React from 'react'`."""
        f = tmp_path / "a.ts"
        f.write_text("import React from 'react';\n")
        result = plugin.parse_file(f)
        expected = ImportRef(
            source="react", specifiers=("React",), is_relative=False,
        )
        assert expected in result.imports

    def test_namespace_import(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `import * as ns from 'module'`."""
        f = tmp_path / "a.ts"
        f.write_text("import * as utils from './utils';\n")
        result = plugin.parse_file(f)
        expected = ImportRef(
            source="./utils", specifiers=("*",), is_relative=True,
        )
        assert expected in result.imports

    def test_side_effect_import(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `import 'side-effect'`."""
        f = tmp_path / "a.ts"
        f.write_text("import 'reflect-metadata';\n")
        result = plugin.parse_file(f)
        expected = ImportRef(
            source="reflect-metadata", specifiers=(), is_relative=False,
        )
        assert expected in result.imports

    def test_relative_import(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Relative imports are marked as is_relative=True."""
        f = tmp_path / "a.ts"
        f.write_text("import { helper } from './utils/helper';\n")
        result = plugin.parse_file(f)
        ref = result.imports[0]
        assert ref.is_relative is True
        assert ref.source == "./utils/helper"

    def test_parent_relative_import(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Parent relative imports (../) are detected."""
        f = tmp_path / "a.ts"
        f.write_text("import { config } from '../config';\n")
        result = plugin.parse_file(f)
        ref = result.imports[0]
        assert ref.is_relative is True
        assert ref.source == "../config"

    def test_multiple_imports(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Multiple import statements are all captured."""
        f = tmp_path / "a.ts"
        f.write_text(
            "import React from 'react';\n"
            "import { useState } from 'react';\n"
            "import './styles.css';\n"
        )
        result = plugin.parse_file(f)
        assert len(result.imports) == 3

    def test_import_specifiers_sorted(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Specifiers are sorted for determinism."""
        f = tmp_path / "a.ts"
        f.write_text("import { zeta, alpha, middle } from 'mod';\n")
        result = plugin.parse_file(f)
        ref = result.imports[0]
        assert ref.specifiers == ("alpha", "middle", "zeta")

    def test_aliased_import(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Import alias: `import { foo as bar } from 'mod'`."""
        f = tmp_path / "a.ts"
        f.write_text("import { foo as bar } from 'mod';\n")
        result = plugin.parse_file(f)
        ref = result.imports[0]
        # We track the original name, not the alias
        assert "foo" in ref.specifiers

    def test_default_and_named_import(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Mixed default + named: `import React, { useState } from 'react'`."""
        f = tmp_path / "a.ts"
        f.write_text("import React, { useState } from 'react';\n")
        result = plugin.parse_file(f)
        ref = result.imports[0]
        assert ref.source == "react"
        assert "React" in ref.specifiers
        assert "useState" in ref.specifiers


# ---------------------------------------------------------------------------
# CommonJS require
# ---------------------------------------------------------------------------


class TestCommonJSImport:
    """Tests for extracting CommonJS require() calls."""

    def test_const_require(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `const x = require('module')`."""
        f = tmp_path / "a.js"
        f.write_text("const path = require('path');\n")
        result = plugin.parse_file(f)
        expected = ImportRef(
            source="path", specifiers=("path",), is_relative=False,
        )
        assert expected in result.imports

    def test_destructured_require(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `const { readFile } = require('fs')`."""
        f = tmp_path / "a.js"
        f.write_text("const { readFile, writeFile } = require('fs');\n")
        result = plugin.parse_file(f)
        expected = ImportRef(
            source="fs",
            specifiers=("readFile", "writeFile"),
            is_relative=False,
        )
        assert expected in result.imports

    def test_relative_require(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Relative require paths are marked is_relative=True."""
        f = tmp_path / "a.js"
        f.write_text("const utils = require('./utils');\n")
        result = plugin.parse_file(f)
        ref = result.imports[0]
        assert ref.is_relative is True
        assert ref.source == "./utils"


# ---------------------------------------------------------------------------
# Dynamic import
# ---------------------------------------------------------------------------


class TestDynamicImport:
    """Tests for extracting dynamic import() expressions."""

    def test_dynamic_import(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `import('module')` as an import."""
        f = tmp_path / "a.ts"
        f.write_text("const mod = await import('./lazy-module');\n")
        result = plugin.parse_file(f)
        expected = ImportRef(
            source="./lazy-module", specifiers=(), is_relative=True,
        )
        assert expected in result.imports

    def test_dynamic_import_in_function(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Dynamic imports inside functions are captured."""
        f = tmp_path / "a.ts"
        f.write_text(
            "async function load() {\n"
            "  const mod = await import('heavy-lib');\n"
            "  return mod;\n"
            "}\n"
        )
        result = plugin.parse_file(f)
        sources = {ref.source for ref in result.imports}
        assert "heavy-lib" in sources


# ---------------------------------------------------------------------------
# Export extraction
# ---------------------------------------------------------------------------


class TestExportExtraction:
    """Tests for extracting exported symbols from TS/JS files."""

    def test_export_function(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `export function greet() {}`."""
        f = tmp_path / "a.ts"
        f.write_text("export function greet() {}\n")
        result = plugin.parse_file(f)
        assert ExportRef(
            name="greet", kind=ExportKind.FUNCTION, line=1,
        ) in result.exports

    def test_export_class(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `export class Foo {}`."""
        f = tmp_path / "a.ts"
        f.write_text("export class Foo {}\n")
        result = plugin.parse_file(f)
        assert ExportRef(
            name="Foo", kind=ExportKind.CLASS, line=1,
        ) in result.exports

    def test_export_const(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `export const X = 1`."""
        f = tmp_path / "a.ts"
        f.write_text("export const X = 1;\n")
        result = plugin.parse_file(f)
        assert ExportRef(
            name="X", kind=ExportKind.VARIABLE, line=1,
        ) in result.exports

    def test_export_default_function(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `export default function main() {}`."""
        f = tmp_path / "a.ts"
        f.write_text("export default function main() {}\n")
        result = plugin.parse_file(f)
        # Should have both a DEFAULT export and the function
        kinds = {e.kind for e in result.exports}
        assert ExportKind.DEFAULT in kinds

    def test_export_default_class(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `export default class App {}`."""
        f = tmp_path / "a.ts"
        f.write_text("export default class App {}\n")
        result = plugin.parse_file(f)
        kinds = {e.kind for e in result.exports}
        assert ExportKind.DEFAULT in kinds

    def test_export_default_expression(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `export default 42`."""
        f = tmp_path / "a.ts"
        f.write_text("export default 42;\n")
        result = plugin.parse_file(f)
        assert ExportRef(
            name="default", kind=ExportKind.DEFAULT, line=1,
        ) in result.exports

    def test_named_export_clause(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `export { foo, bar }`."""
        f = tmp_path / "a.ts"
        f.write_text(
            "function foo() {}\n"
            "function bar() {}\n"
            "export { foo, bar };\n"
        )
        result = plugin.parse_file(f)
        names = {e.name for e in result.exports}
        assert "foo" in names
        assert "bar" in names

    def test_re_export(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `export { foo } from './mod'`."""
        f = tmp_path / "a.ts"
        f.write_text("export { foo } from './mod';\n")
        result = plugin.parse_file(f)
        names = {e.name for e in result.exports}
        assert "foo" in names

    def test_module_exports(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `module.exports = { foo, bar }`."""
        f = tmp_path / "a.js"
        f.write_text("module.exports = { foo, bar };\n")
        result = plugin.parse_file(f)
        names = {e.name for e in result.exports}
        assert "foo" in names
        assert "bar" in names

    def test_export_let_var(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Export with let/var: `export let x = 1; export var y = 2;`."""
        f = tmp_path / "a.ts"
        f.write_text("export let x = 1;\nexport var y = 2;\n")
        result = plugin.parse_file(f)
        names = {e.name for e in result.exports}
        assert "x" in names
        assert "y" in names

    def test_export_arrow_function(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Export arrow fn: `export const greet = () => {}`."""
        f = tmp_path / "a.ts"
        f.write_text("export const greet = () => {};\n")
        result = plugin.parse_file(f)
        names = {e.name for e in result.exports}
        assert "greet" in names


# ---------------------------------------------------------------------------
# TypeScript-specific constructs
# ---------------------------------------------------------------------------


class TestTypeScriptSpecific:
    """Tests for TypeScript-specific syntax: interfaces, types, enums."""

    def test_export_interface(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `export interface Foo {}`."""
        f = tmp_path / "a.ts"
        f.write_text("export interface Config { db: string; }\n")
        result = plugin.parse_file(f)
        assert ExportRef(
            name="Config", kind=ExportKind.TYPE, line=1,
        ) in result.exports

    def test_export_type_alias(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `export type Foo = string | number`."""
        f = tmp_path / "a.ts"
        f.write_text("export type UserId = string | number;\n")
        result = plugin.parse_file(f)
        assert ExportRef(
            name="UserId", kind=ExportKind.TYPE, line=1,
        ) in result.exports

    def test_export_enum(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `export enum Color { Red, Green, Blue }`."""
        f = tmp_path / "a.ts"
        f.write_text("export enum Color { Red, Green, Blue }\n")
        result = plugin.parse_file(f)
        assert ExportRef(
            name="Color", kind=ExportKind.TYPE, line=1,
        ) in result.exports

    def test_non_exported_interface(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Non-exported interfaces are not in exports."""
        f = tmp_path / "a.ts"
        f.write_text("interface Internal { x: number; }\n")
        result = plugin.parse_file(f)
        names = {e.name for e in result.exports}
        assert "Internal" not in names

    def test_type_only_import(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `import type { Foo } from './types'`."""
        f = tmp_path / "a.ts"
        f.write_text("import type { Foo } from './types';\n")
        result = plugin.parse_file(f)
        expected = ImportRef(
            source="./types", specifiers=("Foo",), is_relative=True,
        )
        assert expected in result.imports

    def test_export_type_clause(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Extract `export type { Foo }`."""
        f = tmp_path / "a.ts"
        f.write_text("export type { Foo };\n")
        result = plugin.parse_file(f)
        names = {e.name for e in result.exports}
        assert "Foo" in names


# ---------------------------------------------------------------------------
# Function extraction
# ---------------------------------------------------------------------------


class TestFunctionExtraction:
    """Tests for extracting function declarations and call relationships."""

    def test_function_declaration(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Regular function declarations are extracted."""
        f = tmp_path / "a.ts"
        f.write_text("function greet(name: string) {\n  return name;\n}\n")
        result = plugin.parse_file(f)
        func = next(fn for fn in result.functions if fn.name == "greet")
        assert func.line == 1
        assert func.end_line == 3

    def test_arrow_function_assigned_to_const(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Arrow functions assigned to const are extracted."""
        f = tmp_path / "a.ts"
        f.write_text("const greet = (name: string) => name;\n")
        result = plugin.parse_file(f)
        names = {fn.name for fn in result.functions}
        assert "greet" in names

    def test_function_expression_assigned(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Function expressions assigned to variables are extracted."""
        f = tmp_path / "a.ts"
        f.write_text(
            "const greet = function(name: string) {\n"
            "  return name;\n"
            "};\n"
        )
        result = plugin.parse_file(f)
        names = {fn.name for fn in result.functions}
        assert "greet" in names

    def test_class_methods(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Methods inside classes are extracted with qualified names."""
        f = tmp_path / "a.ts"
        f.write_text(
            "class Service {\n"
            "  start() {\n"
            "    this.init();\n"
            "  }\n"
            "  init() {}\n"
            "}\n"
        )
        result = plugin.parse_file(f)
        names = {fn.name for fn in result.functions}
        assert "Service.start" in names
        assert "Service.init" in names

    def test_function_calls_extracted(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Function calls within a function body are captured."""
        f = tmp_path / "a.ts"
        f.write_text(
            "function process() {\n"
            "  validate();\n"
            "  save();\n"
            "}\n"
        )
        result = plugin.parse_file(f)
        func = next(fn for fn in result.functions if fn.name == "process")
        assert "validate" in func.calls
        assert "save" in func.calls

    def test_method_calls_captured(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Method calls like obj.method() are captured."""
        f = tmp_path / "a.ts"
        f.write_text("function run() {\n  db.query('SELECT 1');\n}\n")
        result = plugin.parse_file(f)
        func = next(fn for fn in result.functions if fn.name == "run")
        assert "db.query" in func.calls

    def test_calls_sorted_and_deduped(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Calls are sorted and deduplicated for determinism."""
        f = tmp_path / "a.ts"
        f.write_text(
            "function run() {\n"
            "  save();\n"
            "  validate();\n"
            "  save();\n"
            "}\n"
        )
        result = plugin.parse_file(f)
        func = next(fn for fn in result.functions if fn.name == "run")
        assert func.calls == ("save", "validate")

    def test_async_function(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Async functions are extracted normally."""
        f = tmp_path / "a.ts"
        f.write_text("async function fetch() {\n  await get();\n}\n")
        result = plugin.parse_file(f)
        func = next(fn for fn in result.functions if fn.name == "fetch")
        assert func.line == 1
        assert "get" in func.calls

    def test_exported_function_in_functions(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Exported functions also appear in the functions list."""
        f = tmp_path / "a.ts"
        f.write_text("export function greet() {}\n")
        result = plugin.parse_file(f)
        names = {fn.name for fn in result.functions}
        assert "greet" in names


# ---------------------------------------------------------------------------
# Class extraction (via exports)
# ---------------------------------------------------------------------------


class TestClassExtraction:
    """Tests for class declaration extraction."""

    def test_class_declaration(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Class methods are extracted from class declarations."""
        f = tmp_path / "a.ts"
        f.write_text(
            "class UserService {\n"
            "  getUser() { return null; }\n"
            "  saveUser() {}\n"
            "}\n"
        )
        result = plugin.parse_file(f)
        names = {fn.name for fn in result.functions}
        assert "UserService.getUser" in names
        assert "UserService.saveUser" in names

    def test_exported_class(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Exported classes appear in exports."""
        f = tmp_path / "a.ts"
        f.write_text("export class App {}\n")
        result = plugin.parse_file(f)
        assert ExportRef(
            name="App", kind=ExportKind.CLASS, line=1,
        ) in result.exports


# ---------------------------------------------------------------------------
# Entry point detection
# ---------------------------------------------------------------------------


class TestEntryPointDetection:
    """Tests for detecting TS/JS entry points."""

    def test_main_ts_not_entry_by_default(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Regular TS files are not entry points."""
        f = tmp_path / "utils.ts"
        f.write_text("export function helper() {}\n")
        result = plugin.parse_file(f)
        assert result.entry_point is False

    def test_index_ts_is_entry_point(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """index.ts/index.js files are entry points."""
        f = tmp_path / "index.ts"
        f.write_text("export function main() {}\n")
        result = plugin.parse_file(f)
        assert result.entry_point is True

    def test_main_ts_is_entry_point(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """main.ts/main.js files are entry points."""
        f = tmp_path / "main.ts"
        f.write_text("console.log('hello');\n")
        result = plugin.parse_file(f)
        assert result.entry_point is True

    def test_app_ts_is_entry_point(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """app.ts/app.js files are entry points."""
        f = tmp_path / "app.ts"
        f.write_text("const app = express();\n")
        result = plugin.parse_file(f)
        assert result.entry_point is True


# ---------------------------------------------------------------------------
# Import resolution
# ---------------------------------------------------------------------------


class TestImportResolution:
    """Tests for resolving TS/JS imports to file paths."""

    def test_resolve_relative_import_ts(
        self, plugin: TypeScriptPlugin, ts_project: Path,
    ) -> None:
        """Resolve `./config` to `src/config.ts`."""
        ref = ImportRef(
            source="./config", specifiers=("getConfig",), is_relative=True,
        )
        from_file = ts_project / "src" / "index.ts"
        resolved = plugin.resolve_import(ref, from_file)
        assert resolved is not None
        assert resolved.name == "config.ts"

    def test_resolve_relative_import_with_extension(
        self, plugin: TypeScriptPlugin, ts_project: Path,
    ) -> None:
        """Resolve `./config.ts` (explicit extension) to file."""
        ref = ImportRef(
            source="./config.ts", specifiers=(), is_relative=True,
        )
        from_file = ts_project / "src" / "index.ts"
        resolved = plugin.resolve_import(ref, from_file)
        assert resolved is not None
        assert resolved.name == "config.ts"

    def test_resolve_index_file(
        self, plugin: TypeScriptPlugin, ts_project: Path,
    ) -> None:
        """Resolve `./utils` to `utils/index.ts`."""
        ref = ImportRef(
            source="./utils", specifiers=("formatName",), is_relative=True,
        )
        from_file = ts_project / "src" / "config.ts"
        resolved = plugin.resolve_import(ref, from_file)
        assert resolved is not None
        assert resolved.name == "index.ts"

    def test_resolve_parent_relative(
        self, plugin: TypeScriptPlugin, ts_project: Path,
    ) -> None:
        """Resolve `../config` from a subdirectory."""
        ref = ImportRef(
            source="../config", specifiers=("DB_URL",), is_relative=True,
        )
        from_file = ts_project / "src" / "utils" / "helpers.ts"
        resolved = plugin.resolve_import(ref, from_file)
        assert resolved is not None
        assert resolved.name == "config.ts"

    def test_resolve_external_package_returns_none(
        self, plugin: TypeScriptPlugin, ts_project: Path,
    ) -> None:
        """External packages (react, lodash) return None."""
        ref = ImportRef(
            source="react", specifiers=("useState",), is_relative=False,
        )
        from_file = ts_project / "src" / "index.ts"
        resolved = plugin.resolve_import(ref, from_file)
        assert resolved is None

    def test_resolve_scoped_package_returns_none(
        self, plugin: TypeScriptPlugin, ts_project: Path,
    ) -> None:
        """Scoped packages (@org/pkg) return None."""
        ref = ImportRef(
            source="@org/pkg", specifiers=(), is_relative=False,
        )
        from_file = ts_project / "src" / "index.ts"
        resolved = plugin.resolve_import(ref, from_file)
        assert resolved is None

    def test_resolve_js_file(
        self, plugin: TypeScriptPlugin, ts_project: Path,
    ) -> None:
        """Resolve imports to .js files."""
        ref = ImportRef(
            source="./legacy", specifiers=("resolve",), is_relative=True,
        )
        from_file = ts_project / "src" / "index.ts"
        resolved = plugin.resolve_import(ref, from_file)
        assert resolved is not None
        assert resolved.name == "legacy.js"


# ---------------------------------------------------------------------------
# JSX/TSX files
# ---------------------------------------------------------------------------


class TestJSXTSXFiles:
    """Tests for JSX and TSX file parsing."""

    def test_tsx_file(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """TSX files with JSX syntax parse correctly."""
        f = tmp_path / "App.tsx"
        f.write_text(
            "import React from 'react';\n"
            "\n"
            "export function App() {\n"
            "  return <div>Hello</div>;\n"
            "}\n"
        )
        result = plugin.parse_file(f)
        sources = {ref.source for ref in result.imports}
        assert "react" in sources
        names = {fn.name for fn in result.functions}
        assert "App" in names

    def test_jsx_file(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """JSX files parse correctly."""
        f = tmp_path / "Component.jsx"
        f.write_text(
            "import React from 'react';\n"
            "\n"
            "export default function Component() {\n"
            "  return <span>hi</span>;\n"
            "}\n"
        )
        result = plugin.parse_file(f)
        sources = {ref.source for ref in result.imports}
        assert "react" in sources
        kinds = {e.kind for e in result.exports}
        assert ExportKind.DEFAULT in kinds


# ---------------------------------------------------------------------------
# MJS/CJS files
# ---------------------------------------------------------------------------


class TestMJSCJSFiles:
    """Tests for .mjs and .cjs file parsing."""

    def test_mjs_file(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """MJS files use JS grammar."""
        f = tmp_path / "utils.mjs"
        f.write_text("export function helper() { return 1; }\n")
        result = plugin.parse_file(f)
        names = {e.name for e in result.exports}
        assert "helper" in names

    def test_cjs_file(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """CJS files use JS grammar."""
        f = tmp_path / "utils.cjs"
        f.write_text("const x = require('fs');\nmodule.exports = { x };\n")
        result = plugin.parse_file(f)
        assert len(result.imports) > 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_file(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Empty files parse to empty results."""
        f = tmp_path / "empty.ts"
        f.write_text("")
        result = plugin.parse_file(f)
        assert result.imports == ()
        assert result.exports == ()
        assert result.functions == ()
        assert result.entry_point is False

    def test_syntax_error_file(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Syntax error files return partial results (error-tolerant)."""
        f = tmp_path / "bad.ts"
        f.write_text("export function broken(\n")
        result = plugin.parse_file(f)
        assert isinstance(result, ParseResult)

    def test_file_not_found(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            plugin.parse_file(tmp_path / "nonexistent.ts")

    def test_parse_is_deterministic(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Parsing the same file twice produces identical results."""
        f = tmp_path / "a.ts"
        f.write_text(
            "import { useState } from 'react';\n"
            "import { useEffect } from 'react';\n"
            "export function App() {\n"
            "  useState();\n"
            "  useEffect();\n"
            "}\n"
            "export class Config {}\n"
            "export const VERSION = '1.0';\n"
        )
        r1 = plugin.parse_file(f)
        r2 = plugin.parse_file(f)
        assert r1 == r2

    def test_encoding_utf8(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """UTF-8 files parse correctly."""
        f = tmp_path / "a.ts"
        f.write_text("export function grüße() {}\n")
        result = plugin.parse_file(f)
        names = {fn.name for fn in result.functions}
        assert "grüße" in names

    def test_imports_sorted_for_determinism(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Import results are sorted by source for deterministic output."""
        f = tmp_path / "a.ts"
        f.write_text(
            "import 'z-module';\n"
            "import 'a-module';\n"
            "import 'm-module';\n"
        )
        result = plugin.parse_file(f)
        sources = [ref.source for ref in result.imports]
        assert sources == sorted(sources)

    def test_comment_only_file(
        self, plugin: TypeScriptPlugin, tmp_path: Path,
    ) -> None:
        """Files with only comments parse to empty results."""
        f = tmp_path / "a.ts"
        f.write_text("// This is a comment\n/* Block comment */\n")
        result = plugin.parse_file(f)
        assert result.imports == ()
        assert result.exports == ()
        assert result.functions == ()
