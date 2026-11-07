"""Trend, BOS and CHoCH (FR-SMC-03, FR-SMC-04, FR-SMC-05; DD 3.4 and 7.2)."""

from builders import bar

from tradelens_engine.rules.structure import Structure, add_swing, detect_breaks
from tradelens_engine.rules.swings import Swing

T = bar(1, 1, 0)


def sw(kind, price, at):
    c = bar(at, price + 1, price - 1)
    return Swing(kind, price, at, c.open_time, c.close_time)


def build(*swings, st=None):
    st = st or Structure()
    for s in swings:
        st = add_swing(st, s)
    return st


def close_at(i, c, h=None, l=None):
    return bar(i, h if h is not None else c + 1, l if l is not None else c - 1, c, c)


def bull():
    # HH (10 -> 20) and HL (5 -> 8): Bull, protected low 8. The close at bar 5 consumed the old
    # high 10 while Neutral (as real price would), so only 20 is unbroken.
    st = build(sw("high", 10, 2), sw("low", 5, 4))
    st, _ = detect_breaks(st, close_at(5, 11), atr_k=None, buf_m=0)
    return build(sw("high", 20, 6), sw("low", 8, 8), st=st)


def bear():
    # LH (20 -> 15) and LL (10 -> 5): Bear, protected high 15; the old low 10 was consumed.
    st = build(sw("low", 10, 2), sw("high", 20, 4))
    st, _ = detect_breaks(st, close_at(5, 9), atr_k=None, buf_m=0)
    return build(sw("low", 5, 6), sw("high", 15, 8), st=st)


def test_hh_hl_turns_bull():
    st = bull()
    assert st.trend == "bull"
    assert st.protected_low == sw("low", 8, 8)
    assert st.protected_high is None


def test_one_higher_high_stays_neutral():
    st = build(sw("high", 10, 2), sw("low", 5, 4), sw("high", 20, 6))
    assert st.trend == "neutral"


def test_lh_ll_turns_bear():
    st = bear()
    assert st.trend == "bear"
    assert st.protected_high == sw("high", 15, 8)


def test_equal_values_keep_neutral():
    st = build(sw("high", 10, 2), sw("low", 5, 4), sw("high", 10, 6), sw("low", 8, 8))
    assert st.trend == "neutral"
    st = build(sw("high", 10, 2), sw("low", 5, 4), sw("high", 20, 6), sw("low", 5, 8))
    assert st.trend == "neutral"


def test_trend_needs_latest_low_unbroken():
    st = build(sw("high", 10, 2), sw("low", 5, 4), sw("high", 20, 6))
    st, _ = detect_breaks(st, close_at(9, 3), atr_k=None, buf_m=0)  # breaks low 5 while Neutral
    st = add_swing(st, sw("low", 8, 8))
    assert st.trend == "bull"  # the latest low (8) is unbroken; the broken one was older


def test_close_above_unbroken_high_in_bull_is_bos():
    st, events = detect_breaks(bull(), close_at(10, 21), atr_k=None, buf_m=0)
    assert [(e.type, e.direction, e.level.price) for e in events] == [("bos", "bull", 20)]
    assert events[0].confirm_time == close_at(10, 21).close_time
    assert events[0].origin_time == sw("high", 20, 6).origin_time
    assert st.trend == "bull"


def test_wick_is_not_bos():
    st, events = detect_breaks(bull(), close_at(10, 19, h=25), atr_k=None, buf_m=0)
    assert events == []
    assert sw("high", 20, 6) in st.unbroken_highs


def test_close_equal_to_level_is_not_bos():
    _, events = detect_breaks(bull(), close_at(10, 20), atr_k=None, buf_m=0)
    assert events == []


def test_buffer_needs_close_beyond_level_plus_atr_multiple():
    # bos_buffer_m 500 with ATR 4 units (atr_k 4000): close must exceed 20 + 2.
    _, events = detect_breaks(bull(), close_at(10, 22), atr_k=4000, buf_m=500)
    assert events == []
    _, events = detect_breaks(bull(), close_at(10, 23), atr_k=4000, buf_m=500)
    assert len(events) == 1


def test_one_bos_per_level():
    st, first = detect_breaks(bull(), close_at(10, 21), atr_k=None, buf_m=0)
    st, second = detect_breaks(st, close_at(11, 22), atr_k=None, buf_m=0)
    st, third = detect_breaks(st, close_at(12, 23), atr_k=None, buf_m=0)
    assert len(first) == 1
    assert second == third == []


def test_older_unbroken_level_kept():
    st = add_swing(bull(), sw("high", 30, 10))  # unbroken highs: 20, 30
    st, events = detect_breaks(st, close_at(12, 25), atr_k=None, buf_m=0)
    assert [e.level.price for e in events] == [20]  # highest level the close is beyond
    assert sw("high", 30, 10) in st.unbroken_highs
    st, events = detect_breaks(st, close_at(13, 31), atr_k=None, buf_m=0)
    assert [e.level.price for e in events] == [30]


def test_close_beyond_several_levels_consumes_all_and_emits_one():
    st = add_swing(bull(), sw("high", 30, 10))
    st, events = detect_breaks(st, close_at(12, 35), atr_k=None, buf_m=0)
    assert [e.level.price for e in events] == [30]
    assert st.unbroken_highs == ()


def test_bos_moves_protected_low_to_lowest_unbroken_low_after_broken_high():
    st = build(sw("low", 12, 9), st=bull())  # a low formed after the high 20 (bar 6)
    st, _ = detect_breaks(st, close_at(10, 21), atr_k=None, buf_m=0)
    assert st.protected_low == sw("low", 8, 8)  # 8 (bar 8) is lower than 12 (bar 9)


def test_protected_low_waits_for_a_low_after_the_break():
    st = build(sw("high", 25, 9), st=bull())
    st, _ = detect_breaks(st, close_at(10, 21), atr_k=None, buf_m=0)  # breaks 20 (bar 6)
    st, _ = detect_breaks(st, close_at(11, 26), atr_k=None, buf_m=0)  # breaks 25 (bar 9)
    assert st.protected_low is None  # no unbroken low formed after bar 9 yet
    st = add_swing(st, sw("low", 22, 11))
    assert st.protected_low == sw("low", 22, 11)


def test_neutral_break_emits_nothing():
    st = build(sw("high", 10, 2), sw("low", 5, 4))
    st, events = detect_breaks(st, close_at(6, 11), atr_k=None, buf_m=0)
    assert events == []
    assert st.unbroken_highs == ()  # consumed silently, so no stale BOS once a trend starts
    st, events = detect_breaks(st, close_at(7, 4), atr_k=None, buf_m=0)
    assert events == []
    assert st.trend == "neutral"


def test_choch_first_close_beyond_protected():
    st, events = detect_breaks(bear(), close_at(10, 16), atr_k=None, buf_m=0)
    assert [(e.type, e.direction, e.level.price) for e in events] == [("choch", "bull", 15)]
    assert st.trend == "bull"
    assert st.protected_high is None


def test_close_beyond_non_protected_swing_no_choch():
    st = add_swing(bear(), sw("high", 12, 10))  # a lower, non-protected high
    st, events = detect_breaks(st, close_at(12, 13), atr_k=None, buf_m=0)
    assert events == []
    assert st.trend == "bear"
    assert sw("high", 15, 8) in st.unbroken_highs


def test_choch_never_from_neutral():
    st = build(sw("high", 10, 2), sw("low", 5, 4), sw("high", 20, 6))
    for i, c in enumerate([25, 1, 30], start=7):
        st, events = detect_breaks(st, close_at(i, c), atr_k=None, buf_m=0)
        assert all(e.type != "choch" for e in events)
    assert st.trend == "neutral"


def test_mirror_bear_bos():
    st, events = detect_breaks(bear(), close_at(10, 4), atr_k=None, buf_m=0)
    assert [(e.type, e.direction, e.level.price) for e in events] == [("bos", "bear", 5)]
    assert st.trend == "bear"


def test_choch_bear_from_bull():
    st, events = detect_breaks(bull(), close_at(10, 7), atr_k=None, buf_m=0)
    assert [(e.type, e.direction, e.level.price) for e in events] == [("choch", "bear", 8)]
    assert st.trend == "bear"
    assert st.protected_low is None


def test_history_keeps_last_30():
    st = Structure()
    for i in range(40):
        st = add_swing(st, sw("high", 100 + i, i + 1))
    assert len(st.highs) == 30
    assert st.highs[-1].price == 139


def test_bos_without_a_newer_low_leaves_protected_low_empty_per_spec():
    """DD 3.4 pick_protected: "None until one exists". A close below the old protected low is
    then consumed silently (no CHoCH) - flagged to the client to confirm (Day 2 report)."""
    st, _ = detect_breaks(bull(), close_at(10, 21), atr_k=None, buf_m=0)  # BOS on 20 (bar 6)
    assert st.protected_low == sw("low", 8, 8)  # 8 (bar 8) is after the broken high (bar 6)
    st = build(sw("high", 30, 11), st=st)
    st, _ = detect_breaks(st, close_at(12, 31), atr_k=None, buf_m=0)  # breaks 30 (bar 11)
    assert st.protected_low is None
    st, events = detect_breaks(st, close_at(13, 7), atr_k=None, buf_m=0)
    assert events == []
    assert st.trend == "bull"


def test_bear_without_protected_high_is_silent():
    st, _ = detect_breaks(bear(), close_at(10, 4), atr_k=None, buf_m=0)  # BOS bear on 5 (bar 6)
    assert st.protected_high == sw("high", 15, 8)
    st = build(sw("low", 2, 11), st=st)
    st, _ = detect_breaks(st, close_at(12, 1), atr_k=None, buf_m=0)  # BOS bear on 2 (bar 11)
    assert st.protected_high is None
    st, events = detect_breaks(st, close_at(13, 16), atr_k=None, buf_m=0)
    assert events == []


def test_buffer_ignored_without_atr():
    _, events = detect_breaks(bull(), close_at(10, 21), atr_k=None, buf_m=500)
    assert len(events) == 1


def test_one_choch_per_candle_even_with_crossed_stale_levels():
    st = bear()
    st = add_swing(st, sw("low", 17, 9))  # a stale unbroken low above the protected high
    st, events = detect_breaks(st, close_at(10, 16), atr_k=None, buf_m=0)
    assert [e.type for e in events] == ["choch"]
    assert st.trend == "bull"
    assert sw("low", 17, 9) not in st.unbroken_lows  # consumed silently


def test_unbroken_stacks_are_capped_but_keep_the_protected_swing():
    from tradelens_engine.rules.structure import UNBROKEN_MAX

    st = bear()
    for i in range(UNBROKEN_MAX + 20):
        st = add_swing(st, sw("high", 14 - (i % 3), 20 + i))
    assert len(st.unbroken_highs) == UNBROKEN_MAX
    assert st.protected_high in st.unbroken_highs
    st, events = detect_breaks(st, close_at(200, 16), atr_k=None, buf_m=0)
    assert [e.type for e in events] == ["choch"]
