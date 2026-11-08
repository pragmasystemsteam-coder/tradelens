"""Displacement (FR-SMC-09; DD 3.4, 7.2 row Displacement)."""

from datetime import UTC, datetime, timedelta

from tradelens_engine.rules.displacement import detect_displacement
from tradelens_engine.types import Candle

T0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
ATR_K = 1_000_000  # ATR = 1000 units
NORMAL = {"single_m": 1500, "multi_m": 2000}
STRONG = {"single_m": 2000, "multi_m": 2500}


def c(i, o, h, l, cl):
    return Candle.of(T0 + timedelta(hours=i), "1h", o, h, l, cl, bid_c=cl, ask_c=cl)


def detect(candles, atr_k=ATR_K, bar=10):
    return detect_displacement(candles, bar, atr_k, thresholds=NORMAL, strong=STRONG,
                               body_permille=650)  # fmt: skip


def test_single_body_1_5_atr_and_65_percent_of_range():
    d = detect([c(1, 10_000, 11_501, 9_999, 11_500)])
    assert (d.direction, d.candles, d.first_bar, d.end_bar, d.strong) == ("bull", 1, 10, 10, False)
    assert d.origin_time == T0 + timedelta(hours=1)
    assert d.confirm_time == T0 + timedelta(hours=2)


def test_body_1_499_atr_is_not_a_displacement():
    assert detect([c(1, 10_000, 11_500, 9_999, 11_499)]) is None


def test_body_ratio_below_65_percent_is_not_a_displacement():
    # body 1500, range 2400: 1500/2400 = 0.625
    assert detect([c(1, 10_000, 12_000, 9_600, 11_500)]) is None


def test_zero_range_and_missing_or_zero_atr_give_none():
    assert detect([c(1, 10_000, 10_000, 10_000, 10_000)]) is None
    big = c(1, 10_000, 13_000, 9_999, 13_000)
    assert detect([big], atr_k=None) is None
    assert detect([big], atr_k=0) is None


def test_two_same_colour_candles_moving_2_atr():
    d = detect([c(1, 10_000, 11_100, 9_990, 11_000), c(2, 11_000, 12_100, 10_990, 12_000)])
    assert (d.direction, d.candles, d.first_bar, d.end_bar) == ("bull", 2, 9, 10)
    assert d.origin_time == T0 + timedelta(hours=1)


def test_mixed_colours_are_not_a_multi_candle_move():
    assert detect([c(1, 10_000, 11_100, 9_990, 11_000), c(2, 11_000, 11_100, 10_990, 10_999),
                   c(3, 10_999, 12_200, 10_990, 12_000)]) is None  # fmt: skip


def test_three_candles_bearish():
    rows = [c(1, 20_000, 20_010, 19_200, 19_300), c(2, 19_300, 19_310, 18_600, 18_700),
            c(3, 18_700, 18_710, 17_900, 18_000)]  # fmt: skip
    d = detect(rows)
    assert (d.direction, d.candles, d.first_bar, d.end_bar) == ("bear", 3, 8, 10)


def test_single_beats_multi_and_strong_thresholds():
    rows = [c(1, 10_000, 11_100, 9_990, 11_000), c(2, 11_000, 13_050, 10_990, 13_000)]
    d = detect(rows)
    assert (d.candles, d.strong) == (1, True)  # body 2000 = 2.0 x ATR, strong single
    d2 = detect([c(1, 10_000, 11_300, 9_990, 11_250), c(2, 11_250, 12_550, 11_240, 12_500)])
    assert (d2.candles, d2.strong) == (2, True)  # net 2500 = 2.5 x ATR


def test_strong_setting_uses_the_strong_table():
    candle = c(1, 10_000, 11_501, 9_999, 11_500)
    assert detect_displacement([candle], 10, ATR_K, thresholds=STRONG, strong=STRONG,
                               body_permille=650) is None  # fmt: skip
