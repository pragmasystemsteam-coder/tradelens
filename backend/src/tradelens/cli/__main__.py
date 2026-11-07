"""Dispatch ``python -m tradelens.cli doctor|seed|verify-instruments ...``."""

from __future__ import annotations

import sys

from tradelens.cli import doctor, seed, verify_instruments

COMMANDS = {
    "doctor": doctor.main,
    "seed": seed.main,
    "verify-instruments": verify_instruments.main,
}
USAGE = (
    "usage: python -m tradelens.cli"
    " {doctor ENV_FILE | seed CONFIG_DIR | verify-instruments CONFIG_DIR [--live]}\n"
)
EXIT_USAGE = 2


def main(argv: list[str]) -> int:
    """Run the command named in ``argv[0]``.

    Args:
        argv: Command name followed by its arguments.

    Returns:
        The command's exit code, or 2 for an unknown command.
    """
    if not argv or argv[0] not in COMMANDS:
        sys.stderr.write(USAGE)
        return EXIT_USAGE
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
