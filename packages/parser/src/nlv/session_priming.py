"""Session priming — compressed context from previous summaries (BED-79).

Builds a compact context string for `/read-next` that orients Claude
at the start of each reading session. Collects one-line summaries from
progress.json, separates dependency summaries from general progress,
and includes structural data from map.json.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SessionContext:
    """Structured context for a reading session.

    Holds all data needed to prime Claude before reading a file:
    structural info from map.json and summaries from progress.json.

    Attributes:
        current_file: Path of the file about to be read.
        layer: Which architectural layer this file belongs to.
        line_count: Number of lines in the file.
        complexity: Complexity rating from the parser.
        reason: Why this file is next in reading order.
        imports: Files this file imports (direct dependencies).
        imported_by: Files that import this file (consumers).
        exports: Symbols exported by this file.
        dependency_summaries: Summaries of read direct dependencies.
            Keys are file paths, values are summary strings or None.
        dependency_statuses: Reading statuses of read dependencies.
            Keys are file paths, values are status strings.
        general_summaries: Summaries of other read files (not deps).
            Keys are file paths, values are summary strings or None.
    """

    current_file: str
    layer: str
    line_count: int
    complexity: str
    reason: str
    imports: list[str] = field(
        default_factory=lambda: list[str](),
    )
    imported_by: list[str] = field(
        default_factory=lambda: list[str](),
    )
    exports: list[str] = field(
        default_factory=lambda: list[str](),
    )
    dependency_summaries: dict[str, str | None] = field(
        default_factory=lambda: dict[str, str | None](),
    )
    dependency_statuses: dict[str, str] = field(
        default_factory=lambda: dict[str, str](),
    )
    general_summaries: dict[str, str | None] = field(
        default_factory=lambda: dict[str, str | None](),
    )

    def format(self) -> str:
        """Format the session context as a compact readable string.

        Returns:
            Multi-line string suitable for injecting into context.
        """
        lines: list[str] = []
        lines.append(
            f"-- Next: {self.current_file} "
            + "-" * max(1, 50 - len(self.current_file) - 9)
        )
        lines.append(
            f"Layer: {self.layer} | "
            f"Lines: {self.line_count} | "
            f"Complexity: {self.complexity}"
        )

        if self.reason:
            lines.append(f"Why now: {self.reason}")

        lines.extend(_format_dependency_section(self))
        lines.extend(_format_structural_section(self))
        lines.extend(_format_general_section(self))

        lines.append("-" * 50)
        return "\n".join(lines)


def build_session_context(
    guide_dir: Path,
    current_file: str,
) -> SessionContext:
    """Build session context for a file about to be read.

    Loads map.json and progress.json, finds the current file in the
    reading order, collects summaries of previously-read files, and
    separates them into dependency summaries and general summaries.

    Args:
        guide_dir: Path to the `.codebase-guide` directory.
        current_file: Path of the file to build context for.

    Returns:
        A SessionContext with all priming data.

    Raises:
        FileNotFoundError: If map.json or progress.json is missing.
        KeyError: If current_file is not in the reading order.
    """
    map_data = _load_map(guide_dir)
    progress_data = _load_progress(guide_dir)

    ro_entry = _find_reading_order_entry(map_data, current_file)
    imports_list = list(ro_entry.get("imports", []))

    dep_summaries, dep_statuses, general_summaries = (
        _collect_summaries(
            progress_data, current_file, set(imports_list),
        )
    )

    return SessionContext(
        current_file=current_file,
        layer=str(ro_entry.get("layer", "unknown")),
        line_count=int(ro_entry.get("line_count", 0)),
        complexity=str(ro_entry.get("complexity", "unknown")),
        reason=str(ro_entry.get("reason", "")),
        imports=imports_list,
        imported_by=list(ro_entry.get("imported_by", [])),
        exports=list(ro_entry.get("exports", [])),
        dependency_summaries=dep_summaries,
        dependency_statuses=dep_statuses,
        general_summaries=general_summaries,
    )


def _load_map(guide_dir: Path) -> dict[str, Any]:
    """Load map.json from disk.

    Raises:
        FileNotFoundError: If map.json does not exist.
    """
    map_path = guide_dir / "map.json"
    if not map_path.exists():
        msg = f"map.json not found at {map_path}"
        raise FileNotFoundError(msg)
    raw = map_path.read_text()
    result: dict[str, Any] = json.loads(raw)
    return result


def _load_progress(guide_dir: Path) -> dict[str, Any]:
    """Load progress.json from disk.

    Raises:
        FileNotFoundError: If progress.json does not exist.
    """
    progress_path = guide_dir / "progress.json"
    if not progress_path.exists():
        msg = f"progress.json not found at {progress_path}"
        raise FileNotFoundError(msg)
    raw = progress_path.read_text()
    result: dict[str, Any] = json.loads(raw)
    return result


def _find_reading_order_entry(
    map_data: dict[str, Any],
    target_file: str,
) -> dict[str, Any]:
    """Find a file's entry in the reading order.

    Args:
        map_data: Parsed map.json content.
        target_file: File path to look up.

    Returns:
        The reading order entry dict.

    Raises:
        KeyError: If the file is not in the reading order.
    """
    for entry in map_data.get("reading_order", []):
        if entry["path"] == target_file:
            return entry
    msg = f"File not in reading order: {target_file}"
    raise KeyError(msg)


def _collect_summaries(
    progress_data: dict[str, Any],
    current_file: str,
    dependency_paths: set[str],
) -> tuple[
    dict[str, str | None],
    dict[str, str],
    dict[str, str | None],
]:
    """Collect summaries split into dependency and general buckets.

    Only includes files that have been read (status != "unread").
    The current file is excluded from both buckets.

    Args:
        progress_data: Parsed progress.json content.
        current_file: Path of the file being read (excluded).
        dependency_paths: Set of file paths that are direct imports.

    Returns:
        Tuple of (dependency_summaries, dependency_statuses,
        general_summaries).
    """
    dep_summaries: dict[str, str | None] = {}
    dep_statuses: dict[str, str] = {}
    general_summaries: dict[str, str | None] = {}

    files: dict[str, dict[str, Any]] = progress_data.get("files", {})

    for path, entry in files.items():
        if path == current_file:
            continue
        if entry.get("status") == "unread":
            continue

        summary = entry.get("summary")
        status = str(entry.get("status", ""))

        if path in dependency_paths:
            dep_summaries[path] = summary
            dep_statuses[path] = status
        else:
            general_summaries[path] = summary

    return dep_summaries, dep_statuses, general_summaries


def _format_dependency_section(ctx: SessionContext) -> list[str]:
    """Format the dependency summaries section.

    Shows each direct import with its read status and summary.
    """
    if not ctx.imports:
        return []

    lines: list[str] = ["", "Dependencies (imports):"]
    for dep_path in ctx.imports:
        if dep_path in ctx.dependency_summaries:
            status = ctx.dependency_statuses.get(dep_path, "read")
            summary = ctx.dependency_summaries[dep_path]
            summary_text = (
                f'"{summary}"' if summary else "(no summary)"
            )
            lines.append(
                f"  [{status}] {dep_path} -- {summary_text}",
            )
        else:
            lines.append(f"  [unread] {dep_path}")
    return lines


def _format_structural_section(ctx: SessionContext) -> list[str]:
    """Format the structural info section (exports, imported_by)."""
    lines: list[str] = []

    if ctx.exports:
        lines.append("")
        lines.append(f"Exports: {', '.join(ctx.exports)}")

    if ctx.imported_by:
        lines.append(
            f"Used by: {', '.join(ctx.imported_by)} (unread, later)"
        )

    return lines


def _format_general_section(ctx: SessionContext) -> list[str]:
    """Format the general progress summaries section."""
    if not ctx.general_summaries:
        return []

    lines: list[str] = ["", "Previously read:"]
    for path, summary in ctx.general_summaries.items():
        summary_text = f'"{summary}"' if summary else "(no summary)"
        lines.append(f"  {path} -- {summary_text}")
    return lines
