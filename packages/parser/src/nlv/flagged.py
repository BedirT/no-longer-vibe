"""/read-flagged command logic (BED-77).

Iterates through flagged files from progress.json, ordered by their
position in the reading order from map.json. For each file, produces
a briefing with the original flag note, structural context, and
supports resolving to confirmed, re-flagging, or skipping.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nlv.progress import FileStatus, ProgressManager

logger = logging.getLogger(__name__)

_VALID_ACTIONS = frozenset({"confirmed", "flagged", "skimmed"})


class NoFlaggedFilesError(Exception):
    """Raised when no flagged files exist in progress data."""


@dataclass(frozen=True)
class FlaggedBriefing:
    """Briefing for a single flagged file.

    Contains the file path, original flag note, structural context
    from map.json, and the summary from the first reading pass.
    """

    path: str
    note: str | None
    summary: str | None
    layer: str
    line_count: int
    reading_order_index: int
    imports: list[str]
    imported_by: list[str]
    exports: list[str]

    def format(self) -> str:
        """Format the briefing as a human-readable string.

        Matches the template from the SKILL.md specification.
        """
        lines: list[str] = []
        lines.append(f"-- Flagged: {self.path} " + "-" * 30)
        lines.append(f"Layer: {self.layer} | Lines: {self.line_count}")

        note_display = f'"{self.note}"' if self.note else "(no note)"
        lines.append(f"Original note: {note_display}")

        if self.summary:
            lines.append(f'Original summary: "{self.summary}"')

        if self.imports:
            lines.append(f"Imports: {', '.join(self.imports)}")

        if self.imported_by:
            lines.append(f"Used by: {', '.join(self.imported_by)}")

        if self.exports:
            lines.append(f"Exports: {', '.join(self.exports)}")

        lines.append("-" * 50)
        return "\n".join(lines)


class FlaggedIterator:
    """Iterate through flagged files in reading order.

    Loads map.json and progress.json from the given guide directory,
    collects all flagged files, and provides methods to resolve them.

    Args:
        guide_dir: Path to the `.codebase-guide` directory.
    """

    def __init__(self, guide_dir: Path) -> None:
        self._guide_dir = guide_dir
        self._progress_mgr = ProgressManager(guide_dir)
        self._briefings: list[FlaggedBriefing] = []
        self._resolved: set[str] = set()

    def collect(self) -> list[FlaggedBriefing]:
        """Collect all flagged files and build briefings.

        Loads both map.json and progress.json, finds flagged files,
        sorts them by reading order, and returns briefings.

        Returns:
            List of FlaggedBriefing objects sorted by reading order.

        Raises:
            FileNotFoundError: If map.json or progress.json is missing.
            NoFlaggedFilesError: If no files have status "flagged".
        """
        map_data = self._load_map()
        progress_data = self._progress_mgr.load()

        flagged_paths = _extract_flagged_paths(progress_data)
        if not flagged_paths:
            raise NoFlaggedFilesError(
                "No flagged files. All clear."
            )

        reading_order_lookup = _build_reading_order_lookup(map_data)

        briefings = _build_briefings(
            flagged_paths,
            progress_data,
            reading_order_lookup,
        )

        briefings.sort(key=lambda b: b.reading_order_index)
        self._briefings = briefings
        self._resolved = set()
        return list(briefings)

    def resolve(
        self,
        path: str,
        *,
        action: str,
        note: str | None = None,
        summary: str | None = None,
    ) -> None:
        """Resolve a flagged file with the given action.

        Args:
            path: File path to resolve.
            action: One of "confirmed", "flagged", or "skimmed".
            note: Note for re-flagging (only used when action="flagged").
            summary: Updated summary (optional).

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
        self._resolved.add(path)

    def remaining(self) -> list[FlaggedBriefing]:
        """Return briefings for flagged files not yet resolved.

        Returns:
            List of unresolved FlaggedBriefing objects.
        """
        return [
            b for b in self._briefings
            if b.path not in self._resolved
        ]

    def _load_map(self) -> dict[str, Any]:
        """Load map.json from disk.

        Raises:
            FileNotFoundError: If map.json does not exist.
        """
        map_path = self._guide_dir / "map.json"
        if not map_path.exists():
            msg = f"map.json not found at {map_path}"
            raise FileNotFoundError(msg)
        raw = map_path.read_text()
        result: dict[str, Any] = json.loads(raw)
        return result


def _extract_flagged_paths(
    progress_data: dict[str, Any],
) -> list[str]:
    """Extract file paths with status 'flagged' from progress data."""
    flagged: list[str] = []
    files = progress_data.get("files", {})
    for path, entry in files.items():
        if entry.get("status") == FileStatus.FLAGGED.value:
            flagged.append(path)
    return flagged


def _build_reading_order_lookup(
    map_data: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Build a lookup from file path to its reading order entry."""
    lookup: dict[str, dict[str, Any]] = {}
    for entry in map_data.get("reading_order", []):
        lookup[entry["path"]] = entry
    return lookup


def _build_briefings(
    flagged_paths: list[str],
    progress_data: dict[str, Any],
    reading_order_lookup: dict[str, dict[str, Any]],
) -> list[FlaggedBriefing]:
    """Build FlaggedBriefing objects for each flagged file.

    Files present in progress but missing from reading_order are
    included with a high index so they sort to the end.
    """
    briefings: list[FlaggedBriefing] = []
    max_index = len(reading_order_lookup)

    for path in flagged_paths:
        file_entry = progress_data["files"][path]
        ro_entry = reading_order_lookup.get(path)

        if ro_entry is not None:
            layer = str(ro_entry.get("layer", "unknown"))
            line_count = int(ro_entry.get("line_count", 0))
            index = int(ro_entry.get("index", max_index))
            imports = list(ro_entry.get("imports", []))
            imported_by = list(ro_entry.get("imported_by", []))
            exports = list(ro_entry.get("exports", []))
        else:
            logger.warning(
                "Flagged file %r not in reading_order, "
                "appending at end",
                path,
            )
            layer = "unknown"
            line_count = 0
            index = max_index
            imports = []
            imported_by = []
            exports = []

        briefings.append(
            FlaggedBriefing(
                path=path,
                note=file_entry.get("note"),
                summary=file_entry.get("summary"),
                layer=layer,
                line_count=line_count,
                reading_order_index=index,
                imports=imports,
                imported_by=imported_by,
                exports=exports,
            ),
        )

    return briefings
