"""Reading order configuration (BED-92).

Defines a ``ReadingConfig`` dataclass with configurable parameters for
reading order heuristics: test file handling, tie-breaking strategy,
layer thresholds, and per-file/per-glob pass overrides.

Configuration is loaded from ``.codebase-guide/config.toml`` or
``.codebase-guide/config.json`` when present, falling back to sensible
defaults that match the existing behavior.
"""

from __future__ import annotations

import enum
import json
import logging
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import cast

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TestFileMode(enum.Enum):
    """Where to place test files in the reading order.

    - ``CONTRACTS``: Put unpaired tests in the contracts pass.
    - ``DATA_FLOW``: Put unpaired tests in the data flow pass.
    - ``UTILITY``: Put unpaired tests in the utility pass (default).
    - ``SEPARATE``: Put all tests in a separate fourth pass after all
      non-test files.
    - ``SKIP``: Exclude test files entirely from the reading order.
    """

    CONTRACTS = "contracts"
    DATA_FLOW = "data_flow"
    UTILITY = "utility"
    SEPARATE = "separate"
    SKIP = "skip"


class TieBreaking(enum.Enum):
    """Strategy for breaking ties in topological sort.

    - ``ALPHABETICAL``: Break ties by file path (default — deterministic).
    - ``FILE_SIZE``: Break ties by file size (smaller first). Not yet implemented.
    - ``COMPLEXITY``: Break ties by complexity (lower first). Not yet implemented.

    Note: Only ALPHABETICAL is currently wired into the sort logic.
    FILE_SIZE and COMPLEXITY are defined for future use.
    """

    ALPHABETICAL = "alphabetical"
    FILE_SIZE = "file_size"
    COMPLEXITY = "complexity"


# ---------------------------------------------------------------------------
# Default layer thresholds
# ---------------------------------------------------------------------------

_DEFAULT_LAYER_THRESHOLDS: dict[str, int] = {
    "foundation": 0,
    "core": 1,
    "features": 2,
    "integration": 3,
}


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReadingConfig:
    """Configuration for reading order computation.

    Attributes:
        skip_tests: Whether to skip test files entirely.
        test_pass: Which pass to place unpaired/orphan test files in.
        layer_thresholds: Mapping of layer name to minimum depth threshold.
        tie_breaking: How to break ties in topological sort.
        custom_pass_overrides: Per-file or per-glob pass overrides
            (e.g., ``{"src/types/**": "contracts"}``).
        integration_fan_in_threshold: Minimum fan_in for a file at depth 3+
            to qualify as integration layer.
        exclude_from_reading: Glob patterns for files to exclude from
            the reading order (e.g., ``("**/__init__.py",)``).
    """

    skip_tests: bool = False
    test_pass: TestFileMode = TestFileMode.UTILITY
    layer_thresholds: dict[str, int] = field(
        default_factory=lambda: dict(_DEFAULT_LAYER_THRESHOLDS),
    )
    tie_breaking: TieBreaking = TieBreaking.ALPHABETICAL
    custom_pass_overrides: dict[str, str] = field(
        default_factory=lambda: dict[str, str](),
    )
    integration_fan_in_threshold: int = 3
    exclude_from_reading: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Glob matching helper
# ---------------------------------------------------------------------------


def match_custom_pass_override(
    path: str,
    config: ReadingConfig,
) -> str | None:
    """Check if a file path matches any custom pass override glob.

    Globs are checked in sorted order for determinism. The first
    matching glob wins.

    Args:
        path: Relative file path to check.
        config: The reading config with custom_pass_overrides.

    Returns:
        The pass name string if a glob matches, or None.
    """
    for glob_pattern in sorted(config.custom_pass_overrides):
        if fnmatch(path, glob_pattern):
            return config.custom_pass_overrides[glob_pattern]
    return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_VALID_PASS_NAMES: frozenset[str] = frozenset({
    "contracts", "data_flow", "utility",
})


def validate_config(config: ReadingConfig) -> None:
    """Validate a ReadingConfig, raising ValueError on invalid values.

    Checks:
    - Layer thresholds are non-negative.
    - Custom pass override values are valid pass names.
    - integration_fan_in_threshold is non-negative.
    """
    for layer_name, threshold in config.layer_thresholds.items():
        if threshold < 0:
            msg = (
                f"layer_thresholds[{layer_name!r}] must be non-negative, "
                f"got {threshold}"
            )
            raise ValueError(msg)

    for glob_pattern, pass_name in config.custom_pass_overrides.items():
        if pass_name not in _VALID_PASS_NAMES:
            msg = (
                f"custom_pass_overrides[{glob_pattern!r}] has invalid value "
                f"{pass_name!r}; must be one of {sorted(_VALID_PASS_NAMES)}"
            )
            raise ValueError(msg)

    if config.integration_fan_in_threshold < 0:
        msg = (
            f"integration_fan_in_threshold must be non-negative, "
            f"got {config.integration_fan_in_threshold}"
        )
        raise ValueError(msg)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_config(guide_dir: Path) -> ReadingConfig:
    """Load reading configuration from a .codebase-guide directory.

    Searches for ``config.toml`` first, then ``config.json``. Falls back
    to defaults if neither exists or the directory is missing.

    Args:
        guide_dir: Path to the ``.codebase-guide/`` directory.

    Returns:
        A validated ReadingConfig.

    Raises:
        ValueError: If the config file contains invalid values.
    """
    if not guide_dir.is_dir():
        return ReadingConfig()

    toml_path = guide_dir / "config.toml"
    json_path = guide_dir / "config.json"

    raw: dict[str, object] = {}

    if toml_path.is_file():
        raw = _load_toml(toml_path)
    elif json_path.is_file():
        raw = _load_json(json_path)
    else:
        return ReadingConfig()

    config = _build_config_from_raw(raw)
    validate_config(config)
    return config


def _load_json(path: Path) -> dict[str, object]:
    """Load a JSON config file."""
    text = path.read_text(encoding="utf-8")
    data: object = json.loads(text)
    if not isinstance(data, dict):
        msg = f"Config file {path} must contain a JSON object"
        raise ValueError(msg)
    return cast(dict[str, object], data)


def _load_toml(path: Path) -> dict[str, object]:
    """Load a TOML config file using Python 3.11+ tomllib."""
    import tomllib

    with path.open("rb") as f:
        data: dict[str, object] = tomllib.load(f)
    return data


def _build_config_from_raw(raw: dict[str, object]) -> ReadingConfig:
    """Build a ReadingConfig from a raw dict, applying defaults."""
    defaults = ReadingConfig()

    skip_tests = raw.get("skip_tests", defaults.skip_tests)
    if not isinstance(skip_tests, bool):
        msg = f"skip_tests must be a boolean, got {type(skip_tests).__name__}"
        raise ValueError(msg)

    test_pass = _parse_test_pass(raw.get("test_pass"))
    tie_breaking = _parse_tie_breaking(raw.get("tie_breaking"))

    layer_thresholds = _parse_layer_thresholds(
        raw.get("layer_thresholds"), defaults.layer_thresholds,
    )
    custom_pass_overrides = _parse_custom_pass_overrides(
        raw.get("custom_pass_overrides"), defaults.custom_pass_overrides,
    )

    raw_fan_in: object = raw.get("integration_fan_in_threshold")
    if raw_fan_in is not None:
        integration_fan_in_threshold = int(str(raw_fan_in))
    else:
        integration_fan_in_threshold = defaults.integration_fan_in_threshold

    exclude_from_reading = _parse_exclude_from_reading(
        raw.get("exclude_from_reading"),
    )

    return ReadingConfig(
        skip_tests=skip_tests,
        test_pass=test_pass,
        layer_thresholds=layer_thresholds,
        tie_breaking=tie_breaking,
        custom_pass_overrides=custom_pass_overrides,
        integration_fan_in_threshold=integration_fan_in_threshold,
        exclude_from_reading=exclude_from_reading,
    )


def _parse_test_pass(value: object) -> TestFileMode:
    """Parse a test_pass value from raw config."""
    if value is None:
        return ReadingConfig.test_pass  # type: ignore[return-value]
    if not isinstance(value, str):
        msg = f"test_pass must be a string, got {type(value).__name__}"
        raise ValueError(msg)
    try:
        return TestFileMode(value)
    except ValueError:
        valid = [m.value for m in TestFileMode]
        msg = f"test_pass must be one of {valid}, got {value!r}"
        raise ValueError(msg) from None


def _parse_tie_breaking(value: object) -> TieBreaking:
    """Parse a tie_breaking value from raw config."""
    if value is None:
        return ReadingConfig.tie_breaking  # type: ignore[return-value]
    if not isinstance(value, str):
        msg = f"tie_breaking must be a string, got {type(value).__name__}"
        raise ValueError(msg)
    try:
        return TieBreaking(value)
    except ValueError:
        valid = [m.value for m in TieBreaking]
        msg = f"tie_breaking must be one of {valid}, got {value!r}"
        raise ValueError(msg) from None


def _parse_layer_thresholds(
    value: object,
    defaults: dict[str, int],
) -> dict[str, int]:
    """Parse layer_thresholds from raw config value."""
    if value is None:
        return dict(defaults)
    if not isinstance(value, dict):
        msg = "layer_thresholds must be a dict"
        raise ValueError(msg)
    typed = cast(dict[str, object], value)
    return {str(k): int(str(v)) for k, v in typed.items()}


def _parse_custom_pass_overrides(
    value: object,
    defaults: dict[str, str],
) -> dict[str, str]:
    """Parse custom_pass_overrides from raw config value."""
    if value is None:
        return dict(defaults)
    if not isinstance(value, dict):
        msg = "custom_pass_overrides must be a dict"
        raise ValueError(msg)
    typed = cast(dict[str, object], value)
    return {str(k): str(v) for k, v in typed.items()}


def _parse_exclude_from_reading(value: object) -> tuple[str, ...]:
    """Parse exclude_from_reading from raw config value."""
    if value is None:
        return ()
    if not isinstance(value, list):
        msg = "exclude_from_reading must be a list of strings"
        raise ValueError(msg)
    typed = cast(list[object], value)
    for item in typed:
        if not isinstance(item, str):
            msg = (
                f"exclude_from_reading items must be strings, "
                f"got {type(item).__name__}"
            )
            raise ValueError(msg)
    return tuple(cast(list[str], typed))


def is_excluded(path: str, config: ReadingConfig) -> bool:
    """Check if a file path matches any exclude_from_reading pattern.

    Args:
        path: Relative file path to check.
        config: The reading config with exclude_from_reading patterns.

    Returns:
        True if the path matches any exclude pattern.
    """
    for pattern in config.exclude_from_reading:
        if fnmatch(path, pattern):
            return True
    return False
