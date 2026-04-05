"""/read-status command output formatting (BED-76).

Reads map.json and progress.json from the `.codebase-guide` directory,
computes reading statistics, and returns a formatted progress report.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def format_read_status(guide_dir: Path) -> str:
    """Produce the /read-status progress report.

    Reads map.json and progress.json, computes per-status breakdown,
    current layer completion, next file in queue, flagged count,
    session count, and average pace.

    Args:
        guide_dir: Path to the `.codebase-guide` directory.

    Returns:
        Formatted progress report string.
    """
    map_path = guide_dir / "map.json"
    progress_path = guide_dir / "progress.json"

    if not map_path.exists():
        return "No map.json found. Run /read-index first."

    map_data = _load_json(map_path)

    if not progress_path.exists():
        return "No progress.json found. Start reading with /read-next."

    progress_data = _load_json(progress_path)

    stats = _compute_stats(progress_data)
    layer_info = _compute_current_layer(map_data, progress_data)
    next_file = _find_next_file(map_data, progress_data)
    session_info = _compute_session_info(progress_data, stats)

    return _render_report(stats, layer_info, next_file, session_info)


def _load_json(path: Path) -> dict[str, Any]:
    """Load and parse a JSON file.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed JSON data.
    """
    raw = path.read_text()
    result: dict[str, Any] = json.loads(raw)
    return result


def _compute_stats(
    progress_data: dict[str, Any],
) -> dict[str, int]:
    """Compute per-status counts from progress data.

    Args:
        progress_data: Parsed progress.json content.

    Returns:
        Dict with total, confirmed, flagged, skimmed, unread counts.
    """
    files: dict[str, dict[str, Any]] = progress_data.get("files", {})
    counts = {"confirmed": 0, "flagged": 0, "skimmed": 0, "unread": 0}
    for entry in files.values():
        status = entry.get("status", "unread")
        if status in counts:
            counts[status] += 1
        else:
            counts["unread"] += 1
    return {"total": len(files), **counts}


def _compute_current_layer(
    map_data: dict[str, Any],
    progress_data: dict[str, Any],
) -> dict[str, Any]:
    """Determine the current layer and its completion percentage.

    The current layer is the first layer (in map order) that has
    at least one unread file. If all layers are complete, returns
    a sentinel indicating completion.

    Args:
        map_data: Parsed map.json content.
        progress_data: Parsed progress.json content.

    Returns:
        Dict with "name", "pct" keys, or "complete": True.
    """
    layers: dict[str, dict[str, Any]] = map_data.get("layers", {})
    files: dict[str, dict[str, Any]] = progress_data.get("files", {})

    for layer_name, layer_data in layers.items():
        layer_files = layer_data.get("files", [])
        if not layer_files:
            continue

        read_count = _count_read_in_list(layer_files, files)
        total = len(layer_files)

        if read_count < total:
            pct = round(read_count / total * 100)
            return {"name": layer_name, "pct": pct}

    return {"complete": True}


def _count_read_in_list(
    file_list: list[str],
    files: dict[str, dict[str, Any]],
) -> int:
    """Count how many files in a list have been read.

    A file is "read" if its status is not "unread".

    Args:
        file_list: List of file paths to check.
        files: Progress file entries.

    Returns:
        Number of read files.
    """
    count = 0
    for filepath in file_list:
        entry = files.get(filepath)
        if entry and entry.get("status") != "unread":
            count += 1
    return count


def _find_next_file(
    map_data: dict[str, Any],
    progress_data: dict[str, Any],
) -> str | None:
    """Find the next unread file in reading order.

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

    for entry in reading_order:
        path = entry["path"]
        file_entry = files.get(path)
        if file_entry and file_entry.get("status") == "unread":
            return path

    return None


def _compute_session_info(
    progress_data: dict[str, Any],
    stats: dict[str, int],
) -> dict[str, int]:
    """Compute session count and average pace.

    Args:
        progress_data: Parsed progress.json content.
        stats: Pre-computed status counts.

    Returns:
        Dict with "sessions" and "avg_pace" keys.
    """
    sessions: int = progress_data.get("sessions", 1)
    files_read = (
        stats["confirmed"] + stats["flagged"] + stats["skimmed"]
    )

    if sessions > 0:
        avg_pace = round(files_read / sessions)
    else:
        avg_pace = 0

    return {"sessions": sessions, "avg_pace": avg_pace}


def _render_report(
    stats: dict[str, int],
    layer_info: dict[str, Any],
    next_file: str | None,
    session_info: dict[str, int],
) -> str:
    """Render the formatted progress report.

    Args:
        stats: Per-status counts.
        layer_info: Current layer info or completion sentinel.
        next_file: Next file path or None.
        session_info: Session count and average pace.

    Returns:
        Formatted multi-line progress report.
    """
    files_read = (
        stats["confirmed"] + stats["flagged"] + stats["skimmed"]
    )
    total = stats["total"]
    pct = round(files_read / total * 100) if total > 0 else 0

    lines: list[str] = []

    # Progress summary
    lines.append(f"Progress: {files_read}/{total} files ({pct}%)")
    lines.append(f"  confirmed: {stats['confirmed']}")
    lines.append(f"  flagged: {stats['flagged']}")
    lines.append(f"  skimmed: {stats['skimmed']}")
    lines.append(f"  unread: {stats['unread']}")

    # Blank line separator
    lines.append("")

    # Current layer
    if layer_info.get("complete"):
        lines.append("All layers complete")
    else:
        name = layer_info["name"]
        layer_pct = layer_info["pct"]
        lines.append(
            f"Current layer: {name} ({layer_pct}% complete)",
        )

    # Next file
    if next_file is not None:
        lines.append(f"Next file: {next_file}")
    else:
        lines.append("Next file: (none -- all files read)")

    # Flagged awaiting
    lines.append(
        f"Flagged files awaiting second pass: {stats['flagged']}",
    )

    # Blank line separator
    lines.append("")

    # Sessions and pace
    sessions = session_info["sessions"]
    avg_pace = session_info["avg_pace"]
    lines.append(
        f"Sessions: {sessions} | Avg pace: ~{avg_pace} files/session",
    )

    return "\n".join(lines)
