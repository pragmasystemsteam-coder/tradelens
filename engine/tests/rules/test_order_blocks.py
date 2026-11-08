"""Order block candidates and pre-confirmation touches (FR-SMC-10; DD 3.4, 7.2)."""

from datetime import UTC, datetime, timedelta

from tradelens_engine.rules.displacement import Displacement
from tradelens_engine.rules.order_blocks import (
    ObCandidate,
    closed_beyond,
    find_order_block,
    pre_confirmation_touch,
)
from tradelens_engine.types import Candle

T0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


def c(i, o, h, l, cl):
    return Candle.of(T0 + timedelta(hours=i - 1), "1h", o, h, l, cl, bid_c=cl, ask_c=cl)


# bars 1..8: 4 is the last bearish candle, 5 a small bullish one, 6-8 the bullish move.
ROWS = [
    (100, 105, 95, 102), (102, 106, 98, 99), (99, 104, 97, 103), (103, 104, 96, 97),
    (105, 108, 105, 107), (107, 120, 99, 118), (118, 140, 117, 138), (138, 160, 137, 158),
]  # fmt: skip
WINDOW = [c(i, *r) for i, r in enumerate(ROWS, start=1)]
MOVE = Displacement("bull", 6, 8, WINDOW[5].open_time, WINDOW[7].close_time, 3, False)


def test_last_opposing_candle_before_the_move_full_range():
    cand = find_order_block(WINDOW, 8, MOVE, limit_bar=None, lookback=10)
    assert cand == ObCandidate(4, WINDOW[3].open_time, 96, 104, MOVE.confirm_time)


def test_search_stops_at_the_latest_internal_swing_low():
    assert find_order_block(WINDOW, 8, MOVE, limit_bar=5, lookback=10) is None
    assert find_order_block(WINDOW, 8, MOVE, limit_bar=4, lookback=10).bar == 4


def test_search_stops_after_lookback_bars():
    assert find_order_block(WINDOW, 8, MOVE, limit_bar=None, lookback=1) is None
    assert find_order_block(WINDOW, 8, MOVE, limit_bar=None, lookback=2).bar == 4


def test_candidate_dropped_when_a_later_close_went_below_its_low():
    rows = [*ROWS[:4], (94, 101, 93, 95), *ROWS[5:]]  # bullish bar 5 closes 95 < low 96
    window = [c(i, *r) for i, r in enumerate(rows, start=1)]
    assert find_order_block(window, 8, MOVE, limit_bar=None, lookback=10) is None
    cand = find_order_block(WINDOW, 8, MOVE, limit_bar=None, lookback=10)
    assert closed_beyond(cand, "bull", 95) and not closed_beyond(cand, "bull", 96)


def test_bearish_mirror():
    rows = [(200, 205, 195, 198), (198, 204, 197, 203), (203, 204, 180, 182), (182, 183, 160, 162)]
    window = [c(i, *r) for i, r in enumerate(rows, start=1)]
    move = Displacement("bear", 3, 4, window[2].open_time, window[3].close_time, 2, False)
    cand = find_order_block(window, 4, move, limit_bar=None, lookback=10)
    assert (cand.bar, cand.low, cand.high) == (2, 197, 204)
    assert closed_beyond(cand, "bear", 205) and not closed_beyond(cand, "bear", 204)


def test_leg_candles_not_pre_touch():
    cand = find_order_block(WINDOW, 8, MOVE, limit_bar=None, lookback=10)
    # Bar 6 (the first leg candle) overlaps the OB, but leg candles are excluded.
    assert not pre_confirmation_touch(WINDOW, 8, cand, MOVE, break_bar=8)
    # Bar 5 sits between the OB and the move and overlaps it: touched before confirmation.
    move_late = Displacement("bull", 7, 8, WINDOW[6].open_time, WINDOW[7].close_time, 2, False)
    assert pre_confirmation_touch(WINDOW, 8, cand, move_late, break_bar=8)


def test_touch_between_the_move_and_the_break_counts():
    rows = [*ROWS, (158, 159, 103, 150), (150, 170, 149, 168)]  # bar 9 dips into the OB
    window = [c(i, *r) for i, r in enumerate(rows, start=1)]
    cand = find_order_block(WINDOW, 8, MOVE, limit_bar=None, lookback=10)
    assert pre_confirmation_touch(window, 10, cand, MOVE, break_bar=10)
    calm = [*ROWS, (158, 159, 140, 150), (150, 170, 149, 168)]
    window = [c(i, *r) for i, r in enumerate(calm, start=1)]
    assert not pre_confirmation_touch(window, 10, cand, MOVE, break_bar=10)
