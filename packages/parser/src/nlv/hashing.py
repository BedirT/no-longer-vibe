"""Content hashing — SHA-256 for staleness detection.

Computes SHA-256 content hashes for source files. Hashes are based
on file content only (not path or metadata) and truncated to 8 hex
characters, matching the ``content_hashes`` field in map.json.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_HASH_LENGTH = 8
_READ_CHUNK = 65536


def compute_content_hash(path: Path) -> str:
    """Compute a truncated SHA-256 hash of a file's content.

    Reads the file in binary mode and hashes its raw bytes.
    The result is the first 8 characters of the hex digest.

    Args:
        path: Path to the file to hash.

    Returns:
        8-character hex string (e.g. ``"a3f2b8c1"``).

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(_READ_CHUNK)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()[:_HASH_LENGTH]


def compute_content_hashes(
    paths: list[Path],
    *,
    root: Path | None = None,
) -> dict[str, str]:
    """Compute content hashes for multiple files.

    Args:
        paths: List of file paths to hash.
        root: Optional root directory. When provided, dict keys are
            paths relative to root (using forward slashes). When
            omitted, keys are absolute path strings.

    Returns:
        Dict mapping path strings to 8-char hex hashes.
        Missing files are skipped with a warning.
    """
    result: dict[str, str] = {}
    for path in paths:
        try:
            file_hash = compute_content_hash(path)
        except FileNotFoundError:
            logger.warning("File not found, skipping: %s", path)
            continue

        if root is not None:
            key = path.relative_to(root).as_posix()
        else:
            key = str(path)

        result[key] = file_hash
    return result
