"""Zone lifecycle: touched, 50%, filled, invalidated, retests and expiry (FR-ZONE-01..05)."""

from datetime import UTC, datetime, timedelta

from tradelens_engine.events import Zone
from tradelens_engine.rules.lifecycle import ZoneState, advance_zone, expire_zone
from tradelens_engine.types import Candle

T0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


def zone(direction="bull", low=100, high=110):
    return Zone("z" * 32, "ob", "EUR_USD", "1h", direction, low, high, T0, T0, "h" * 64, "r1.0")


def zs(direction="bull", **kw):
    return ZoneState(zone(direction), "confirmed", T0, created_bar=10, **kw)


def c(h, l, cl, i=1):
    o = max(l, min(h, cl))
    return Candle.of(T0 + timedelta(hours=i), "1h", o, h, l, cl, bid_c=cl, ask_c=cl)


def test_touched_50_filled_invalidated_with_timestamps():
    s, moves = advance_zone(zs(), c(130, 108, 120))
    assert moves == ("touched",) and s.state == "touched"
    assert s.state_time == c(130, 108, 120).close_time
    s, moves = advance_zone(s, c(130, 105, 120, i=2))
    assert moves == ("mitigated_50",)
    s, moves = advance_zone(s, c(130, 99, 120, i=3))
    assert moves == ("filled",)
    s, moves = advance_zone(s, c(130, 90, 99, i=4))
    assert moves == ("invalidated",) and s.state == "invalidated"


def test_one_candle_can_move_several_states():
    _s, moves = advance_zone(zs(), c(130, 99, 120))
    assert moves == ("touched", "mitigated_50", "filled")


def test_wick_beyond_far_edge_does_not_invalidate():
    s, moves = advance_zone(zs(), c(130, 95, 100))
    assert "invalidated" not in moves and s.state == "filled"


def test_states_only_move_forward():
    s, _ = advance_zone(zs(), c(130, 104, 120))
    assert s.state == "mitigated_50"
    s, moves = advance_zone(s, c(130, 109, 120, i=2))
    assert moves == () and s.state == "mitigated_50"


def test_bear_mirror():
    s, moves = advance_zone(zs("bear"), c(105, 80, 90))
    assert moves == ("touched", "mitigated_50")
    s, moves = advance_zone(s, c(112, 80, 111, i=2))
    assert moves == ("filled", "invalidated")


def test_five_candles_inside_count_one_retest():
    s = zs()
    for i in range(5):
        s, _ = advance_zone(s, c(112, 106, 108, i=i + 1))
    assert s.retests == 1
    s, _ = advance_zone(s, c(130, 115, 120, i=6))  # leaves the zone
    s, _ = advance_zone(s, c(120, 107, 112, i=7))  # comes back: second retest
    assert s.retests == 2


def test_101st_candle_expires_100th_does_not():
    s, expired = expire_zone(zs(), 110, 100, 3, T0)
    assert not expired and s.state == "confirmed"
    s, expired = expire_zone(zs(), 111, 100, 3, T0)
    assert expired and s.state == "expired" and s.state_time == T0


def test_fourth_retest_expires():
    _, expired = expire_zone(zs(retests=3), 20, 100, 3, T0)
    assert not expired
    _s, expired = expire_zone(zs(retests=4), 20, 100, 3, T0)
    assert expired


def test_invalidate_beats_expire():
    s, moves = advance_zone(zs(retests=3), c(130, 90, 95, i=101))  # 4th retest + close < low
    assert moves[-1] == "invalidated" and s.retests == 4
    s, expired = expire_zone(s, 111, 100, 3, T0)
    assert not expired and s.state == "invalidated"
