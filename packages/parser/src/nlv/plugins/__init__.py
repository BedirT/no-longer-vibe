"""Language plugins for AST parsing.

Defines the LanguagePlugin protocol, shared data types, and the
PluginRegistry that dispatches files to the correct language parser.
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Sequence
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
    specifiers: tuple[str, ...]
    is_relative: bool


@dataclass(frozen=True)
class ExportRef:
    """A single exported symbol from a source file.

    ``line`` is the declaration line (1-indexed). Exports are point
    declarations so no ``end_line`` is tracked (unlike FunctionRef).
    """

    name: str
    kind: ExportKind
    line: int


@dataclass(frozen=True)
class FunctionRef:
    """A function or method declaration with call relationships."""

    name: str
    line: int
    end_line: int
    calls: tuple[str, ...]


@dataclass(frozen=True)
class ParseResult:
    """The result of parsing a single source file."""

    imports: tuple[ImportRef, ...]
    exports: tuple[ExportRef, ...]
    functions: tuple[FunctionRef, ...]
    entry_point: bool


# ---------------------------------------------------------------------------
# Plugin protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class LanguagePlugin(Protocol):
    """Interface that each language parser must implement.

    ``parse_file`` raises ``FileNotFoundError`` if the path does not
    exist.  ``resolve_import`` returns ``None`` for unresolvable imports
    (e.g. third-party packages not on disk).
    """

    @property
    def name(self) -> str: ...

    @property
    def extensions(self) -> Sequence[str]: ...

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
        """Register a plugin.

        Raises ``ValueError`` on duplicate extensions, duplicate names,
        or extensions missing a leading dot.
        """
        # Validate everything before mutating any state
        if plugin.name in self._by_name:
            msg = f"Plugin name {plugin.name!r} already registered"
            raise ValueError(msg)

        for ext in plugin.extensions:
            if not ext.startswith("."):
                msg = f"Extension {ext!r} must start with '.'"
                raise ValueError(msg)
            if ext in self._by_extension:
                existing = self._by_extension[ext]
                msg = (
                    f"Extension {ext} already registered "
                    f"by plugin {existing.name!r}"
                )
                raise ValueError(msg)

        # All checks passed — commit the registration
        for ext in plugin.extensions:
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
