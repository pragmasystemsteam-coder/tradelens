"""Swings (FR-SMC-01, FR-SMC-02, DD 3.4 and 7.2 Swings)."""

import pytest
from builders import bar, series

from tradelens_engine.rules.swings import Swing, confirm_swings


def window(highs, lows=None):
    lows = lows or [h - 10 for h in highs]
    return [bar(i, h, l) for i, (h, l) in enumerate(zip(highs, lows, strict=True), start=1)]


def test_3_3_pivot_confirmed_at_close_of_i_plus_3():
    w = window([10, 11, 12, 20, 13, 12, 11])  # candidate bar 4, three bars each side
    swings = confirm_swings(w, last_bar=7, left=3, right=3)
    assert swings == [Swing("high", 20, 4, w[3].open_time, w[6].close_time)]
    assert confirm_swings(w[:6], last_bar=6, left=3, right=3) == []  # not knowable before i+3


def test_higher_high_in_right_window_rejects():
    assert confirm_swings(window([10, 11, 12, 20, 13, 21, 11]), 7, 3, 3) == []


def test_equal_high_on_right_confirms():
    w = window([10, 11, 12, 20, 20, 12, 11])
    assert [s.bar for s in confirm_swings(w, 7, 3, 3) if s.kind == "high"] == [4]


def test_equal_high_on_left_rejects():
    w = window([10, 11, 20, 20, 13, 12, 11])
    assert [s for s in confirm_swings(w, 7, 3, 3) if s.kind == "high"] == []


def test_plateau_gives_first_swing():
    highs = [10, 11, 12, 20, 20, 12, 11, 10]
    found = []
    for t in range(7, len(highs) + 1):
        found += [s.bar for s in confirm_swings(window(highs[:t]), t, 3, 3) if s.kind == "high"]
    assert found == [4]


def test_mirror_low():
    lows = [20, 19, 18, 5, 6, 7, 8]
    w = window([x + 10 for x in lows], lows)
    swings = [s for s in confirm_swings(w, 7, 3, 3) if s.kind == "low"]
    assert [(s.price, s.bar) for s in swings] == [(5, 4)]


def test_not_enough_bars_returns_nothing():
    assert confirm_swings(window([1, 5, 1]), 3, 3, 3) == []


def test_window_may_be_longer_than_pivot_and_bars_are_absolute():
    w = window([1, 1, 1, 1, 10, 11, 12, 20, 13, 12, 11])
    swings = confirm_swings(w, last_bar=111, left=3, right=3)
    assert [(s.price, s.bar) for s in swings if s.kind == "high"] == [(20, 108)]


@pytest.mark.parametrize("pivot", [2, 3, 5, 10])
def test_pivot_lengths_internal_3_htf_5_external_10(pivot):
    highs = [10] * pivot + [50] + [10] * pivot
    swings = confirm_swings(window(highs), len(highs), pivot, pivot)
    assert [(s.price, s.bar) for s in swings if s.kind == "high"] == [(50, pivot + 1)]


def test_worked_example_swings():
    from builders import WORKED

    c = series(WORKED)
    found = []
    for t in range(1, len(c) + 1):
        found += [(s.kind, s.price, s.bar) for s in confirm_swings(c[:t], t, 2, 2)]
    assert found == [("high", 15, 3), ("low", 6, 5), ("high", 17, 7), ("low", 9, 10)]
