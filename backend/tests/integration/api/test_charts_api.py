"""Charts and candles (DD 4.2 charts, 4.3, 7.4; task 2.6; FR-CHART-01..05, FR-CUST-04)."""

from datetime import UTC, datetime, timedelta

import pytest
from api_support import Clock, make_app, new_user, sign_in
from seed_api import hexid, official_hash, rule_doc, set_status
from sqlalchemy import text

from tradelens.integrations.fakes.synthetic import SyntheticProvider
from tradelens.modules.analysis.output_store import SqlAnalysisStore
from tradelens.modules.analysis.process import to_engine
from tradelens.modules.analysis.public import CloseBatch, official_settings
from tradelens.modules.market_data.candles import to_stored
from tradelens.modules.market_data.ports import RawBar
from tradelens.modules.market_data.public import SqlCandleStore, load_instrument_specs
from tradelens_engine.multi import step_batch

pytestmark = pytest.mark.integration
END = datetime(2026, 11, 13, 21, 0, tzinfo=UTC)
KEYS = {"instrument", "timeframe", "price_scale", "settings", "status", "candles", "has_more",
        "events", "zones", "htf_zones", "liquidity", "setups", "trend_strip", "provisional",
        "live_price", "forming"}  # fmt: skip


@pytest.fixture(scope="module")
def data(db, repo):
    provider = SyntheticProvider(load_instrument_specs(repo / "config"), lambda: END)
    with db.begin() as conn:
        store = SqlCandleStore(conn)
        for code, count in (("EUR_USD", 2100), ("XAU_USD", 50)):
            bars = provider.fetch(code, "1h", count=count, end=END - timedelta(hours=1))
            store.add([to_stored(b, code, "1h", "synthetic") for b in bars])
        rows = store.load("EUR_USD", "1h", None)
        cfg = official_settings(rule_doc())
        result = step_batch({}, {"1h": [to_engine(r) for r in rows]}, cfg,
                            instrument="EUR_USD", rule_version="r1.0")  # fmt: skip
        SqlAnalysisStore(conn).save_batch(CloseBatch("EUR_USD", official_hash(), "r1.0", result))
        conn.execute(text(
            "INSERT INTO zones (id, kind, instrument, timeframe, settings_hash, rule_version,"
            " direction, low, high, origin_time, confirm_time, state, state_time) VALUES (:id,"
            " 'fvg', 'EUR_USD', '4h', :h, 'r1.0', 'bull', 108000, 108100, :o, :t, 'confirmed', :t)"),
            {"id": hexid(), "h": official_hash(), "o": END - timedelta(days=3),
             "t": END - timedelta(days=2)})  # fmt: skip
        set_status(conn, "EUR_USD", "ok", END)
    return rows


@pytest.fixture(scope="module")
def repo(request):
    return request.config.rootpath


@pytest.fixture(scope="module")
def free(db, data):
    app, _, _ = make_app(db)
    email, _ = new_user(db)
    return sign_in(app, email)


@pytest.fixture(scope="module")
def pro(db, data):
    app, _, _ = make_app(db)
    email, _ = new_user(db, plan="pro_annual")
    return sign_in(app, email)


def test_chart_shape_matches_4_2(free, data):
    body = free.get("/api/v1/charts/EUR_USD/1h").json()
    assert set(body) == KEYS
    assert body["price_scale"] == 5 and body["timeframe"] == "1h"
    assert body["settings"]["kind"] == "official" and body["settings"]["rule_version"] == "r1.0"
    assert body["settings"]["settings_hash"] == official_hash()
    assert len(body["candles"]) == 500
    assert set(body["candles"][0]) == {"t", "o", "h", "l", "c", "spread"}
    assert body["candles"][-1]["t"] == data[-1].open_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert body["events"] and {"id", "type", "direction", "level", "origin_time",
                                "confirm_time"} <= set(body["events"][0])  # fmt: skip
    z = body["zones"][0]
    assert {"id", "kind", "direction", "low", "high", "state", "retests",
            "pre_confirmation_touch", "origin_time", "confirm_time"} <= set(z)  # fmt: skip
    assert body["status"]["state"] == "ok"


def test_trend_strip_5_timeframes(free):
    strip = free.get("/api/v1/charts/EUR_USD/1h").json()["trend_strip"]
    assert [s["timeframe"] for s in strip] == ["1d", "4h", "1h", "15m", "5m"]
    one = strip[2]
    assert one["internal"] in ("bull", "bear", "neutral") and one["as_of"] is not None
    assert strip[0]["internal"] == "neutral" and strip[0]["as_of"] is None  # no 1D state yet


def test_provisional_swings_not_stored(db, free, data):
    with db.begin() as conn:
        before = conn.execute(text("SELECT count(*) FROM market_events")).scalar()
    body = free.get("/api/v1/charts/EUR_USD/1h").json()
    swings = body["provisional"]["swings"]
    recent = {c.open_time.strftime("%Y-%m-%dT%H:%M:%SZ") for c in data[-10:]}
    assert all(s["origin_time"] in recent and "id" not in s for s in swings)
    with db.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM market_events")).scalar() == before


def test_htf_zones_empty_on_strip(free, pro):
    assert free.get("/api/v1/charts/EUR_USD/1h").json()["htf_zones"] == []
    htf = pro.get("/api/v1/charts/EUR_USD/1h").json()["htf_zones"]
    assert [z["timeframe"] for z in htf] == ["4h"]


def test_history_capped_500_free_2000_pro(free, pro):
    r = free.get("/api/v1/charts/EUR_USD/1h", params={"limit": 1000}).json()
    assert len(r["candles"]) == 500 and r["has_more"] is False
    c = free.get("/api/v1/candles/EUR_USD/1h", params={"limit": 1000}).json()
    assert len(c["candles"]) == 500 and c["has_more"] is False and c["price_scale"] == 5
    first = pro.get("/api/v1/candles/EUR_USD/1h", params={"limit": 1000}).json()
    assert len(first["candles"]) == 1000 and first["has_more"] is True
    second = pro.get("/api/v1/candles/EUR_USD/1h",
                     params={"limit": 1000, "before": first["candles"][0]["t"]}).json()  # fmt: skip
    assert len(second["candles"]) == 1000 and second["has_more"] is False
    assert second["candles"][-1]["t"] < first["candles"][0]["t"]
    third = pro.get("/api/v1/charts/EUR_USD/1h",
                    params={"limit": 1000, "before": second["candles"][0]["t"]}).json()  # fmt: skip
    assert third["candles"] == [] and third["has_more"] is False  # never beyond 2,000


def test_commodity_chart_403_free(free, pro):
    for path in ("/api/v1/charts/XAU_USD/1h", "/api/v1/candles/XAU_USD/1h"):
        r = free.get(path)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "plan_required"
        assert r.json()["error"]["details"]["limit_key"] == "asset_classes"
    assert pro.get("/api/v1/charts/XAU_USD/1h").status_code == 200


def test_custom_chart_rate_limit_20(db, data):
    app, _, _ = make_app(db)
    email, _ = new_user(db)
    c = sign_in(app, email)
    codes = [c.get("/api/v1/charts/EUR_USD/1h", params={"preset": "scalping"}) for _ in range(21)]
    assert [r.status_code for r in codes[:20]] == [200] * 20
    assert codes[20].status_code == 429 and codes[20].json()["error"]["code"] == "rate_limited"
    body = codes[0].json()
    assert body["settings"]["kind"] == "preset" and body["settings"]["preset"] == "scalping"
    assert body["settings"]["settings_hash"] != official_hash()
    assert body["setups"] == [] and len(body["candles"]) == 500
    # The official chart is not counted.
    assert c.get("/api/v1/charts/EUR_USD/1h").status_code == 200


def test_liquidity_kinds_and_end_reason(free):
    levels = free.get("/api/v1/charts/EUR_USD/1h").json()["liquidity"]
    allowed = {"swing_high", "swing_low", "eqh", "eql", "pdh", "pdl", "pwh", "pwl", "asian_high",
               "asian_low", "london_high", "london_low", "ny_high", "ny_low"}  # fmt: skip
    assert levels
    for lv in levels:
        assert lv["kinds"] and set(lv["kinds"]) <= allowed and lv["side"] in ("buy", "sell")
        if lv["status"] == "ended":
            assert lv["end_reason"] in ("swept", "breakout", "superseded", "merged", "expired")
            assert lv["end_time"] is not None
        else:
            assert lv["status"] == "active" and lv["end_reason"] is None
    assert any(lv["status"] == "ended" for lv in levels)
    assert any(lv["status"] == "active" for lv in levels)


def test_include_inactive_and_errors(free):
    base = free.get("/api/v1/charts/EUR_USD/1h").json()["zones"]
    assert all(z["state"] not in ("invalidated", "expired") for z in base)
    every = free.get("/api/v1/charts/EUR_USD/1h", params={"include_inactive": 1}).json()["zones"]
    assert len(every) >= len(base)
    assert free.get("/api/v1/charts/NOPE_USD/1h").status_code == 404
    r = free.get("/api/v1/charts/EUR_USD/2h")
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_error"
    r = free.get("/api/v1/charts/EUR_USD/1h", params={"preset": "nope"})
    assert r.status_code == 400
    r = free.get("/api/v1/charts/EUR_USD/1h", params={"profile_version_id": hexid()})
    assert r.status_code == 403 and r.json()["error"]["details"]["limit_key"] == "custom_settings"


def test_forming_candle_from_5m_display_only(db, data):
    """The open 1H period is built from its finished 5m candles; 5m and delayed data get none."""
    with db.begin() as conn:
        SqlCandleStore(conn).add([
            to_stored(RawBar(END + timedelta(minutes=5 * i), *ohlc), "EUR_USD", "5m", "synthetic")
            for i, ohlc in enumerate([(108000, 108050, 107990, 108020),
                                      (108020, 108090, 108010, 108080)])
        ])  # fmt: skip
    app, _, _ = make_app(db, clock=Clock(END + timedelta(minutes=12)))
    email, _ = new_user(db)
    client = sign_in(app, email)
    body = client.get("/api/v1/charts/EUR_USD/1h").json()
    assert body["forming"] == {
        "t": "2026-11-13T21:00:00Z",
        "o": 108000,
        "h": 108090,
        "l": 107990,
        "c": 108080,
        "closes_at": "2026-11-13T22:00:00Z",
    }
    assert body["candles"][-1]["t"] == "2026-11-13T20:00:00Z"  # finished candles unchanged
    assert client.get("/api/v1/charts/EUR_USD/5m").json()["forming"] is None
    older = client.get("/api/v1/charts/EUR_USD/1h", params={"before": "2026-11-12T00:00:00Z"})
    assert older.json()["forming"] is None
    with db.begin() as conn:
        set_status(conn, "EUR_USD", "delayed", END)
    try:
        assert client.get("/api/v1/charts/EUR_USD/1h").json()["forming"] is None
    finally:
        with db.begin() as conn:
            set_status(conn, "EUR_USD", "ok", END)


def test_analysis_lists_everything_and_never_stores_candidates(db, data):
    """CR-006: computed on request; candidates are labelled and never written."""
    app, _, _ = make_app(db, clock=Clock(END))
    email, _ = new_user(db)
    client = sign_in(app, email)
    with db.connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM setups")).scalar_one()
    r = client.get("/api/v1/analysis/EUR_USD/1h")
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"trend_strip", "structure", "zones", "liquidity", "setups", "pattern_counts",
            "candidates"} <= set(body)  # fmt: skip
    assert len(body["trend_strip"]) == 5
    assert set(body["pattern_counts"]) == {"bos", "choch", "sweep", "fvg", "ob", "displacement"}
    assert body["structure"], "the engine output has recent structure events"
    for cand in body["candidates"]:
        assert cand["label"] == "Candidate, not a setup"
        assert {k["code"] for k in cand["checks"]} == {"break", "displacement", "zone_in_move"}
        assert all(f["locked"] for f in cand["factors"] if f["score"] == "C")  # Free
    with db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM setups")).scalar_one() == before
    assert client.get("/api/v1/analysis/XAU_USD/1h").status_code == 403
    assert client.get("/api/v1/analysis/NOPE_X/1h").status_code == 404
