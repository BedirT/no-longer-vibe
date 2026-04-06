"""Tests for reading order configuration (BED-92).

Tests the ReadingConfig dataclass, config loading from TOML/JSON files,
default config behavior, validation, and integration with reading order
and layer classification.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from nlv.config import (
    ReadingConfig,
    TestFileMode,
    TieBreaking,
    load_config,
    validate_config,
)

# ---------------------------------------------------------------------------
# ReadingConfig defaults
# ---------------------------------------------------------------------------


class TestReadingConfigDefaults:
    """Tests that ReadingConfig has sensible defaults."""

    def test_default_skip_tests(self) -> None:
        cfg = ReadingConfig()
        assert cfg.skip_tests is False

    def test_default_test_pass(self) -> None:
        cfg = ReadingConfig()
        assert cfg.test_pass == TestFileMode.UTILITY

    def test_default_layer_thresholds(self) -> None:
        cfg = ReadingConfig()
        assert cfg.layer_thresholds == {
            "foundation": 0,
            "core": 1,
            "features": 2,
            "integration": 3,
        }

    def test_default_tie_breaking(self) -> None:
        cfg = ReadingConfig()
        assert cfg.tie_breaking == TieBreaking.ALPHABETICAL

    def test_default_custom_pass_overrides_empty(self) -> None:
        cfg = ReadingConfig()
        assert cfg.custom_pass_overrides == {}

    def test_default_integration_fan_in_threshold(self) -> None:
        cfg = ReadingConfig()
        assert cfg.integration_fan_in_threshold == 3


# ---------------------------------------------------------------------------
# TestFileMode enum
# ---------------------------------------------------------------------------


class TestTestFileModeEnum:
    """Tests for the TestFileMode enum."""

    def test_all_modes_exist(self) -> None:
        assert TestFileMode.CONTRACTS.value == "contracts"
        assert TestFileMode.DATA_FLOW.value == "data_flow"
        assert TestFileMode.UTILITY.value == "utility"
        assert TestFileMode.SEPARATE.value == "separate"
        assert TestFileMode.SKIP.value == "skip"

    def test_mode_count(self) -> None:
        assert len(TestFileMode) == 5


# ---------------------------------------------------------------------------
# TieBreaking enum
# ---------------------------------------------------------------------------


class TestTieBreakingEnum:
    """Tests for the TieBreaking enum."""

    def test_all_modes_exist(self) -> None:
        assert TieBreaking.ALPHABETICAL.value == "alphabetical"
        assert TieBreaking.FILE_SIZE.value == "file_size"
        assert TieBreaking.COMPLEXITY.value == "complexity"

    def test_mode_count(self) -> None:
        assert len(TieBreaking) == 3


# ---------------------------------------------------------------------------
# Config loading — JSON
# ---------------------------------------------------------------------------


class TestLoadConfigJson:
    """Tests for loading config from JSON files."""

    def test_load_from_json_file(self, tmp_path: Path) -> None:
        config_data = {
            "skip_tests": True,
            "test_pass": "separate",
            "tie_breaking": "file_size",
        }
        config_file = tmp_path / ".codebase-guide" / "config.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(json.dumps(config_data))

        cfg = load_config(tmp_path / ".codebase-guide")
        assert cfg.skip_tests is True
        assert cfg.test_pass == TestFileMode.SEPARATE
        assert cfg.tie_breaking == TieBreaking.FILE_SIZE

    def test_load_custom_pass_overrides_from_json(
        self, tmp_path: Path,
    ) -> None:
        config_data = {
            "custom_pass_overrides": {
                "src/types/**": "contracts",
                "src/utils/**": "utility",
            },
        }
        config_file = tmp_path / ".codebase-guide" / "config.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(json.dumps(config_data))

        cfg = load_config(tmp_path / ".codebase-guide")
        assert cfg.custom_pass_overrides == {
            "src/types/**": "contracts",
            "src/utils/**": "utility",
        }

    def test_load_layer_thresholds_from_json(self, tmp_path: Path) -> None:
        config_data = {
            "layer_thresholds": {
                "foundation": 0,
                "core": 1,
                "features": 3,
                "integration": 5,
            },
        }
        config_file = tmp_path / ".codebase-guide" / "config.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(json.dumps(config_data))

        cfg = load_config(tmp_path / ".codebase-guide")
        assert cfg.layer_thresholds["features"] == 3
        assert cfg.layer_thresholds["integration"] == 5

    def test_load_integration_fan_in_threshold(self, tmp_path: Path) -> None:
        config_data = {"integration_fan_in_threshold": 5}
        config_file = tmp_path / ".codebase-guide" / "config.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(json.dumps(config_data))

        cfg = load_config(tmp_path / ".codebase-guide")
        assert cfg.integration_fan_in_threshold == 5


# ---------------------------------------------------------------------------
# Config loading — TOML
# ---------------------------------------------------------------------------


class TestLoadConfigToml:
    """Tests for loading config from TOML files."""

    def test_load_from_toml_file(self, tmp_path: Path) -> None:
        toml_content = textwrap.dedent("""\
            skip_tests = true
            test_pass = "separate"
            tie_breaking = "complexity"
        """)
        config_file = tmp_path / ".codebase-guide" / "config.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(toml_content)

        cfg = load_config(tmp_path / ".codebase-guide")
        assert cfg.skip_tests is True
        assert cfg.test_pass == TestFileMode.SEPARATE
        assert cfg.tie_breaking == TieBreaking.COMPLEXITY

    def test_load_custom_pass_overrides_from_toml(
        self, tmp_path: Path,
    ) -> None:
        toml_content = textwrap.dedent("""\
            [custom_pass_overrides]
            "src/types/**" = "contracts"
            "src/utils/**" = "utility"
        """)
        config_file = tmp_path / ".codebase-guide" / "config.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(toml_content)

        cfg = load_config(tmp_path / ".codebase-guide")
        assert cfg.custom_pass_overrides["src/types/**"] == "contracts"

    def test_toml_takes_precedence_over_json(self, tmp_path: Path) -> None:
        """When both config.toml and config.json exist, TOML wins."""
        guide_dir = tmp_path / ".codebase-guide"
        guide_dir.mkdir(parents=True)

        json_file = guide_dir / "config.json"
        json_file.write_text(json.dumps({"skip_tests": False}))

        toml_file = guide_dir / "config.toml"
        toml_file.write_text('skip_tests = true\n')

        cfg = load_config(guide_dir)
        assert cfg.skip_tests is True


# ---------------------------------------------------------------------------
# Config loading — defaults (no file)
# ---------------------------------------------------------------------------


class TestLoadConfigDefaults:
    """Tests for default config when no file is present."""

    def test_no_config_file_returns_defaults(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / ".codebase-guide"
        guide_dir.mkdir(parents=True)

        cfg = load_config(guide_dir)
        default = ReadingConfig()
        assert cfg.skip_tests == default.skip_tests
        assert cfg.test_pass == default.test_pass
        assert cfg.tie_breaking == default.tie_breaking
        assert cfg.layer_thresholds == default.layer_thresholds
        assert cfg.custom_pass_overrides == default.custom_pass_overrides

    def test_nonexistent_directory_returns_defaults(
        self, tmp_path: Path,
    ) -> None:
        cfg = load_config(tmp_path / "nonexistent")
        default = ReadingConfig()
        assert cfg == default

    def test_partial_json_fills_defaults(self, tmp_path: Path) -> None:
        """Only specified fields override; others stay default."""
        config_data = {"skip_tests": True}
        config_file = tmp_path / ".codebase-guide" / "config.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(json.dumps(config_data))

        cfg = load_config(tmp_path / ".codebase-guide")
        assert cfg.skip_tests is True
        # Remaining fields at default
        assert cfg.test_pass == TestFileMode.UTILITY
        assert cfg.tie_breaking == TieBreaking.ALPHABETICAL


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


class TestValidateConfig:
    """Tests for config validation."""

    def test_valid_config_no_error(self) -> None:
        cfg = ReadingConfig()
        validate_config(cfg)  # Should not raise

    def test_invalid_test_pass_value(self, tmp_path: Path) -> None:
        config_data = {"test_pass": "invalid_value"}
        config_file = tmp_path / ".codebase-guide" / "config.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(json.dumps(config_data))

        with pytest.raises(ValueError, match="test_pass"):
            load_config(tmp_path / ".codebase-guide")

    def test_invalid_tie_breaking_value(self, tmp_path: Path) -> None:
        config_data = {"tie_breaking": "random"}
        config_file = tmp_path / ".codebase-guide" / "config.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(json.dumps(config_data))

        with pytest.raises(ValueError, match="tie_breaking"):
            load_config(tmp_path / ".codebase-guide")

    def test_invalid_custom_pass_override_value(
        self, tmp_path: Path,
    ) -> None:
        config_data = {
            "custom_pass_overrides": {"src/**": "invalid_pass"},
        }
        config_file = tmp_path / ".codebase-guide" / "config.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(json.dumps(config_data))

        with pytest.raises(ValueError, match="custom_pass_overrides"):
            load_config(tmp_path / ".codebase-guide")

    def test_negative_layer_threshold(self) -> None:
        cfg = ReadingConfig(
            layer_thresholds={
                "foundation": -1,
                "core": 1,
                "features": 2,
                "integration": 3,
            },
        )
        with pytest.raises(ValueError, match="layer_thresholds"):
            validate_config(cfg)

    def test_negative_integration_fan_in_threshold(self) -> None:
        cfg = ReadingConfig(integration_fan_in_threshold=-1)
        with pytest.raises(ValueError, match="integration_fan_in_threshold"):
            validate_config(cfg)


# ---------------------------------------------------------------------------
# Custom pass overrides with glob matching
# ---------------------------------------------------------------------------


class TestCustomPassOverrides:
    """Tests for glob-based custom pass overrides."""

    def test_glob_match_assigns_pass(self) -> None:
        """A file matching a glob override should get that pass."""
        cfg = ReadingConfig(
            custom_pass_overrides={"src/types/**": "contracts"},
        )
        # The match_custom_pass_override helper should resolve this
        from nlv.config import match_custom_pass_override
        result = match_custom_pass_override("src/types/user.py", cfg)
        assert result == "contracts"

    def test_no_match_returns_none(self) -> None:
        cfg = ReadingConfig(
            custom_pass_overrides={"src/types/**": "contracts"},
        )
        from nlv.config import match_custom_pass_override
        result = match_custom_pass_override("src/models/user.py", cfg)
        assert result is None

    def test_first_matching_glob_wins(self) -> None:
        """When multiple globs match, the first (sorted) wins."""
        cfg = ReadingConfig(
            custom_pass_overrides={
                "src/**": "data_flow",
                "src/types/**": "contracts",
            },
        )
        from nlv.config import match_custom_pass_override
        # "src/**" sorts before "src/types/**", so it wins
        result = match_custom_pass_override("src/types/user.py", cfg)
        assert result == "data_flow"


# ---------------------------------------------------------------------------
# exclude_from_reading
# ---------------------------------------------------------------------------


class TestExcludeFromReading:
    """Tests for the exclude_from_reading config option."""

    def test_default_is_empty(self) -> None:
        cfg = ReadingConfig()
        assert cfg.exclude_from_reading == ()

    def test_custom_patterns(self) -> None:
        cfg = ReadingConfig(
            exclude_from_reading=("**/__init__.py", "**/__main__.py"),
        )
        assert len(cfg.exclude_from_reading) == 2

    def test_load_from_json(self, tmp_path: Path) -> None:
        guide = tmp_path / ".codebase-guide"
        guide.mkdir()
        (guide / "config.json").write_text(json.dumps({
            "exclude_from_reading": ["**/__init__.py"],
        }))
        cfg = load_config(guide)
        assert cfg.exclude_from_reading == ("**/__init__.py",)

    def test_load_from_toml(self, tmp_path: Path) -> None:
        guide = tmp_path / ".codebase-guide"
        guide.mkdir()
        (guide / "config.toml").write_text(textwrap.dedent("""\
            exclude_from_reading = ["**/__init__.py", "conftest.py"]
        """))
        cfg = load_config(guide)
        assert cfg.exclude_from_reading == ("**/__init__.py", "conftest.py")

    def test_missing_key_defaults_to_empty(self, tmp_path: Path) -> None:
        guide = tmp_path / ".codebase-guide"
        guide.mkdir()
        (guide / "config.json").write_text(json.dumps({
            "skip_tests": False,
        }))
        cfg = load_config(guide)
        assert cfg.exclude_from_reading == ()
