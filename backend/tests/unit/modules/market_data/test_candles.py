"""Price parsing and the completed-candle rule (FR-DATA-01, FR-DATA-02, AD-04, CR-004)."""

from datetime import UTC, datetime, timedelta

import pytest

from tradelens.modules.market_data.candles import (
    PriceFormatError,
    StoredCandle,
    complete_bars,
    normalise_bars,
    parse_price,
    to_stored,
)
from tradelens.modules.market_data.ports import RawBar

T0 = datetime(2026, 11, 6, 14, 0, tzinfo=UTC)


def bar(minutes: int, o=100, h=110, l=90, c=105) -> RawBar:
    return RawBar(T0 + timedelta(minutes=minutes), o, h, l, c)


def test_parse_price_string_to_int():
    assert parse_price("1.07215", 5) == 107215
    assert parse_price("1.0721", 5) == 107210  # fewer decimals are padded, never floats
    assert parse_price("2650.5", 3) == 2650500
    assert parse_price("153", 3) == 153000
    assert parse_price("0.61000", 5) == 61000


def test_parse_price_rejects_extra_digits():
    with pytest.raises(PriceFormatError):
        parse_price("1.072155", 5)


def test_parse_price_allows_trailing_zero_beyond_scale():
    assert parse_price("1.072150", 5) == 107215


@pytest.mark.parametrize("text", ["", "1e5", "-", "1.2.3", "abc", "-1.0", " 1.0", "1.", ".5"])
def test_parse_price_rejects_garbage(text):
    with pytest.raises(PriceFormatError):
        parse_price(text, 5)


def test_forming_bar_is_dropped():
    bars = [bar(0), bar(5), bar(10)]  # 5m bars; the 14:10 bar closes at 14:15
    now = T0 + timedelta(minutes=14, seconds=59)
    assert [b.open_time for b in complete_bars(bars, "5m", now)] == [
        bar(0).open_time,
        bar(5).open_time,
    ]


def test_bar_complete_exactly_at_close():
    assert complete_bars([bar(0)], "5m", T0 + timedelta(minutes=5)) == [bar(0)]
    assert (
        complete_bars([bar(0)], "5m", T0 + timedelta(minutes=5) - timedelta(microseconds=1)) == []
    )


def test_stored_candle_mid_for_bid_and_ask():
    row = to_stored(bar(0), "EUR_USD", "5m", "twelvedata")
    assert isinstance(row, StoredCandle)
    assert (row.bid_o, row.bid_h, row.bid_l, row.bid_c) == (100, 110, 90, 105)
    assert (row.ask_o, row.ask_h, row.ask_l, row.ask_c) == (100, 110, 90, 105)
    assert row.source == "twelvedata"
    assert row.close_time == T0 + timedelta(minutes=5)
    assert row.as_row()["instrument"] == "EUR_USD"


def test_bars_sorted_and_deduplicated():
    out = normalise_bars([bar(10), bar(0), bar(5), bar(0, c=104)])
    assert [b.open_time.minute for b in out] == [0, 5, 10]
    assert out[0].c == 104  # the later copy of a duplicate wins (providers may revise)


def test_raw_bar_rejects_inconsistent_ohlc_and_naive_time():
    with pytest.raises(ValueError):
        RawBar(T0, 100, 99, 90, 95)
    with pytest.raises(ValueError):
        RawBar(datetime(2026, 11, 6, 14, 0), 100, 110, 90, 105)
    with pytest.raises(ValueError):
        RawBar(T0, 100.0, 110, 90, 105)
