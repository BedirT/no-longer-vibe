"""Progress.json management for codebase reading sessions.

Manages `.codebase-guide/progress.json` — the persistent state for
reading sessions. Tracks which files have been read, their status,
notes, summaries, and session metadata.
"""

from __future__ import annotations

import json
import logging
import os
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

    def create(
        self,
        map_data: dict[str, Any],
        map_hash: str,
        *,
        force: bool = False,
    ) -> None:
        """Create a new progress.json from map data.

        Initialises all files from the map's reading_order as unread,
        sets session count to 1, and computes initial stats.

        Args:
            map_data: Parsed map.json content.
            map_hash: SHA-256 hex digest of the map.json file content.
            force: If True, overwrite existing progress.json.

        Raises:
            FileExistsError: If progress.json already exists and
                force is False.
        """
        if self._progress_path.exists() and not force:
            msg = (
                f"progress.json already exists at "
                f"{self._progress_path}. "
                "Use force=True to overwrite."
            )
            raise FileExistsError(msg)

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
            "next_unread_index": 0,
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
        The note field is always set to the provided value (None clears
        it). The summary field is preserved from the previous value
        unless explicitly provided.

        Args:
            path: File path as it appears in the reading order.
            status: New reading status.
            note: Note for this status (None clears any existing note).
            summary: One-line summary. If None, preserves existing.

        Raises:
            KeyError: If the file path is not in the progress data.
        """
        data = self._get_data()

        if path not in data["files"]:
            msg = f"File not tracked in progress: {path}"
            raise KeyError(msg)

        entry = data["files"][path]
        entry["status"] = status.value
        entry["note"] = note
        if summary is not None:
            entry["summary"] = summary
        if status is FileStatus.UNREAD:
            entry["read_at"] = None
        else:
            entry["read_at"] = _now_iso()

        data["stats"] = _compute_stats(data["files"])
        self._save()

    def compute_stats(self) -> dict[str, int]:
        """Compute current reading statistics from loaded data.

        Returns:
            Dict with keys: total, confirmed, flagged, skimmed, unread.
        """
        return _compute_stats(self._get_data()["files"])

    def start_session(self) -> None:
        """Record a new reading session.

        Increments the session counter and updates last_session
        timestamp. Preserves started_at.
        """
        data = self._get_data()
        data["sessions"] += 1
        data["last_session"] = _now_iso()
        self._save()

    def validate_map_hash(
        self, current_map_hash: str, *, strict: bool = False,
    ) -> bool:
        """Check if progress data matches the current map.json.

        Args:
            current_map_hash: SHA-256 hex digest of the current
                map.json.
            strict: If True, raise StaleMapError on mismatch instead
                of returning False.

        Returns:
            True if hashes match, False otherwise.

        Raises:
            StaleMapError: If strict is True and hashes don't match.
        """
        data = self._get_data()
        stored = str(data.get("map_hash", ""))
        matches = stored == current_map_hash
        if not matches and strict:
            stored_display = stored[:12] if stored else "<missing>"
            raise StaleMapError(
                f"Progress map_hash ({stored_display}...) does not "
                f"match current map ({current_map_hash[:12]}...)"
            )
        return matches

    def set_git_state(
        self,
        commit: str | None,
        branch: str | None,
    ) -> None:
        """Store the git commit and branch in progress data.

        Persists to disk atomically.

        Args:
            commit: Full SHA-1 of the git commit, or None to clear.
            branch: Branch name, or None to clear.
        """
        data = self._get_data()
        data["git_commit"] = commit
        data["git_branch"] = branch
        self._save()

    def get_git_state(self) -> tuple[str | None, str | None]:
        """Return the stored git commit and branch.

        Returns:
            Tuple of (commit, branch). Either may be None if not set.
        """
        data = self._get_data()
        commit: str | None = data.get("git_commit")
        branch: str | None = data.get("git_branch")
        return commit, branch

    def advance_pointer(
        self, reading_order_paths: list[str],
    ) -> None:
        """Advance next_unread_index to the next unread file.

        Scans forward from the current pointer position through
        *reading_order_paths* and sets the pointer to the first
        unread file's index.  When no unread files remain, sets
        the pointer to ``len(reading_order_paths)``.

        Persists the result to disk.

        Args:
            reading_order_paths: File paths in reading-order sequence.
        """
        data = self._get_data()
        files: dict[str, dict[str, Any]] = data.get("files", {})
        start: int = data.get("next_unread_index", 0)

        idx = start
        while idx < len(reading_order_paths):
            file_path = reading_order_paths[idx]
            entry = files.get(file_path)
            if entry and entry.get("status") == FileStatus.UNREAD.value:
                break
            idx += 1

        data["next_unread_index"] = idx
        self._save()

    def save(self) -> None:
        """Persist current in-memory progress data to disk.

        Delegates to the internal atomic-write implementation.
        Typically called after bulk modifications that bypass
        ``update_file`` (e.g. during a refresh operation).

        Raises:
            RuntimeError: If no data has been loaded or created.
        """
        self._save()

    def _get_data(self) -> dict[str, Any]:
        """Return loaded data, auto-loading from disk if needed.

        Raises:
            FileNotFoundError: If progress.json does not exist.
            RuntimeError: If data is still None after load attempt.
        """
        if self._data is None:
            self.load()
        if self._data is None:
            msg = "Failed to load progress data"
            raise RuntimeError(msg)
        return self._data

    def _save(self) -> None:
        """Atomically write progress data to disk.

        Writes to a temporary file in the same directory, then
        renames it to the target path. Uses fsync to ensure data
        reaches disk before the rename.
        """
        if self._data is None:
            msg = "No progress data to save"
            raise RuntimeError(msg)

        self._guide_dir.mkdir(parents=True, exist_ok=True)

        fd, tmp_path_str = tempfile.mkstemp(
            suffix=".tmp", dir=self._guide_dir,
        )
        tmp_path = Path(tmp_path_str)
        try:
            with open(fd, "w") as f:
                json.dump(self._data, f, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
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
        else:
            logger.warning("Unknown file status %r, counting as unread", status)
            counts["unread"] += 1
    return {"total": len(files), **counts}


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
