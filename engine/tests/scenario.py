"""A hand-made 29-candle series (internal pivot 2) for displacement, OB and setup tests.

Bars 1-14 are flat (ATR 20 at bar 14). Then: swing high H1 1040 (bar 16), swing low L1 980
(bar 19, sweeping the 990 London/NY/PD low: close 995), H2 1060 (bar 22), L2 1000 (bar 24,
confirmed at 26: trend turns Bull), bar 26 is the last bearish candle (the OB, 1003-1025),
bar 27 a single bullish displacement (body 50 >= 1.5 x ATR ~28), bar 28 completes a bullish
FVG 1025-1045 and bar 29 closes 1070 above H2: internal bull BOS two candles after the
displacement, so the OB is promoted and a setup candidate appears on 15m, 1H and 4H.
"""

from datetime import timedelta

from builders import START

from tradelens_engine.types import TIMEFRAME_MINUTES, Candle

FLAT = [(1010, 990, 1000, 1000)] * 14
BASE = [
    *FLAT,
    (1020, 1000, 1000, 1015),  # 15
    (1040, 1010, 1015, 1035),  # 16 H1
    (1036, 1005, 1035, 1010),  # 17
    (1020, 995, 1010, 1000),  # 18
    (1015, 980, 1000, 995),  # 19 L1, sweeps the 990 low (close back above)
    (1030, 990, 995, 1025),  # 20
    (1050, 1015, 1025, 1045),  # 21
    (1060, 1035, 1045, 1055),  # 22 H2
    (1055, 1020, 1055, 1025),  # 23
    (1040, 1000, 1025, 1005),  # 24 L2
    (1030, 1002, 1005, 1020),  # 25
    (1025, 1003, 1020, 1008),  # 26 last bearish candle: the order block
    (1059, 1006, 1008, 1058),  # 27 displacement
    (1062, 1045, 1058, 1050),  # 28 FVG 1025-1045 confirmed
    (1075, 1048, 1050, 1070),  # 29 internal bull BOS above 1060
]
# Break 4 candles after the displacement: too late (no OB, no setup).
LATE = [*BASE[:27], (1062, 1045, 1058, 1050), (1058, 1044, 1050, 1048), (1056, 1046, 1048, 1052),
        (1075, 1050, 1052, 1070)]  # fmt: skip
# Break exactly 3 candles after the displacement: still in time.
EXACT3 = [*BASE[:27], (1062, 1045, 1058, 1050), (1058, 1044, 1050, 1048), (1070, 1046, 1048, 1065)]
# Bar 28 dips into the OB before the break: touched before confirmation.
TOUCHED = [*BASE[:27], (1062, 1020, 1058, 1050), BASE[28]]
# No displacement: bar 27 is small, bar 28 bearish.
NO_DISP = [*BASE[:26], (1040, 1006, 1008, 1030), (1062, 1035, 1050, 1040), (1075, 1038, 1040, 1070)]


def candles(rows, tf="1h", start=START):
    """Candles from ``(high, low, open, close)`` rows; spread 2 (bid close - 1, ask close + 1)."""
    step = timedelta(minutes=TIMEFRAME_MINUTES[tf])
    return [
        Candle(start + i * step, start + (i + 1) * step, o, h, l, c, c - 1, c + 1)
        for i, (h, l, o, c) in enumerate(rows)
    ]


# Bar 28 makes a second (2-candle) displacement 27-28 that finds the same OB candle 26 and
# closes 1080 above H2: one break, two displacement records sharing one OB (review HIGH 1).
SHARED = [*BASE[:27], (1085, 1056, 1058, 1080)]
