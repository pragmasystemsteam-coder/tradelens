"""``python -m tradelens.cli verify-instruments CONFIG_DIR [--live]`` (DD 6.8, task 1.3, CR-004).

Offline (always): every instrument has a unique Twelve Data symbol and valid scales. With
``--live`` and ``TWELVEDATA_API_KEY`` in the environment or deploy/.env, each symbol is looked
up with Twelve Data's ``/symbol_search`` (1 credit each, through the FREE-plan limiter) and
must exist with an expected instrument type. Exit code 1 lists every difference. The key is
never printed.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from tradelens.cli.doctor import parse_env
from tradelens.integrations.twelvedata.client import TwelveDataProvider
from tradelens.integrations.twelvedata.rate_limiter import CreditLimiter
from tradelens.modules.market_data.ports import ProviderError
from tradelens.modules.market_data.public import (
    InstrumentSpec,
    ReferenceDataError,
    load_instrument_specs,
)

EXIT_OK, EXIT_FAILED = 0, 1
# Twelve Data labels: FX "Physical Currency", gold/silver "Precious Metal", oil "Energy Resource".
EXPECTED_TYPES = frozenset({"Physical Currency", "Precious Metal", "Energy Resource"})
ENV_FILE = Path("deploy/.env")

Lookup = Callable[[str], Sequence[Mapping[str, Any]]]


def verify(specs: Sequence[InstrumentSpec], lookup: Lookup | None = None) -> list[str]:
    """Return one message per difference between config and the provider.

    Args:
        specs: Instruments from config/.
        lookup: Symbol search (``symbol -> matches``); None for offline checks only.

    Returns:
        Differences; empty when everything matches.
    """
    problems: list[str] = []
    seen: dict[str, str] = {}
    for spec in specs:
        symbol = spec.twelvedata_symbol
        if not symbol:
            problems.append(f"{spec.code}: no provider_symbols.twelvedata in instruments.json")
            continue
        if symbol in seen:
            problems.append(f"{spec.code}: symbol {symbol} also used by {seen[symbol]}")
        seen[symbol] = spec.code
        if lookup is None:
            continue
        matches = [m for m in lookup(symbol) if m.get("symbol") == symbol]
        if not matches:
            problems.append(f"{spec.code}: Twelve Data has no symbol {symbol}")
        elif not any(m.get("instrument_type") in EXPECTED_TYPES for m in matches):
            types = sorted({str(m.get("instrument_type")) for m in matches})
            problems.append(f"{spec.code}: {symbol} has unexpected instrument type {types}")
    return problems


def _api_key() -> str:
    key = os.environ.get("TWELVEDATA_API_KEY", "").strip()
    if not key and ENV_FILE.exists():
        key = parse_env(ENV_FILE.read_text(encoding="utf-8")).get("TWELVEDATA_API_KEY", "").strip()
    return key


def main(argv: list[str]) -> int:
    """Run the checks and print the result.

    Args:
        argv: ``[CONFIG_DIR]`` or ``[CONFIG_DIR, "--live"]``.

    Returns:
        0 when config matches, 1 otherwise.
    """
    live = "--live" in argv
    args = [a for a in argv if a != "--live"]
    config_dir = Path(args[0]) if args else Path("config")
    try:
        specs = load_instrument_specs(config_dir)
    except (OSError, ReferenceDataError) as exc:
        sys.stderr.write(f"verify-instruments: {exc}\n")
        return EXIT_FAILED
    lookup: Lookup | None = None
    if live:
        key = _api_key()
        if not key:
            sys.stderr.write("verify-instruments: --live needs TWELVEDATA_API_KEY in deploy/.env\n")
            return EXIT_FAILED
        provider = TwelveDataProvider(
            key, {s.code: s.twelvedata_symbol or "" for s in specs},
            {s.code: s.price_scale for s in specs}, CreditLimiter(),
        )  # fmt: skip
        lookup = provider.search_symbol
    try:
        problems = verify(specs, lookup)
    except ProviderError as exc:
        sys.stderr.write(f"verify-instruments: provider error: {exc}\n")
        return EXIT_FAILED
    for problem in problems:
        sys.stdout.write(f"DIFF    {problem}\n")
    mode = "live" if live else "offline"
    sys.stdout.write(
        f"verify-instruments ({mode}): {len(specs)} instruments, {len(problems)} differences\n"
    )
    return EXIT_FAILED if problems else EXIT_OK
