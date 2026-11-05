from datetime import UTC, datetime, timedelta

import pytest

from tradelens_engine.arith import (
    AtrState,
    atr_update,
    body_ratio_ok,
    combined_score,
    ge_atr,
    le_atr,
)
from tradelens_engine.types import Candle

T0 = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def flat(i: int) -> Candle:
    """o=c=100, h=101, l=100: true range 1 whether or not a previous close exists."""
    return Candle.of(at(5 * i), "5m", 100, 101, 100, 100, bid_c=100, ask_c=100)


def feed(n: int) -> AtrState:
    state = AtrState()
    for i in range(n):
        state = atr_update(state, flat(i))
    return state


def test_atr_seed_at_14():
    s13 = feed(13)
    assert s13.atr_k is None
    assert (s13.tr_count, s13.tr_sum, s13.prev_close) == (13, 13, 100)
    s14 = atr_update(s13, flat(13))
    assert s14.atr_k == 1000  # ATR 1 unit, x1000


def test_atr_half_up():
    s14 = feed(14)
    doji = Candle.of(at(5 * 14), "5m", 100, 100, 100, 100, bid_c=100, ask_c=100)
    s15 = atr_update(s14, doji)
    # Wilder: (1000*13 + 0*1000) / 14 = 928.57 -> 929 (floor would give 928)
    assert s15.atr_k == 929
    assert s15.tr_count == 15


def test_atr_true_range_uses_previous_close():
    s1 = atr_update(AtrState(), Candle.of(at(0), "5m", 100, 100, 100, 100, bid_c=100, ask_c=100))
    gap = Candle.of(at(5), "5m", 105, 110, 105, 108, bid_c=108, ask_c=108)
    s2 = atr_update(s1, gap)
    assert s2.tr_sum == 0 + 10  # max(110-105, |110-100|, |105-100|)


def test_atr_state_is_immutable_input():
    s13 = feed(13)
    atr_update(s13, flat(13))
    assert s13.atr_k is None and s13.tr_count == 13


@pytest.mark.parametrize("atr_k", [None, 0])
def test_ge_atr_no_atr_false(atr_k):
    assert ge_atr(10**9, 1, atr_k) is False
    assert le_atr(0, 1000, atr_k) is False


def test_ge_atr_boundary():
    # atr_k 10000 = ATR of 10 units; m 1500 = 1.5 x ATR = 15 units
    assert ge_atr(15, 1500, 10000) is True
    assert ge_atr(14, 1500, 10000) is False
    assert le_atr(15, 1500, 10000) is True
    assert le_atr(16, 1500, 10000) is False


def test_body_ratio_ok():
    assert body_ratio_ok(65, 100, 650) is True
    assert body_ratio_ok(64, 100, 650) is False
    assert body_ratio_ok(0, 0, 650) is False  # zero range never qualifies


@pytest.mark.parametrize(
    "q,c,expected",
    [(60, 60, 60), (60, 59, 60), (59, 60, 59), (1, 0, 1), (0, 0, 0), (100, 100, 100)],
)
def test_combined_half_up(q, c, expected):
    assert combined_score(q, c) == expected


@pytest.mark.parametrize("q,c", [(101, 0), (0, -1), (50.0, 50)])
def test_combined_rejects_out_of_range_or_float(q, c):
    with pytest.raises(ValueError):
        combined_score(q, c)


def test_atr_wilder_smoothing_over_several_candles():
    state = feed(14)  # atr_k 1000
    big = Candle.of(at(70), "5m", 100, 110, 100, 105, bid_c=105, ask_c=105)
    state = atr_update(state, big)  # tr 10: (1000*13 + 10000 + 7) // 14 = 1643
    assert state.atr_k == 1643
    after = Candle.of(at(75), "5m", 100, 101, 100, 100, bid_c=100, ask_c=100)
    state = atr_update(state, after)  # tr = max(1, |101-105|, |100-105|) = 5 -> 1883
    assert state.atr_k == 1883


def test_atr_period_parameter():
    state = AtrState()
    for i in range(3):
        state = atr_update(state, flat(i), period=3)
    assert state.atr_k == 1000
    doji = Candle.of(at(15), "5m", 100, 100, 100, 100, bid_c=100, ask_c=100)
    assert atr_update(state, doji, period=3).atr_k == 667  # 666.67 rounds half up
