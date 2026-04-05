"""Tests for content hashing module (BED-69).

Tests SHA-256 content hashing for staleness detection.
Hash is computed on file content only (not path or metadata),
and truncated to the first 8 hex characters.
"""

from __future__ import annotations

import pathlib

import pytest

from nlv.hashing import compute_content_hash, compute_content_hashes


class TestComputeContentHash:
    """Tests for single-file content hashing."""

    def test_returns_hex_string(self, tmp_path: pathlib.Path) -> None:
        """Hash is a hex-encoded string."""
        f = tmp_path / "file.py"
        f.write_text("hello world\n")
        result = compute_content_hash(f)
        assert isinstance(result, str)
        # Must be valid hex
        int(result, 16)

    def test_truncated_to_8_chars(self, tmp_path: pathlib.Path) -> None:
        """Hash is truncated to 8 hex characters as specified in SPEC.md."""
        f = tmp_path / "file.py"
        f.write_text("content\n")
        result = compute_content_hash(f)
        assert len(result) == 8

    def test_deterministic(self, tmp_path: pathlib.Path) -> None:
        """Same content always produces the same hash."""
        f = tmp_path / "file.py"
        f.write_text("deterministic\n")
        h1 = compute_content_hash(f)
        h2 = compute_content_hash(f)
        assert h1 == h2

    def test_same_content_different_paths(
        self, tmp_path: pathlib.Path,
    ) -> None:
        """Files with identical content produce the same hash regardless of path."""
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        content = "identical content\n"
        f1.write_text(content)
        f2.write_text(content)
        assert compute_content_hash(f1) == compute_content_hash(f2)

    def test_different_content_different_hash(
        self, tmp_path: pathlib.Path,
    ) -> None:
        """Files with different content produce different hashes."""
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text("content A\n")
        f2.write_text("content B\n")
        assert compute_content_hash(f1) != compute_content_hash(f2)

    def test_hashes_content_not_filename(
        self, tmp_path: pathlib.Path,
    ) -> None:
        """Renaming a file does not change its hash (content-based)."""
        f = tmp_path / "original.py"
        f.write_text("stable content\n")
        h1 = compute_content_hash(f)

        renamed = tmp_path / "renamed.py"
        f.rename(renamed)
        h2 = compute_content_hash(renamed)
        assert h1 == h2

    def test_empty_file(self, tmp_path: pathlib.Path) -> None:
        """Empty file produces a valid 8-char hash."""
        f = tmp_path / "empty.py"
        f.write_text("")
        result = compute_content_hash(f)
        assert len(result) == 8
        int(result, 16)

    def test_binary_content(self, tmp_path: pathlib.Path) -> None:
        """Binary file content is hashed correctly."""
        f = tmp_path / "data.bin"
        f.write_bytes(b"\x00\x01\x02\xff")
        result = compute_content_hash(f)
        assert len(result) == 8
        int(result, 16)

    def test_file_not_found_raises(self, tmp_path: pathlib.Path) -> None:
        """Raises FileNotFoundError for nonexistent files."""
        missing = tmp_path / "nonexistent.py"
        with pytest.raises(FileNotFoundError):
            compute_content_hash(missing)

    def test_known_sha256_value(self, tmp_path: pathlib.Path) -> None:
        """Verify against a known SHA-256 value to confirm algorithm."""
        f = tmp_path / "known.txt"
        # SHA-256 of empty bytes is:
        # e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
        f.write_bytes(b"")
        result = compute_content_hash(f)
        assert result == "e3b0c442"


class TestComputeContentHashes:
    """Tests for batch content hashing."""

    def test_returns_dict(self, tmp_path: pathlib.Path) -> None:
        """Batch function returns a dict mapping path to hash."""
        f = tmp_path / "file.py"
        f.write_text("content\n")
        result = compute_content_hashes([f])
        assert isinstance(result, dict)

    def test_keys_are_string_paths(self, tmp_path: pathlib.Path) -> None:
        """Dict keys are string representations of the paths."""
        f = tmp_path / "file.py"
        f.write_text("content\n")
        result = compute_content_hashes([f])
        for key in result:
            assert isinstance(key, str)

    def test_values_are_truncated_hashes(
        self, tmp_path: pathlib.Path,
    ) -> None:
        """Each value is an 8-char truncated hex hash."""
        f = tmp_path / "file.py"
        f.write_text("content\n")
        result = compute_content_hashes([f])
        for val in result.values():
            assert len(val) == 8
            int(val, 16)

    def test_multiple_files(self, tmp_path: pathlib.Path) -> None:
        """Batch hashing processes multiple files."""
        files = []
        for i in range(5):
            f = tmp_path / f"file_{i}.py"
            f.write_text(f"content {i}\n")
            files.append(f)
        result = compute_content_hashes(files)
        assert len(result) == 5

    def test_empty_list(self) -> None:
        """Empty input returns empty dict."""
        result = compute_content_hashes([])
        assert result == {}

    def test_consistent_with_single_hash(
        self, tmp_path: pathlib.Path,
    ) -> None:
        """Batch result matches individual compute_content_hash calls."""
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text("alpha\n")
        f2.write_text("beta\n")

        batch = compute_content_hashes([f1, f2])
        assert batch[str(f1)] == compute_content_hash(f1)
        assert batch[str(f2)] == compute_content_hash(f2)

    def test_relative_path_keys(self, tmp_path: pathlib.Path) -> None:
        """When given a root, keys are relative paths."""
        (tmp_path / "src").mkdir()
        f = tmp_path / "src" / "app.py"
        f.write_text("content\n")
        result = compute_content_hashes([f], root=tmp_path)
        assert "src/app.py" in result

    def test_absolute_path_keys_without_root(
        self, tmp_path: pathlib.Path,
    ) -> None:
        """Without a root, keys are absolute path strings."""
        f = tmp_path / "file.py"
        f.write_text("content\n")
        result = compute_content_hashes([f])
        assert str(f) in result

    def test_skips_missing_files(self, tmp_path: pathlib.Path) -> None:
        """Missing files are skipped with a warning, not raising."""
        existing = tmp_path / "exists.py"
        existing.write_text("ok\n")
        missing = tmp_path / "gone.py"
        result = compute_content_hashes([existing, missing])
        assert str(existing) in result
        assert str(missing) not in result
