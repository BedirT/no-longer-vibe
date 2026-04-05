"""CLI entry point for nlv."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    """Run the nlv CLI.

    Args:
        argv: Command-line arguments. Defaults to sys.argv[1:].
    """
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        sys.stderr.write("usage: nlv <path>\n")
        raise SystemExit(1)

    path = Path(argv[0])
    if not path.exists():
        logger.error("Path does not exist: %s", path)
        raise SystemExit(1)

    logger.debug("Target path: %s", path)
    sys.stdout.write("not yet implemented.\n")
