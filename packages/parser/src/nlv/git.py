"""Git operations for progress tracking (BED-150).

Thin wrappers around git CLI commands for detecting repository state,
retrieving commit hashes, and computing file-level diffs between commits.
All functions return ``None`` on failure rather than raising, so callers
can fall back to non-git strategies gracefully.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 30


def is_git_repo(path: Path) -> bool:
    """Check whether *path* is inside a git working tree.

    Args:
        path: Directory to check.

    Returns:
        True if the path is inside a git repository.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=path,
            capture_output=True,
            text=True,
            check=False,
            timeout=_TIMEOUT_SECONDS,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except (OSError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def get_head_commit(repo_root: Path) -> str | None:
    """Return the full SHA-1 of HEAD, or ``None`` if unavailable.

    Args:
        repo_root: Path inside the git repository.

    Returns:
        40-character lowercase hex string, or None.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None
        commit = result.stdout.strip()
        if len(commit) == 40:
            return commit
        return None
    except (OSError, FileNotFoundError, subprocess.TimeoutExpired):
        return None


def get_current_branch(repo_root: Path) -> str | None:
    """Return the current branch name, or ``None`` for detached HEAD / non-git.

    Args:
        repo_root: Path inside the git repository.

    Returns:
        Branch name string, or None.
    """
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None
        branch = result.stdout.strip()
        return branch if branch else None
    except (OSError, FileNotFoundError, subprocess.TimeoutExpired):
        return None


def commit_exists(repo_root: Path, commit_hash: str) -> bool:
    """Check whether a commit object exists in the repository.

    Args:
        repo_root: Path inside the git repository.
        commit_hash: Commit hash to verify.

    Returns:
        True if the commit exists and is a valid commit object.
    """
    if not commit_hash or commit_hash.startswith("-"):
        return False
    try:
        result = subprocess.run(
            ["git", "cat-file", "-t", commit_hash],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=_TIMEOUT_SECONDS,
        )
        return (
            result.returncode == 0
            and result.stdout.strip() == "commit"
        )
    except (OSError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def diff_name_status(
    repo_root: Path,
    from_commit: str,
    to_commit: str = "HEAD",
) -> list[tuple[str, ...]] | None:
    """Run ``git diff --name-status`` between two commits.

    Each entry is a tuple of ``(status, path)`` for simple statuses
    (A, M, D). Renames are disabled (``--no-renames``) so they appear
    as separate D + A entries.

    Args:
        repo_root: Path inside the git repository.
        from_commit: Base commit hash.
        to_commit: Target commit (defaults to HEAD).

    Returns:
        List of status tuples, or None if the diff cannot be computed
        (missing commit, non-git repo, etc.).
    """
    try:
        result = subprocess.run(
            [
                "git", "diff", "--name-status",
                "--no-renames",
                f"{from_commit}..{to_commit}",
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            logger.debug(
                "git diff failed (rc=%d): %s",
                result.returncode, result.stderr.strip(),
            )
            return None

        entries: list[tuple[str, ...]] = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                entries.append(tuple(parts))
        return entries
    except (OSError, FileNotFoundError, subprocess.TimeoutExpired):
        return None
