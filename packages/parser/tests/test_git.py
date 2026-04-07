"""Tests for git operations module (BED-150).

Covers: repo detection, HEAD commit retrieval, branch name, commit
existence checks, and diff --name-status parsing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from nlv.git import (
    commit_exists,
    diff_name_status,
    get_current_branch,
    get_head_commit,
    is_git_repo,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with one commit containing a.py and b.py."""
    subprocess.run(
        ["git", "init", "--initial-branch=main"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    (tmp_path / "a.py").write_text("# file a\n")
    (tmp_path / "b.py").write_text("# file b\n")
    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    return tmp_path


def _git_commit(repo: Path, msg: str) -> str:
    """Stage all changes and commit. Return the new commit hash."""
    subprocess.run(
        ["git", "add", "."],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=repo, capture_output=True, check=True,
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# is_git_repo
# ---------------------------------------------------------------------------


class TestIsGitRepo:
    """Detecting whether a path is inside a git repository."""

    def test_returns_true_for_git_repo(self, git_repo: Path) -> None:
        assert is_git_repo(git_repo) is True

    def test_returns_false_for_non_git_directory(self, tmp_path: Path) -> None:
        assert is_git_repo(tmp_path) is False

    def test_returns_true_for_subdirectory(self, git_repo: Path) -> None:
        subdir = git_repo / "subdir"
        subdir.mkdir()
        assert is_git_repo(subdir) is True


# ---------------------------------------------------------------------------
# get_head_commit
# ---------------------------------------------------------------------------


class TestGetHeadCommit:
    """Retrieving the current HEAD commit hash."""

    def test_returns_40_char_hex_hash(self, git_repo: Path) -> None:
        commit = get_head_commit(git_repo)
        assert commit is not None
        assert len(commit) == 40
        assert all(c in "0123456789abcdef" for c in commit)

    def test_returns_none_for_non_git(self, tmp_path: Path) -> None:
        assert get_head_commit(tmp_path) is None


# ---------------------------------------------------------------------------
# get_current_branch
# ---------------------------------------------------------------------------


class TestGetCurrentBranch:
    """Retrieving the current branch name."""

    def test_returns_branch_name(self, git_repo: Path) -> None:
        branch = get_current_branch(git_repo)
        assert branch == "main"

    def test_returns_none_for_non_git(self, tmp_path: Path) -> None:
        assert get_current_branch(tmp_path) is None

    def test_returns_none_for_detached_head(self, git_repo: Path) -> None:
        subprocess.run(
            ["git", "checkout", "--detach"],
            cwd=git_repo, capture_output=True, check=True,
        )
        assert get_current_branch(git_repo) is None


# ---------------------------------------------------------------------------
# commit_exists
# ---------------------------------------------------------------------------


class TestCommitExists:
    """Verifying whether a commit hash exists in the repo."""

    def test_existing_commit_returns_true(self, git_repo: Path) -> None:
        commit = get_head_commit(git_repo)
        assert commit is not None
        assert commit_exists(git_repo, commit) is True

    def test_nonexistent_commit_returns_false(self, git_repo: Path) -> None:
        assert commit_exists(git_repo, "0" * 40) is False

    def test_non_git_repo_returns_false(self, tmp_path: Path) -> None:
        assert commit_exists(tmp_path, "abc123") is False


# ---------------------------------------------------------------------------
# diff_name_status
# ---------------------------------------------------------------------------


class TestDiffNameStatus:
    """Parsing git diff --name-status output."""

    def test_detects_added_file(self, git_repo: Path) -> None:
        commit_before = get_head_commit(git_repo)
        assert commit_before is not None
        (git_repo / "c.py").write_text("# new file\n")
        _git_commit(git_repo, "add c.py")

        result = diff_name_status(git_repo, commit_before)
        assert result is not None
        assert ("A", "c.py") in result

    def test_detects_modified_file(self, git_repo: Path) -> None:
        commit_before = get_head_commit(git_repo)
        assert commit_before is not None
        (git_repo / "a.py").write_text("# modified content\n")
        _git_commit(git_repo, "modify a.py")

        result = diff_name_status(git_repo, commit_before)
        assert result is not None
        assert ("M", "a.py") in result

    def test_detects_deleted_file(self, git_repo: Path) -> None:
        commit_before = get_head_commit(git_repo)
        assert commit_before is not None
        (git_repo / "a.py").unlink()
        _git_commit(git_repo, "delete a.py")

        result = diff_name_status(git_repo, commit_before)
        assert result is not None
        assert ("D", "a.py") in result

    def test_multiple_changes(self, git_repo: Path) -> None:
        commit_before = get_head_commit(git_repo)
        assert commit_before is not None
        (git_repo / "a.py").write_text("# changed\n")
        (git_repo / "b.py").unlink()
        (git_repo / "c.py").write_text("# new\n")
        _git_commit(git_repo, "multiple changes")

        result = diff_name_status(git_repo, commit_before)
        assert result is not None
        statuses = {path: status for status, path in result}
        assert statuses["a.py"] == "M"
        assert statuses["b.py"] == "D"
        assert statuses["c.py"] == "A"

    def test_no_changes_returns_empty_list(self, git_repo: Path) -> None:
        commit = get_head_commit(git_repo)
        assert commit is not None
        result = diff_name_status(git_repo, commit)
        assert result is not None
        assert result == []

    def test_returns_none_for_missing_commit(self, git_repo: Path) -> None:
        result = diff_name_status(git_repo, "0" * 40)
        assert result is None

    def test_returns_none_for_non_git_repo(self, tmp_path: Path) -> None:
        result = diff_name_status(tmp_path, "abc123")
        assert result is None

    def test_detects_file_in_subdirectory(self, git_repo: Path) -> None:
        commit_before = get_head_commit(git_repo)
        assert commit_before is not None
        subdir = git_repo / "src"
        subdir.mkdir()
        (subdir / "new.py").write_text("# in subdir\n")
        _git_commit(git_repo, "add src/new.py")

        result = diff_name_status(git_repo, commit_before)
        assert result is not None
        assert ("A", "src/new.py") in result
