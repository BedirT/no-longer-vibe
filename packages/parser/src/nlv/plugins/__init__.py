"""Language plugins for AST parsing.

Defines the LanguagePlugin protocol, shared data types, and the
PluginRegistry that dispatches files to the correct language parser.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types shared across all language plugins
# ---------------------------------------------------------------------------


class ExportKind(enum.Enum):
    """The kind of symbol being exported."""

    FUNCTION = "function"
    CLASS = "class"
    TYPE = "type"
    VARIABLE = "variable"
    DEFAULT = "default"


@dataclass(frozen=True)
class ImportRef:
    """A single import reference extracted from a source file."""

    source: str
    specifiers: list[str]
    is_relative: bool


@dataclass(frozen=True)
class ExportRef:
    """A single exported symbol from a source file."""

    name: str
    kind: ExportKind
    line: int


@dataclass(frozen=True)
class FunctionRef:
    """A function or method declaration with call relationships."""

    name: str
    line: int
    end_line: int
    calls: list[str]


@dataclass(frozen=True)
class ParseResult:
    """The result of parsing a single source file."""

    imports: list[ImportRef]
    exports: list[ExportRef]
    functions: list[FunctionRef]
    entry_point: bool


# ---------------------------------------------------------------------------
# Plugin protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class LanguagePlugin(Protocol):
    """Interface that each language parser must implement."""

    @property
    def name(self) -> str: ...

    @property
    def extensions(self) -> list[str]: ...

    def parse_file(self, path: Path) -> ParseResult: ...

    def resolve_import(
        self, import_ref: ImportRef, from_file: Path
    ) -> Path | None: ...


# ---------------------------------------------------------------------------
# Plugin registry
# ---------------------------------------------------------------------------


class PluginRegistry:
    """Registry that maps file extensions to language plugins."""

    def __init__(self) -> None:
        self._by_extension: dict[str, LanguagePlugin] = {}
        self._by_name: dict[str, LanguagePlugin] = {}

    def register(self, plugin: LanguagePlugin) -> None:
        """Register a plugin. Raises ValueError on duplicate extensions."""
        for ext in plugin.extensions:
            if ext in self._by_extension:
                existing = self._by_extension[ext]
                msg = (
                    f"Extension {ext} already registered "
                    f"by plugin {existing.name!r}"
                )
                raise ValueError(msg)
            self._by_extension[ext] = plugin
        self._by_name[plugin.name] = plugin
        logger.debug("Registered language plugin: %s", plugin.name)

    def get_plugin_for_file(self, path: Path) -> LanguagePlugin | None:
        """Return the plugin that handles this file's extension, or None."""
        return self._by_extension.get(path.suffix)

    def get_plugin_by_name(self, name: str) -> LanguagePlugin | None:
        """Return a plugin by its name, or None."""
        return self._by_name.get(name)

    def get_supported_extensions(self) -> set[str]:
        """Return all file extensions that have a registered plugin."""
        return set(self._by_extension.keys())

    def list_plugins(self) -> list[LanguagePlugin]:
        """Return all registered plugins."""
        return list(self._by_name.values())
