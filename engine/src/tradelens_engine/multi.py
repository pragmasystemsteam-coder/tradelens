"""``run_multi``: several timeframes of one instrument in live order (DD 3.5; NFR-07).

Candles of all timeframes are merged by close time; on a tie the higher timeframe goes first
(the worker steps a close batch 1D, 4H, 1H, 15m, 5m). Before each candle of a setup timeframe
(15m, 1H, 4H) the higher-timeframe context is built from the other series' current states,
which hold only candles that closed at or before this one, so batch equals live and a forming
higher-timeframe candle is never visible (FR-MTF-02).
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence

from tradelens_engine.context import PROFILE_BY_TF, build_context
from tradelens_engine.run import Collector, EngineResult
from tradelens_engine.series import SeriesState
from tradelens_engine.settings import Settings
from tradelens_engine.step import OutOfOrderCandle, step
from tradelens_engine.types import Candle

TF_ORDER: tuple[str, ...] = ("1d", "4h", "1h", "15m", "5m")


def run_multi(
    series_by_tf: Mapping[str, Sequence[Candle]],
    cfg: Settings,
    *,
    instrument: str,
    rule_version: str,
) -> dict[str, EngineResult]:
    """Run every timeframe of one instrument in live order.

    Args:
        series_by_tf: Timeframe to its closed candles (each list in open-time order).
        cfg: Validated settings.
        instrument: Instrument code.
        rule_version: Active rule version.

    Returns:
        Timeframe to its result.

    Raises:
        ValueError: On an unknown timeframe.
        OutOfOrderCandle: If a series is not in strictly increasing open-time order.
    """
    unknown = sorted(set(series_by_tf) - set(TF_ORDER))
    if unknown:
        raise ValueError(f"unknown timeframe(s): {unknown}")
    for tf, cs in series_by_tf.items():
        for prev, cur in itertools.pairwise(cs):
            if cur.open_time <= prev.open_time:
                raise OutOfOrderCandle(f"{tf}: {cur.open_time} is not after {prev.open_time}")
    rank = {tf: i for i, tf in enumerate(TF_ORDER)}
    merged = sorted(
        (
            (c.close_time, rank[tf], i, tf)
            for tf, cs in series_by_tf.items()
            for i, c in enumerate(cs)
        ),
    )
    acc = {tf: Collector(SeriesState()) for tf in series_by_tf}
    for _, _, i, tf in merged:
        profile = PROFILE_BY_TF.get(tf)
        htf = None
        if profile is not None:
            htf = build_context({k: v.state for k, v in acc.items()}, profile)
        acc[tf].add(*step(acc[tf].state, series_by_tf[tf][i], cfg, instrument=instrument,
                          timeframe=tf, rule_version=rule_version, htf=htf))  # fmt: skip
    return {tf: a.result() for tf, a in acc.items()}
