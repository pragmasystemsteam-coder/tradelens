"""Fair value gaps (FR-SMC-06, DD 3.4 and 7.2 FVG)."""

from builders import bar

from tradelens_engine.rules.fvg import Fvg, detect_fvg


def three(a_hl, c_hl, b_hl=(30, 0)):
    return bar(1, *a_hl), bar(2, *b_hl), bar(3, *c_hl)


def test_bullish_fvg_requires_strict_gap():
    a, b, c = three((10, 5), (20, 12))  # c.l 12 > a.h 10
    assert detect_fvg(a, b, c, bar=3, atr_k=None, fvg_min_m=0) == Fvg(
        "bull", 10, 12, a.open_time, c.close_time, 3
    )


def test_equal_values_no_gap():
    a, b, c = three((10, 5), (20, 10))
    assert detect_fvg(a, b, c, bar=3, atr_k=None, fvg_min_m=0) is None


def test_overlap_of_one_unit_no_gap():
    a, b, c = three((10, 5), (20, 9))
    assert detect_fvg(a, b, c, bar=3, atr_k=None, fvg_min_m=0) is None


def test_bearish_fvg():
    a, b, c = three((30, 20), (15, 5))  # c.h 15 < a.l 20
    assert detect_fvg(a, b, c, bar=3, atr_k=None, fvg_min_m=0) == Fvg(
        "bear", 15, 20, a.open_time, c.close_time, 3
    )


def test_min_size_filters_with_atr():
    a, b, c = three((10, 5), (20, 12))  # gap 2 units
    # atr_k = 4000 (ATR 4.000 units): 250 thousandths -> minimum 1 unit, 1000 -> 4 units
    assert detect_fvg(a, b, c, bar=3, atr_k=4000, fvg_min_m=250) is not None
    assert detect_fvg(a, b, c, bar=3, atr_k=4000, fvg_min_m=500) is not None  # exactly 2 = 2
    assert detect_fvg(a, b, c, bar=3, atr_k=4000, fvg_min_m=1000) is None


def test_min_size_without_atr_not_created():
    a, b, c = three((10, 5), (20, 12))
    assert detect_fvg(a, b, c, bar=3, atr_k=None, fvg_min_m=250) is None


def test_min_size_zero_off():
    a, b, c = three((10, 5), (20, 11))
    assert detect_fvg(a, b, c, bar=3, atr_k=None, fvg_min_m=0) is not None
