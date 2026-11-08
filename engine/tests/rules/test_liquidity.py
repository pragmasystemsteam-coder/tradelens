"""Liquidity levels, periods, sessions, sweeps, EQH/EQL (DD 3.4, 7.2; FR-SMC-07/08, FR-DATA-04)."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from tradelens_engine.events import SeriesKey
from tradelens_engine.rules.liquidity import (
    Boxes,
    Level,
    Period,
    check_levels,
    expire_levels,
    register_levels,
    roll_boxes,
)
from tradelens_engine.rules.swings import Swing
from tradelens_engine.types import Candle

NY = ZoneInfo("America/New_York")
KEY = SeriesKey("EUR_USD", "1h", "r1.0", "h" * 64)
SESSIONS = {
    "asian": ["19:00", "03:00"],
    "london": ["03:00", "12:00"],
    "new_york": ["08:00", "17:00"],
}
T0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


def ny(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=NY).astimezone(UTC)


def candle(open_time, h, l, c=None, o=None, tf="1h"):
    mid = (h + l) // 2
    c = mid if c is None else c
    o = mid if o is None else o
    return Candle.of(open_time, tf, o, h, l, c, bid_c=c, ask_c=c)


def roll_all(candles, tf="1h"):
    """Roll the boxes over ``candles``; return the completed periods with the bar they appeared."""
    boxes, out = Boxes(), []
    for i, c in enumerate(candles, start=1):
        boxes, periods = roll_boxes(boxes, c, tf, SESSIONS)
        out += [(i, p) for p in periods]
    return boxes, out


def level(price, side="buy", kinds=("swing_high",), born=1, origin=T0):
    lid = KEY.level_id(kinds[0], side, origin, price)
    return Level(lid, "EUR_USD", "1h", kinds, side, price, "internal", origin, origin, born,
                 KEY.settings_hash, "r1.0")  # fmt: skip


def swing(kind, price, bar, t=T0):
    return Swing(kind, price, bar, t, t + timedelta(hours=1))


# ---- periods (PDH/PDL, PWH/PWL) ---------------------------------------------------------


def test_pdh_pdl_on_the_17ny_day():
    # Tuesday 10 Nov 2026 (winter): the trading day of Wednesday runs 17:00 Tue to 17:00 Wed NY.
    start = ny(2026, 11, 10, 12)
    highs = [10, 30, 20, 15, 12]  # 12:00..16:00 NY, all on the Tuesday trading day
    cs = [candle(start + timedelta(hours=i), h, h - 5) for i, h in enumerate(highs)]
    cs.append(candle(ny(2026, 11, 10, 17), 40, 1))  # first candle of the next day
    _, periods = roll_all(cs)
    day = [p for _, p in periods if p.high_kind == "pdh"]
    assert periods[0][0] == 6
    assert day == [Period("pdh", "pdl", 30, cs[1].open_time, 5, cs[0].open_time)]


def test_no_level_from_an_unfinished_day():
    start = ny(2026, 11, 10, 9)
    cs = [candle(start + timedelta(hours=i), 20 + i, 10) for i in range(8)]  # 09:00..16:00
    _, periods = roll_all(cs)
    assert [p for _, p in periods if p.high_kind in ("pdh", "pwh")] == []


def test_day_boundary_follows_dst_in_march_and_november():
    # 17:00 NY = 21:00 UTC in summer (from 8 Mar 2026) and 22:00 UTC in winter (from 1 Nov 2026).
    for day, utc_hour in ((datetime(2026, 3, 9), 21), (datetime(2026, 11, 2), 22)):
        boundary = datetime(day.year, day.month, day.day, utc_hour, tzinfo=UTC)
        before = [candle(boundary - timedelta(hours=k), 50, 40) for k in (2, 1)]
        after = candle(boundary, 60, 55)
        _, periods = roll_all([*before, after])
        assert [(i, p.high_kind) for i, p in periods if p.high_kind == "pdh"] == [(3, "pdh")]
        # One hour earlier is still the same trading day: nothing completes.
        _, periods = roll_all([before[0], candle(boundary - timedelta(hours=1, minutes=-30), 50, 40,
                                                 tf="5m")], tf="5m")  # fmt: skip
        assert [p for _, p in periods if p.high_kind == "pdh"] == []


def test_week_levels_after_the_week_completes():
    fri = ny(2026, 11, 13, 15)
    cs = [candle(fri, 70, 60), candle(fri + timedelta(hours=1), 75, 50)]
    cs.append(candle(ny(2026, 11, 15, 17), 80, 70))  # Sunday open: new day and new week
    _, periods = roll_all(cs)
    week = [p for i, p in periods if p.high_kind == "pwh"]
    assert week == [Period("pwh", "pwl", 75, cs[1].open_time, 50, cs[1].open_time)]


# ---- sessions ---------------------------------------------------------------------------


def test_session_levels_after_each_session_ends():
    # Asian 19:00-03:00 NY, London 03:00-12:00, New York 08:00-17:00 (overlap 08:00-12:00).
    start = ny(2026, 11, 10, 17)
    cs = [candle(start + timedelta(hours=i), 100 + i, 90 - i) for i in range(20)]  # to 12:00
    _, periods = roll_all(cs)
    kinds = [(i, p.high_kind) for i, p in periods]
    assert (11, "asian_high") in kinds  # first candle at 03:00 completes the Asian session
    assert (20, "london_high") in kinds  # the 12:00 candle completes London
    asian = next(p for _, p in periods if p.high_kind == "asian_high")
    assert asian.high == 109 and asian.high_time == cs[9].open_time  # 02:00 candle
    assert asian.low == 81 and asian.low_time == cs[9].open_time
    assert all(p.high_kind != "ny_high" for _, p in periods)  # NY still running


def test_session_levels_only_5m_15m_1h():
    start = ny(2026, 11, 10, 17)
    for tf, step_h, expect in (("1h", 1, True), ("4h", 4, False), ("1d", 24, False)):
        cs = [candle(start + timedelta(hours=step_h * i), 100 + i, 90, tf=tf) for i in range(12)]
        _, periods = roll_all(cs, tf=tf)
        has_session = any(
            p.high_kind.split("_")[0] in ("asian", "london", "ny") for _, p in periods
        )
        assert has_session is expect, tf
    cs = [candle(start + timedelta(minutes=5 * i), 100, 90, tf="5m") for i in range(10 * 12)]
    cs.append(candle(ny(2026, 11, 11, 3), 100, 90, tf="5m"))
    _, periods = roll_all(cs, tf="5m")
    assert [p.high_kind for _, p in periods] == ["asian_high"]


# ---- registering, superseding, expiry ---------------------------------------------------


def test_period_levels_registered_and_older_superseded():
    c = candle(T0, 20, 10)
    p1 = Period("pdh", "pdl", 50, T0 - timedelta(days=1), 5, T0 - timedelta(days=1))
    levels, changes = register_levels((), [], [p1], candle=c, bar=10, atr_k=None, eq_tol_m=100,
                                      key=KEY)  # fmt: skip
    assert sorted((lv.kinds, lv.side, lv.price) for lv in levels) == [
        (("pdh",), "buy", 50), (("pdl",), "sell", 5)]  # fmt: skip
    assert [ch.change for ch in changes] == ["created", "created"]
    assert all(lv.confirm_time == c.close_time and lv.born_bar == 10 for lv in levels)
    c2 = candle(T0 + timedelta(days=1), 20, 10)
    p2 = Period("pdh", "pdl", 60, T0, 4, T0)
    levels2, changes2 = register_levels(levels, [], [p2], candle=c2, bar=34, atr_k=None,
                                        eq_tol_m=100, key=KEY)  # fmt: skip
    assert sorted(lv.price for lv in levels2) == [4, 60]
    ended = [ch.level for ch in changes2 if ch.change == "ended"]
    assert sorted(lv.price for lv in ended) == [5, 50]
    assert all(lv.end_reason == "superseded" and lv.end_time == c2.close_time for lv in ended)


def test_one_level_per_side_and_price():
    c = candle(T0, 20, 10)
    existing = level(50)
    p = Period("pdh", "pdl", 50, T0 - timedelta(hours=5), 1, T0 - timedelta(hours=5))
    levels, changes = register_levels((existing,), [], [p], candle=c, bar=5, atr_k=None,
                                      eq_tol_m=100, key=KEY)  # fmt: skip
    buy = [lv for lv in levels if lv.side == "buy"]
    assert len(buy) == 1 and buy[0].kinds == ("swing_high", "pdh") and buy[0].id == existing.id
    assert buy[0].born_bar == 5  # the new kind restarts the level's age (review)
    assert ("updated", existing.id) in [(ch.change, ch.level.id) for ch in changes]


def test_swing_levels_from_internal_swings():
    c = candle(T0 + timedelta(hours=3), 20, 10)
    levels, _changes = register_levels((), [swing("high", 70, 4), swing("low", 3, 4)], [], candle=c,
                                      bar=7, atr_k=None, eq_tol_m=100, key=KEY)  # fmt: skip
    assert sorted((lv.kinds, lv.side, lv.price, lv.structure) for lv in levels) == [
        (("swing_high",), "buy", 70, "internal"),
        (("swing_low",), "sell", 3, "internal"),
    ]
    assert all(lv.origin_time == T0 for lv in levels)


def test_levels_expire_after_level_max_age():
    lv = level(50, born=1)
    kept, changes = expire_levels((lv,), 301, 300, T0)
    assert kept == (lv,) and changes == []
    kept, changes = expire_levels((lv,), 302, 300, T0)
    assert kept == () and [(c.change, c.level.end_reason) for c in changes] == [
        ("ended", "expired")
    ]


# ---- sweeps and breakouts ---------------------------------------------------------------


def run_check(levels, c, bar=20):
    return check_levels(tuple(levels), c, bar, KEY)


def test_wick_above_buy_side_close_below_is_bearish_sweep():
    lv = level(50)
    kept, events, changes = run_check([lv], candle(T0, 55, 40, c=48))
    assert [(e.type, e.direction, e.level, e.structure) for e in events] == [
        ("sweep", "bear", 50, None)]  # fmt: skip
    assert dict(events[0].refs) == {"level_id": lv.id}
    assert kept == ()
    assert changes[0].level.end_reason == "swept" and changes[0].level.ended_by == events[0].id


def test_close_above_buy_side_is_breakout():
    _, events, changes = run_check([level(50)], candle(T0, 55, 40, c=51))
    assert [(e.type, e.direction) for e in events] == [("breakout", "bull")]
    assert changes[0].level.end_reason == "breakout"


def test_close_exactly_on_the_level_is_neither():
    lv = level(50)
    kept, events, changes = run_check([lv], candle(T0, 55, 40, c=50))
    assert (kept, events, changes) == ((lv,), [], [])
    sell = level(10, side="sell", kinds=("swing_low",))
    kept, events, _ = run_check([sell], candle(T0, 30, 5, c=10))
    assert kept == (sell,) and events == []


def test_sell_side_mirror():
    _, events, _ = run_check([level(10, "sell", ("swing_low",))], candle(T0, 30, 5, c=12))
    assert [(e.type, e.direction) for e in events] == [("sweep", "bull")]
    _, events, _ = run_check([level(10, "sell", ("swing_low",))], candle(T0, 30, 5, c=9))
    assert [(e.type, e.direction) for e in events] == [("breakout", "bear")]


def test_wick_that_only_touches_the_level_is_not_a_sweep():
    lv = level(50)
    kept, events, _ = run_check([lv], candle(T0, 50, 40, c=45))
    assert kept == (lv,) and events == []


def test_new_level_not_swept_same_candle():
    lv = level(50, born=20)  # registered by the candle being checked
    kept, events, _ = run_check([lv], candle(T0, 55, 40, c=48), bar=20)
    assert kept == (lv,) and events == []


# ---- EQH / EQL --------------------------------------------------------------------------

ATR_K = 20_000  # ATR = 20 units; eq_tol_m 100 -> tolerance 2 units


def eq_register(levels, new_swing, atr_k=ATR_K, tol=100):
    c = candle(T0 + timedelta(hours=10), 20, 10)
    return register_levels(tuple(levels), [new_swing], [], candle=c, bar=30, atr_k=atr_k,
                           eq_tol_m=tol, key=KEY)  # fmt: skip


def test_two_swings_within_tolerance_merge_into_eqh():
    old = level(100)
    new = swing("high", 99, 25, t=T0 + timedelta(hours=5))
    levels, changes = eq_register([old], new)
    assert [(lv.kinds, lv.price) for lv in levels] == [(("eqh",), 100)]
    eqh = levels[0]
    assert eqh.origin_time == new.origin_time and eqh.structure == "internal"
    merged = [ch.level for ch in changes if ch.change == "ended"]
    assert [(m.id, m.end_reason, m.ended_by) for m in merged] == [(old.id, "merged", eqh.id)]


def test_eqh_merges_again_at_the_highest_price():
    eqh = level(100, kinds=("eqh",))
    levels, _ = eq_register([eqh], swing("high", 101, 25, t=T0 + timedelta(hours=7)))
    assert [(lv.kinds, lv.price) for lv in levels] == [(("eqh",), 101)]


def test_outside_tolerance_no_merge():
    old = level(100)
    levels, changes = eq_register([old], swing("high", 97, 25, t=T0 + timedelta(hours=5)))
    assert sorted((lv.kinds, lv.price) for lv in levels) == [
        (("swing_high",), 97), (("swing_high",), 100)]  # fmt: skip
    assert [ch.change for ch in changes] == ["created"]


def test_exactly_at_tolerance_merges():
    levels, _ = eq_register([level(100)], swing("high", 98, 25, t=T0 + timedelta(hours=5)))
    assert [(lv.kinds, lv.price) for lv in levels] == [(("eqh",), 100)]


def test_eql_mirror_at_the_lowest_price():
    old = level(50, side="sell", kinds=("swing_low",))
    levels, _ = eq_register([old], swing("low", 51, 25, t=T0 + timedelta(hours=5)))
    assert [(lv.kinds, lv.side, lv.price) for lv in levels] == [(("eql",), "sell", 50)]


def test_no_atr_no_merge():
    levels, _ = eq_register([level(100)], swing("high", 99, 25, t=T0 + timedelta(hours=5)),
                            atr_k=None)  # fmt: skip
    assert sorted(lv.price for lv in levels) == [99, 100]


def test_period_levels_never_merge_into_eqh():
    pdh = level(100, kinds=("pdh",))
    levels, _ = eq_register([pdh], swing("high", 99, 25, t=T0 + timedelta(hours=5)))
    assert sorted((lv.kinds, lv.price) for lv in levels) == [(("pdh",), 100),
                                                             (("swing_high",), 99)]  # fmt: skip
