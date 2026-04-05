"""CLI entry point for nlv."""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    """Run the nlv CLI.

    Args:
        argv: Command-line arguments. Defaults to sys.argv[1:].
    """
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        print("usage: nlv <path>", file=sys.stderr)  # noqa: T201
        raise SystemExit(1)

    path = argv[0]
    logger.debug("Target path: %s", path)
    print("not yet implemented.")  # noqa: T201
