"""/read-next command logic (BED-75).

Finds the next unread file in reading order, builds a structural
briefing with session context injection, and handles file completion
actions (confirmed, flagged, skimmed).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nlv.progress import FileStatus, ProgressManager
from nlv.session_priming import SessionContext, build_session_context

logger = logging.getLogger(__name__)

_VALID_ACTIONS = frozenset({"confirmed", "flagged", "skimmed"})


class AllFilesReadError(Exception):
    """Raised when all files in the reading order have been read."""


@dataclass(frozen=True)
class NextBriefing:
    """Briefing for the next unread file in reading order.

    Contains structural context from map.json, dependency statuses,
    and session context for priming Claude.
    """

    path: str
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
    dependency_statuses: dict[str, str] = field(
        default_factory=lambda: dict[str, str](),
    )
    dependency_summaries: dict[str, str | None] = field(
        default_factory=lambda: dict[str, str | None](),
    )
    session_context: SessionContext | None = None

    def format(self) -> str:
        """Format the briefing as a human-readable string.

        Matches the template from the SPEC.md specification.
        """
        lines: list[str] = []
        separator_len = max(1, 50 - len(self.path) - 9)
        lines.append(
            f"-- Next: {self.path} " + "-" * separator_len
        )
        lines.append(
            f"Layer: {self.layer} | "
            f"Lines: {self.line_count} | "
            f"Complexity: {self.complexity}"
        )

        if self.reason:
            lines.append("")
            lines.append(f"Why now: {self.reason}")

        lines.extend(_format_deps(self))
        lines.extend(_format_exports(self))
        lines.extend(_format_imported_by(self))

        lines.append("-" * 50)
        return "\n".join(lines)


class ReadNextManager:
    """Manage the /read-next flow: find, brief, and complete files.

    Args:
        guide_dir: Path to the `.codebase-guide` directory.
    """

    def __init__(self, guide_dir: Path) -> None:
        self._guide_dir = guide_dir
        self._progress_mgr = ProgressManager(guide_dir)
        self._session_started = False
        self._reading_order_paths: list[str] | None = None

    def next_briefing(self) -> NextBriefing:
        """Find the next unread file and build its briefing.

        On the first call per ReadNextManager instance, increments
        the session counter in progress.json.

        Returns:
            A NextBriefing with all structural and session context.

        Raises:
            FileNotFoundError: If map.json or progress.json is missing.
            AllFilesReadError: If no unread files remain.
        """
        map_data = _load_map(self._guide_dir)
        progress_data = self._progress_mgr.load()

        # Always refresh from the just-loaded map data
        self._reading_order_paths = [
            e["path"] for e in map_data.get("reading_order", [])
        ]

        if not self._session_started:
            self._progress_mgr.start_session()
            self._session_started = True

        next_path = _find_next_unread(map_data, progress_data)
        if next_path is None:
            stats = progress_data.get("stats", {})
            total = stats.get("total", 0)
            confirmed = stats.get("confirmed", 0)
            flagged = stats.get("flagged", 0)
            skimmed = stats.get("skimmed", 0)
            raise AllFilesReadError(
                f"All {total} files read: "
                f"{confirmed} confirmed, "
                f"{flagged} flagged, "
                f"{skimmed} skimmed."
            )

        ro_entry = _find_reading_order_entry(map_data, next_path)
        dep_statuses, dep_summaries = _collect_dep_info(
            progress_data, ro_entry,
        )

        session_ctx = build_session_context(
            self._guide_dir, next_path,
        )

        return NextBriefing(
            path=next_path,
            layer=str(ro_entry.get("layer", "unknown")),
            line_count=int(ro_entry.get("line_count", 0)),
            complexity=str(ro_entry.get("complexity", "unknown")),
            reason=str(ro_entry.get("reason", "")),
            imports=list(ro_entry.get("imports", [])),
            imported_by=list(ro_entry.get("imported_by", [])),
            exports=list(ro_entry.get("exports", [])),
            dependency_statuses=dep_statuses,
            dependency_summaries=dep_summaries,
            session_context=session_ctx,
        )

    def complete_file(
        self,
        path: str,
        *,
        action: str,
        note: str | None = None,
        summary: str | None = None,
    ) -> None:
        """Mark a file with the given completion action.

        Args:
            path: File path as it appears in the reading order.
            action: One of "confirmed", "flagged", or "skimmed".
            note: Note for flagging (only used when action="flagged").
            summary: One-line summary of the file.

        Raises:
            ValueError: If action is not valid.
            KeyError: If the file is not tracked in progress.
        """
        if action not in _VALID_ACTIONS:
            msg = (
                f"Invalid action: {action!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_ACTIONS))}"
            )
            raise ValueError(msg)

        status = FileStatus(action)
        self._progress_mgr.update_file(
            path,
            status=status,
            note=note,
            summary=summary,
        )

        ro_paths = self._get_reading_order_paths()
        self._progress_mgr.advance_pointer(ro_paths)

    def _get_reading_order_paths(self) -> list[str]:
        """Return cached reading order paths, loading map if needed."""
        if self._reading_order_paths is None:
            map_data = _load_map(self._guide_dir)
            self._reading_order_paths = [
                e["path"]
                for e in map_data.get("reading_order", [])
            ]
        return self._reading_order_paths

    def format_all_read(self) -> str:
        """Format a completion message when all files are read.

        Returns:
            A summary string with final stats.
        """
        progress_data = self._progress_mgr.load()
        stats = progress_data.get("stats", {})
        total = stats.get("total", 0)
        confirmed = stats.get("confirmed", 0)
        flagged = stats.get("flagged", 0)
        skimmed = stats.get("skimmed", 0)
        sessions = progress_data.get("sessions", 0)

        lines: list[str] = []
        lines.append(f"All {total} files read!")
        lines.append("")
        lines.append(f"  confirmed: {confirmed}")
        lines.append(f"  flagged: {flagged}")
        lines.append(f"  skimmed: {skimmed}")
        lines.append("")
        lines.append(f"Sessions: {sessions}")

        if flagged > 0:
            lines.append("")
            lines.append(
                f"{flagged} file(s) flagged for second pass. "
                "Run /read-flagged to review."
            )

        return "\n".join(lines)


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


def _find_next_unread(
    map_data: dict[str, Any],
    progress_data: dict[str, Any],
) -> str | None:
    """Find the next unread file in reading order.

    Uses the ``next_unread_index`` pointer from progress data to
    start scanning from the last known position instead of index 0.

    Args:
        map_data: Parsed map.json content.
        progress_data: Parsed progress.json content.

    Returns:
        File path string, or None if all files are read.
    """
    reading_order: list[dict[str, Any]] = map_data.get(
        "reading_order", [],
    )
    files: dict[str, dict[str, Any]] = progress_data.get("files", {})
    start = int(progress_data.get("next_unread_index", 0))

    # Scan forward from pointer position
    for entry in reading_order[start:]:
        path = entry["path"]
        file_entry = files.get(path)
        if file_entry and file_entry.get("status") == "unread":
            return path

    # Fallback: scan from beginning up to pointer position.
    # Handles stale pointers after refresh or backward status changes.
    for entry in reading_order[:start]:
        path = entry["path"]
        file_entry = files.get(path)
        if file_entry and file_entry.get("status") == "unread":
            return path

    return None


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


def _collect_dep_info(
    progress_data: dict[str, Any],
    ro_entry: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str | None]]:
    """Collect dependency statuses and summaries.

    Returns only dependencies that have been read (not unread).

    Args:
        progress_data: Parsed progress.json content.
        ro_entry: The reading order entry for the current file.

    Returns:
        Tuple of (statuses_dict, summaries_dict).
    """
    imports_list: list[str] = ro_entry.get("imports", [])
    files: dict[str, dict[str, Any]] = progress_data.get("files", {})

    statuses: dict[str, str] = {}
    summaries: dict[str, str | None] = {}

    for dep_path in imports_list:
        entry = files.get(dep_path)
        if entry is None:
            continue
        status = entry.get("status", "unread")
        if status == "unread":
            continue
        statuses[dep_path] = status
        summaries[dep_path] = entry.get("summary")

    return statuses, summaries


def _format_deps(briefing: NextBriefing) -> list[str]:
    """Format the dependency status section of the briefing."""
    if not briefing.imports:
        return []

    lines: list[str] = []
    for dep_path in briefing.imports:
        if dep_path in briefing.dependency_statuses:
            status = briefing.dependency_statuses[dep_path]
            lines.append(f"  [{status}] {dep_path}")
        else:
            lines.append(f"  [unread] {dep_path}")
    return lines


def _format_exports(briefing: NextBriefing) -> list[str]:
    """Format the exports line of the briefing."""
    if not briefing.exports:
        return []
    return ["", f"Exports: {', '.join(briefing.exports)}"]


def _format_imported_by(briefing: NextBriefing) -> list[str]:
    """Format the imported-by line of the briefing."""
    if not briefing.imported_by:
        return []
    return [
        f"Used by: {', '.join(briefing.imported_by)} (unread, later)",
    ]
