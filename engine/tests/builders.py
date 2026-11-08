"""Candle builders for engine rule tests (integers only, UTC 5m candles from a fixed start)."""

from datetime import UTC, datetime, timedelta

from tradelens_engine.types import Candle

START = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
FIVE = timedelta(minutes=5)


def bar(
    i: int, h: int, l: int, c: int | None = None, o: int | None = None, tf: str = "5m"
) -> Candle:
    """Candle number ``i`` (1-based) with the given high/low; open/close default to the middle."""
    mid = (h + l) // 2
    o = mid if o is None else o
    c = mid if c is None else c
    return Candle.of(START + (i - 1) * FIVE, tf, o, h, l, c, bid_c=c, ask_c=c)


def series(rows: list[tuple[int, int, int]]) -> list[Candle]:
    """Candles from ``(high, low, close)`` rows; each open is the previous close kept in range."""
    out: list[Candle] = []
    prev = None
    for i, (h, l, c) in enumerate(rows, start=1):
        o = (h + l) // 2 if prev is None else max(l, min(h, prev))
        out.append(bar(i, h, l, c, o))
        prev = c
    return out


# Worked example (DD 7.2): internal pivot 2, hand-checked in the Day 2 report.
#   bar 3 swing high 15 (confirmed bar 5)   bar 5 swing low 6 (confirmed bar 7)
#   bar 7 closes 16 above 15 while Neutral -> consumed silently, no event
#   bar 7 swing high 17 (confirmed bar 9)   bar 10 swing low 9 (confirmed bar 12) -> Bull
#   bar 12 closes exactly 17 -> no BOS;     bar 13 closes 19 > 17 -> one internal bull BOS
#   bars 11-13 make a bullish FVG [15, 16]; bar 15 closes 22 -> no second BOS on 17
WORKED = [
    (10, 5, 8),
    (12, 7, 11),
    (15, 9, 13),
    (13, 8, 9),
    (11, 6, 7),
    (14, 8, 13),
    (17, 10, 16),
    (16, 12, 13),
    (14, 11, 12),
    (13, 9, 10),
    (15, 10, 14),
    (18, 12, 17),
    (20, 16, 19),
    (21, 18, 19),
    (23, 19, 22),
]


def synthetic(n: int, seed: int = 7) -> list[Candle]:
    """``n`` deterministic 5m candles: an integer random walk (LCG), no floats, no ``random``."""
    out: list[Candle] = []
    x, price = seed, 108_000
    for i in range(1, n + 1):
        x = (1103515245 * x + 12345) % 2**31
        move = x % 61 - 30
        x = (1103515245 * x + 12345) % 2**31
        up, down = x % 13, (x // 13) % 13
        o, c = price, price + move
        out.append(bar(i, max(o, c) + up, min(o, c) - down, c, o))
        price = c
    return out


def impulsive(n: int, seed: int = 11) -> list[Candle]:
    """``n`` 5m candles: a random walk with occasional 1-3 candle impulses (LCG, integers only).

    Impulses have big bodies and small wicks, so the series contains displacements, order
    blocks, FVGs, sweeps and setup candidates as well as the ordinary structure events.
    """
    out: list[Candle] = []
    x, price, impulse, sign = seed, 108_000, 0, 1
    for i in range(1, n + 1):
        x = (1103515245 * x + 12345) % 2**31
        if impulse == 0 and x % 29 == 0:
            impulse, sign = 1 + (x >> 8) % 3, 1 if (x >> 4) % 2 else -1
        x = (1103515245 * x + 12345) % 2**31
        if impulse:
            move = sign * (60 + x % 70)
            up, down = x % 5, (x >> 5) % 5
            impulse -= 1
        else:
            move = x % 61 - 30
            up, down = x % 13, (x // 13) % 13
        o, c = price, price + move
        out.append(bar(i, max(o, c) + up, min(o, c) - down, c, o))
        price = c
    return out


ANCHOR = datetime(2026, 11, 9, 22, 0, tzinfo=UTC)  # 17:00 New York (winter)


def aggregate(five: list[Candle], tf: str) -> list[Candle]:
    """Complete ``tf`` buckets of 5m candles aligned to 17:00 New York (partial ones dropped)."""
    from tradelens_engine.types import TIMEFRAME_MINUTES

    minutes = TIMEFRAME_MINUTES[tf]
    span = timedelta(minutes=minutes)
    buckets: dict[int, list[Candle]] = {}
    for c in five:
        buckets.setdefault((c.open_time - ANCHOR) // span, []).append(c)
    out = []
    for idx in sorted(buckets):
        cs = buckets[idx]
        if len(cs) != minutes // 5:
            continue
        start = ANCHOR + idx * span
        last = cs[-1]
        out.append(Candle(start, start + span, cs[0].o, max(c.h for c in cs),
                          min(c.l for c in cs), last.c, last.bid_c, last.ask_c))  # fmt: skip
    return out
