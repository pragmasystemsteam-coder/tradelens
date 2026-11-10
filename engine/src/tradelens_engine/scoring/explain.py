"""Template explanations, no AI (DD 3.7; FR-MTF-08, AD-13).

"{Direction} {pattern} setup, combined {combined} (Q {q}, C {c}). Met: {sentences}. Missed:
{sentences}." Each reason code has one fixed sentence. Prices print from integers
(units / 10**scale); ATR multiples are ``x * 1_000_000 // atr_k`` thousandths shown with two
decimals. The disclaimer is added by the API and the UI, not stored here.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tradelens_engine.scoring.model import Factor, Setup

BREAK_NAMES = {"bos": "BOS", "choch": "CHoCH"}
SESSION_NAMES = {"london": "London", "new_york": "New York"}
TF_NAMES = {"5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "1D"}
KIND_NAMES = {"ob": "order block", "fvg": "fair value gap"}
THOUSAND = 1000
TIMES = chr(0xD7)  # the multiplication sign of DD 3.7 ("2.62 x ATR")
HUNDREDTHS = 10


def price(units: int, scale: int) -> str:
    """Integer smallest units as a decimal string (no float)."""
    sign, digits = ("-" if units < 0 else ""), str(abs(units))
    if scale == 0:
        return sign + digits
    digits = digits.rjust(scale + 1, "0")
    return f"{sign}{digits[:-scale]}.{digits[-scale:]}"


def multiple(thousandths: int) -> str:
    """Thousandths as ``x.xx`` (truncated, integer arithmetic)."""
    return f"{thousandths // THOUSAND}.{thousandths % THOUSAND // HUNDREDTHS:02d}"


def _tfs(tfs: tuple[str, ...]) -> str:
    return " and ".join(TF_NAMES.get(tf, tf) for tf in tfs)


def _tail(f: Factor) -> str:
    return f"(+{f.points} of {f.max})" if f.points > 0 else f"(0 of {f.max})"


class _Ctx:
    """What the templates need besides the factor."""

    def __init__(self, s: Setup) -> None:
        c = s.candidate
        self.bull = c.direction == "bull"
        self.adj = "bullish" if self.bull else "bearish"
        self.brk = BREAK_NAMES.get(c.break_type, c.break_type)
        self.scale = s.price_scale

    def p(self, units: int) -> str:
        return price(units, self.scale)


def _break(f: Factor, x: _Ctx) -> str:
    side = "above" if x.bull else "below"
    strength = "strong displacement" if f.reason == "strong" else "displacement that was not strong"
    return (f"A {x.adj} {x.brk} closed {side} {x.p(f.arg('level'))} with a "
            f"{f.arg('candles')}-candle {strength} {_tail(f)}.")  # fmt: skip


def _sweep(f: Factor, x: _Ctx) -> str:
    side = "Sell-side" if x.bull else "Buy-side"
    if f.reason == "sweep_found":
        return f"{side} liquidity was swept shortly before the break {_tail(f)}."
    return f"No same-direction liquidity sweep before the break {_tail(f)}."


def _room(f: Factor, x: _Ctx) -> str:
    if f.reason == "no_atr":
        return f"The ATR is not available yet {_tail(f)}."
    if f.reason == "no_opposing_level":
        return f"No opposing liquidity level is known {_tail(f)}."
    side, where = ("buy-side", "above") if x.bull else ("sell-side", "below")
    distance = f"{multiple(f.arg('multiple_k'))} {TIMES} ATR"
    return (
        f"The nearest {side} level {x.p(f.arg('level'))} is {distance} {where} the zone {_tail(f)}."
    )


def _spread(f: Factor, x: _Ctx) -> str:
    if f.reason == "wide_spread":
        return (f"The break candle's spread ({x.p(f.arg('spread'))}) was wider than normal "
                f"({x.p(f.arg('normal'))}) {_tail(f)}.")  # fmt: skip
    if f.reason == "off_session":
        return f"The break came outside the London and New York sessions {_tail(f)}."
    session = SESSION_NAMES.get(f.arg("session"), f.arg("session"))
    return f"Normal spread during the {session} session {_tail(f)}."


def _trend(f: Factor, x: _Ctx) -> str:
    if f.reason == "not_ready":
        return f"Higher-timeframe data is not ready yet {_tail(f)}."
    agree, others = f.arg("agree"), f.arg("others")
    if f.reason == "agree_all":
        noun = "trends are" if len(agree) > 1 else "trend is"
        return f"The {_tfs(agree)} {noun} {x.adj} {_tail(f)}."
    if f.reason == "agree_one":
        return f"The {_tfs(agree)} trend is {x.adj} but the {_tfs(others)} trend is not {_tail(f)}."
    return f"No higher-timeframe trend is {x.adj} {_tail(f)}."


def _zone(f: Factor, x: _Ctx) -> str:
    if f.reason == "inside":
        tf, kind = TF_NAMES.get(f.arg("tf"), f.arg("tf")), KIND_NAMES[f.arg("kind")]
        return f"The zone lies inside a {x.adj} {tf} {kind} {_tail(f)}."
    return f"The zone is not inside a higher-timeframe zone {_tail(f)}."


def _ltf(f: Factor, x: _Ctx) -> str:
    if f.reason == "confirmed":
        tf = TF_NAMES.get(f.arg("tf"), f.arg("tf"))
        brk = BREAK_NAMES.get(f.arg("break_type"), f.arg("break_type"))
        return f"A {tf} {brk} confirmed the zone after price returned to it {_tail(f)}."
    if f.reason == "waiting":
        return f"No lower-timeframe confirmation yet {_tail(f)}."
    return f"Price has not returned to the zone yet {_tail(f)}."


def _conflict(f: Factor, x: _Ctx) -> str:
    if f.reason == "not_ready":
        return f"Higher-timeframe zones are not known yet {_tail(f)}."
    if f.reason == "conflict":
        tf, kind = TF_NAMES.get(f.arg("tf"), f.arg("tf")), KIND_NAMES[f.arg("kind")]
        return f"An opposite {tf} {kind} lies within 1 {TIMES} ATR of the zone {_tail(f)}."
    return f"No opposite higher-timeframe zone within 1 {TIMES} ATR {_tail(f)}."


def _simple(found: str, missed: str) -> Callable[[Factor, _Ctx], str]:
    def sentence(f: Factor, _x: _Ctx) -> str:
        return f"{found if f.points > 0 else missed} {_tail(f)}."

    return sentence


def _ob(f: Factor, _x: _Ctx) -> str:
    text = {"ob_fresh": "The order block was not touched before confirmation",
            "ob_pre_touched": "The order block was touched before confirmation",
            "no_ob": "No order block in the move"}[f.reason]  # fmt: skip
    return f"{text} {_tail(f)}."


TEMPLATES: dict[str, Callable[[Factor, _Ctx], str]] = {
    "break": _break,
    "sweep": _sweep,
    "fvg": _simple("A fair value gap formed in the move", "No fair value gap in the move"),
    "ob_fresh": _ob,
    "room": _room,
    "spread_session": _spread,
    "htf_trend": _trend,
    "htf_zone": _zone,
    "ltf_confirm": _ltf,
    "no_conflict": _conflict,
}


def sentences(setup: Setup) -> list[str]:
    """One sentence per factor, in factor order (Q first, then C)."""
    x = _Ctx(setup)
    return [TEMPLATES[f.code](f, x) for f in setup.factors]


def explain(setup: Setup) -> str:
    """The explanation: met factors first, then missed ones (FR-MTF-08)."""
    x = _Ctx(setup)
    met = [TEMPLATES[f.code](f, x) for f in setup.factors if f.points > 0]
    missed = [TEMPLATES[f.code](f, x) for f in setup.factors if f.points == 0]
    head = (f"{x.adj.capitalize()} {x.brk} setup, combined {setup.combined} "
            f"(Q {setup.q}, C {setup.c}).")  # fmt: skip
    return f"{head} Met: {' '.join(met) or 'none.'} Missed: {' '.join(missed) or 'none.'}"
