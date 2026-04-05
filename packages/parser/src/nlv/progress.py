"""Progress.json management for codebase reading sessions.

Manages `.codebase-guide/progress.json` — the persistent state for
reading sessions. Tracks which files have been read, their status,
notes, summaries, and session metadata.
"""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_VERSION = "1.0.0"


class FileStatus(Enum):
    """Reading status for a tracked file."""

    CONFIRMED = "confirmed"
    FLAGGED = "flagged"
    SKIMMED = "skimmed"
    UNREAD = "unread"


class StaleMapError(Exception):
    """Raised when progress.json's map_hash doesn't match the current map."""


class ProgressManager:
    """Create, load, update, and query progress.json.

    Args:
        guide_dir: Path to the `.codebase-guide` directory.
    """

    def __init__(self, guide_dir: Path) -> None:
        self._guide_dir = guide_dir
        self._progress_path = guide_dir / "progress.json"
        self._data: dict[str, Any] | None = None

    def create(self, map_data: dict[str, Any], map_hash: str) -> None:
        """Create a new progress.json from map data.

        Initialises all files from the map's reading_order as unread,
        sets session count to 1, and computes initial stats.

        Args:
            map_data: Parsed map.json content.
            map_hash: SHA-256 hex digest of the map.json file content.
        """
        now = _now_iso()
        files: dict[str, dict[str, Any]] = {}
        for entry in map_data.get("reading_order", []):
            path = entry["path"]
            files[path] = {
                "status": FileStatus.UNREAD.value,
                "read_at": None,
                "note": None,
                "summary": None,
            }

        self._data = {
            "version": _VERSION,
            "map_hash": map_hash,
            "started_at": now,
            "last_session": now,
            "sessions": 1,
            "files": files,
            "stats": _compute_stats(files),
        }
        self._save()

    def load(self) -> dict[str, Any]:
        """Load progress.json from disk.

        Returns:
            The parsed progress data.

        Raises:
            FileNotFoundError: If progress.json does not exist.
            json.JSONDecodeError: If the file contains invalid JSON.
        """
        raw = self._progress_path.read_text()
        data: dict[str, Any] = json.loads(raw)
        self._data = data
        return data

    def update_file(
        self,
        path: str,
        *,
        status: FileStatus,
        note: str | None = None,
        summary: str | None = None,
    ) -> None:
        """Update a file's reading status.

        Persists the change to disk atomically and recalculates stats.

        Args:
            path: File path as it appears in the reading order.
            status: New reading status.
            note: Optional note (typically used with flagged status).
            summary: Optional one-line summary of the file.

        Raises:
            KeyError: If the file path is not in the progress data.
        """
        self._ensure_loaded()
        assert self._data is not None

        if path not in self._data["files"]:
            msg = f"File not tracked in progress: {path}"
            raise KeyError(msg)

        entry = self._data["files"][path]
        entry["status"] = status.value
        if note is not None:
            entry["note"] = note
        if summary is not None:
            entry["summary"] = summary
        if status is not FileStatus.UNREAD:
            entry["read_at"] = _now_iso()

        self._data["stats"] = _compute_stats(self._data["files"])
        self._save()

    def compute_stats(self) -> dict[str, int]:
        """Compute current reading statistics from loaded data.

        Returns:
            Dict with keys: total, confirmed, flagged, skimmed, unread.
        """
        self._ensure_loaded()
        assert self._data is not None
        return _compute_stats(self._data["files"])

    def start_session(self) -> None:
        """Record a new reading session.

        Increments the session counter and updates last_session timestamp.
        Preserves started_at.
        """
        self._ensure_loaded()
        assert self._data is not None

        self._data["sessions"] += 1
        self._data["last_session"] = _now_iso()
        self._save()

    def validate_map_hash(
        self, current_map_hash: str, *, strict: bool = False,
    ) -> bool:
        """Check if progress data matches the current map.json.

        Args:
            current_map_hash: SHA-256 hex digest of the current map.json.
            strict: If True, raise StaleMapError on mismatch instead of
                returning False.

        Returns:
            True if hashes match, False otherwise.

        Raises:
            StaleMapError: If strict is True and hashes don't match.
        """
        self._ensure_loaded()
        assert self._data is not None

        matches = self._data["map_hash"] == current_map_hash
        if not matches and strict:
            raise StaleMapError(
                f"Progress map_hash ({self._data['map_hash'][:12]}...) "
                f"does not match current map ({current_map_hash[:12]}...)"
            )
        return matches

    def _ensure_loaded(self) -> None:
        """Load progress data if not already in memory."""
        if self._data is None:
            self.load()

    def _save(self) -> None:
        """Atomically write progress data to disk.

        Writes to a temporary file in the same directory, then renames
        it to the target path. This prevents partial writes.
        """
        assert self._data is not None
        self._guide_dir.mkdir(parents=True, exist_ok=True)

        fd, tmp_path_str = tempfile.mkstemp(
            suffix=".tmp", dir=self._guide_dir,
        )
        tmp_path = Path(tmp_path_str)
        try:
            with open(fd, "w") as f:
                json.dump(self._data, f, indent=2)
                f.write("\n")
            tmp_path.replace(self._progress_path)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise


def _compute_stats(files: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Compute status counts from file entries."""
    counts = {"confirmed": 0, "flagged": 0, "skimmed": 0, "unread": 0}
    for entry in files.values():
        status = entry["status"]
        if status in counts:
            counts[status] += 1
    return {"total": len(files), **counts}


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
