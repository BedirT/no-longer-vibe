"""CLI entry point for nlv.

Delegates to the pipeline orchestrator in ``nlv.index`` for the actual
indexing work. The CLI handles argument parsing, logging setup, path
validation, and printing the result summary.

Usage::

    nlv [path] [--verbose]
    python -m nlv [path] [--verbose]

The ``path`` argument defaults to the current working directory.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from nlv.index import run_index

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse argument parser."""
    parser = argparse.ArgumentParser(
        prog="nlv",
        description=(
            "Deterministic codebase reading order tool. "
            "Indexes source files, builds a dependency graph, "
            "and generates .codebase-guide/map.json."
        ),
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path to the project directory (defaults to current directory).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose (DEBUG) logging output.",
    )
    return parser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_logging(*, verbose: bool) -> None:
    """Configure the logging level for the nlv package."""
    level = logging.DEBUG if verbose else logging.WARNING
    nlv_logger = logging.getLogger("nlv")
    nlv_logger.setLevel(level)
    if not nlv_logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        nlv_logger.addHandler(handler)


def _resolve_path(raw_path: str | None) -> Path:
    """Resolve and validate the target path.

    Args:
        raw_path: User-supplied path string, or None for cwd.

    Returns:
        Resolved absolute Path.

    Raises:
        SystemExit: If the path does not exist or is not a directory.
    """
    if raw_path is None:
        target = Path.cwd()
    else:
        target = Path(raw_path)

    if not target.exists():
        logger.error("Path does not exist: %s", target)
        raise SystemExit(1)

    if not target.is_dir():
        logger.error("Path is not a directory: %s", target)
        raise SystemExit(1)

    return target.resolve()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Run the nlv CLI.

    Args:
        argv: Command-line arguments. Defaults to sys.argv[1:].
    """
    if argv is None:
        argv = sys.argv[1:]

    parser = _build_parser()
    args = parser.parse_args(argv)

    _setup_logging(verbose=args.verbose)

    root = _resolve_path(args.path)
    logger.debug("Target path: %s", root)

    result = run_index(root)
    sys.stdout.write(result.summary + "\n")
