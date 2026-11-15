"""Scanner and market endpoints (DD 4.2, 4.3, 7.4; task 2.5; FR-SCAN-01..06, FR-DATA-05/06)."""

import json
from datetime import timedelta

import pytest
from api_support import make_app, new_user, sign_in
from seed_api import T0, insert_setup, set_status

pytestmark = pytest.mark.integration
H = timedelta(hours=1)


@pytest.fixture(scope="module")
def data(db):
    with db.begin() as conn:
        ids = {
            "eur": insert_setup(conn, "EUR_USD", "1h", "bull", 80, ("bos", "displacement", "ob", "sweep"),
                                ("london",), confirm_time=T0),
            "gbp": insert_setup(conn, "GBP_USD", "1h", "bear", 55, ("choch", "displacement", "fvg"),
                                ("new_york",), confirm_time=T0 - H),
            "xau": insert_setup(conn, "XAU_USD", "1h", "bull", 70, ("bos", "displacement", "fvg"),
                                ("london", "new_york"), confirm_time=T0 - 2 * H),
            "jpy": insert_setup(conn, "USD_JPY", "15m", "bull", 65, ("bos", "displacement", "ob"),
                                ("asian",), confirm_time=T0),
            "eur4h": insert_setup(conn, "EUR_USD", "4h", "bear", 50, ("bos", "displacement", "fvg"),
                                  ("london",), confirm_time=T0),
            "dead": insert_setup(conn, "EUR_USD", "1h", "bull", 95, status="invalidated",
                                 confirm_time=T0),
            "wti": insert_setup(conn, "WTICO_USD", "1h", "bear", 60, ("bos", "displacement", "ob"),
                                ("new_york",), confirm_time=T0 - H),
            "tie_a": insert_setup(conn, "GBP_USD", "1h", "bull", 70, confirm_time=T0 - 2 * H,
                                  sid="0" * 31 + "1"),
        }  # fmt: skip
        for code in ("EUR_USD", "GBP_USD", "USD_JPY", "XAU_USD", "WTICO_USD"):
            set_status(conn, code, "ok")
    return ids


@pytest.fixture(scope="module")
def free(db, data):
    app, _, redis = make_app(db)
    email, _ = new_user(db)
    return sign_in(app, email), redis


@pytest.fixture(scope="module")
def pro(db, data):
    app, _, redis = make_app(db)
    email, _ = new_user(db, plan="pro_monthly")
    return sign_in(app, email), redis


def ids_of(r):
    assert r.status_code == 200, r.text
    return [row["id"] for row in r.json()["items"]]


def test_default_timeframe_follows_trading_style(pro, data):
    c, _ = pro
    body = c.get("/api/v1/setups").json()  # intraday user: 1H
    assert {row["timeframe"] for row in body["items"]} == {"1h"}
    assert body["data_as_of"] is not None and body["series_delayed"] == []


def test_filter_instrument(pro, data):
    c, _ = pro
    got = ids_of(c.get("/api/v1/setups", params=[("instrument", "EUR_USD"),
                                                 ("instrument", "XAU_USD")]))  # fmt: skip
    assert got == [data["eur"], data["xau"]]


def test_filter_timeframe_selects_profile(pro, data):
    c, _ = pro
    r = c.get("/api/v1/setups", params={"timeframe": "15m"})
    assert ids_of(r) == [data["jpy"]]
    assert r.json()["items"][0]["profile"] == "scalping"
    r = c.get("/api/v1/setups", params={"timeframe": "4h"})
    assert ids_of(r) == [data["eur4h"]] and r.json()["items"][0]["profile"] == "swing"


def test_filter_direction(pro, data):
    c, _ = pro
    assert ids_of(c.get("/api/v1/setups", params={"direction": "bear"})) == [
        data["wti"],
        data["gbp"],
    ]


def test_filter_pattern_any(pro, data):
    c, _ = pro
    got = ids_of(c.get("/api/v1/setups", params=[("pattern", "sweep"), ("pattern", "choch")]))
    assert got == [data["eur"], data["gbp"]]


def test_filter_session_any(pro, data):
    c, _ = pro
    got = ids_of(c.get("/api/v1/setups", params=[("session", "new_york")]))
    assert got == [data["xau"], data["wti"], data["gbp"]]


def test_filter_min_score(pro, data):
    c, _ = pro
    got = ids_of(c.get("/api/v1/setups", params={"min_score": 70}))
    assert got == [data["eur"], data["tie_a"], data["xau"]]  # ties: newer first, then id


def test_filter_asset_class(pro, data):
    c, _ = pro
    assert ids_of(c.get("/api/v1/setups", params={"asset_class": "metal"})) == [data["xau"]]
    assert ids_of(c.get("/api/v1/setups", params={"asset_class": "energy"})) == [data["wti"]]


def test_only_confirmed_listed(pro, data):
    c, _ = pro
    got = ids_of(c.get("/api/v1/setups", params={"limit": 200}))
    assert data["dead"] not in got
    assert all(row["status"] == "confirmed" for row in c.get("/api/v1/setups").json()["items"])


def test_free_hides_commodities(free, data):
    c, _ = free
    got = ids_of(c.get("/api/v1/setups"))
    assert got == [data["eur"], data["tie_a"], data["gbp"]]
    assert ids_of(c.get("/api/v1/setups", params={"asset_class": "metal"})) == []


def test_row_shape_matches_4_2(pro, data):
    c, _ = pro
    row = c.get("/api/v1/setups").json()["items"][0]
    assert set(row) >= {"id", "instrument", "display_name", "asset_class", "price_scale",
                        "timeframe", "profile", "direction", "patterns", "sessions", "q", "c",
                        "combined", "high_quality", "counter_trend", "zone", "zone_state",
                        "invalidation", "spread", "status", "confirm_time"}  # fmt: skip
    assert row["high_quality"] is True and row["zone"] == {"low": 108000, "high": 108050}
    assert row["confirm_time"].endswith("Z")


def test_keyset_cursor_pages(pro, data):
    c, _ = pro
    seen, cursor = [], None
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        body = c.get("/api/v1/setups", params=params).json()
        seen += [row["id"] for row in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == ids_of(c.get("/api/v1/setups", params={"limit": 200}))
    r = c.get("/api/v1/setups", params={"cursor": "not-a-cursor"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_error"


def test_timeframe_5m_400(pro):
    c, _ = pro
    r = c.get("/api/v1/setups", params={"timeframe": "5m"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_error"


def test_redis_first_then_database(db, data):
    app, _, redis = make_app(db)
    email, _ = new_user(db, plan="pro_monthly")
    c = sign_in(app, email)
    cached = {"id": "c" * 32, "instrument": "EUR_USD", "display_name": "EUR/USD",
              "asset_class": "forex", "price_scale": 5, "timeframe": "1h", "profile": "intraday",
              "direction": "bull", "patterns": ["bos"], "sessions": [], "q": 99, "c": 99,
              "combined": 99, "high_quality": True, "counter_trend": False,
              "zone": {"low": 1, "high": 2}, "zone_state": "confirmed", "invalidation": 1,
              "spread": 0, "status": "confirmed", "confirm_time": "2026-11-16T09:00:00Z"}  # fmt: skip
    redis.set(
        "scanner:bull:1h", json.dumps({"data_as_of": "2026-11-16T09:00:00Z", "items": [cached]})
    )
    redis.set("scanner:bear:1h", json.dumps({"data_as_of": "2026-11-16T09:00:00Z", "items": []}))
    body = c.get("/api/v1/setups").json()
    assert [row["id"] for row in body["items"]] == ["c" * 32]  # the cache, not the database
    assert body["data_as_of"] == "2026-11-16T09:00:00Z"
    redis.delete("scanner:bear:1h")  # a missing list: the database answers
    assert "c" * 32 not in ids_of(c.get("/api/v1/setups"))


def test_delayed_returns_200_with_flag(db, data):
    with db.begin() as conn:
        set_status(conn, "GBP_USD", "delayed")
    try:
        app, _, _ = make_app(db)
        email, _ = new_user(db)
        r = sign_in(app, email).get("/api/v1/setups")
        assert r.status_code == 200
        assert r.json()["series_delayed"] == ["GBP_USD"]
        assert data["gbp"] in ids_of(r)  # the last good data stays listed
    finally:
        with db.begin() as conn:
            set_status(conn, "GBP_USD", "ok")


def test_setup_detail_c_locked_on_strip(free, pro, data):
    c, _ = free
    body = c.get(f"/api/v1/setups/{data['eur']}").json()
    c_factors = [f for f in body["factors"] if f["score"] == "C"]
    assert c_factors and all(f["locked"] and f["points"] is None for f in c_factors)
    assert all(not f["locked"] and f["points"] is not None
               for f in body["factors"] if f["score"] == "Q")  # fmt: skip
    assert body["c"] == 80  # C itself is shown (FR-CHART-03)
    assert body["explanation"] and body["rule_version"] == "r1.0"
    assert [r["status"] for r in body["revisions"]] == ["confirmed"]
    assert {m["role"] for m in body["mtf"]} == {"setup", "context", "confirmation"}
    full = pro[0].get(f"/api/v1/setups/{data['eur']}").json()
    assert all(not f["locked"] and f["points"] is not None for f in full["factors"])


def test_commodity_setup_detail_403_free(free, pro, data):
    r = free[0].get(f"/api/v1/setups/{data['xau']}")
    assert r.status_code == 403
    err = r.json()["error"]
    assert err["code"] == "plan_required" and err["details"]["limit_key"] == "asset_classes"
    assert err["details"]["upgrade"] is True
    assert pro[0].get(f"/api/v1/setups/{data['xau']}").status_code == 200
    assert free[0].get("/api/v1/setups/" + "9" * 32).status_code == 404


def test_instruments_available_flags(free):
    c, _ = free
    items = {i["code"]: i for i in c.get("/api/v1/instruments").json()["items"]}
    assert len(items) == 11
    assert items["EUR_USD"]["available"] and not items["XAU_USD"]["available"]
    assert items["USD_JPY"]["price_scale"] == 3 and items["EUR_USD"]["display_name"]


def test_prices_entitled_and_stale(free):
    c, redis = free
    fresh = {"instrument": "EUR_USD", "bid": 108000, "ask": 108000, "mid": 108000,
             "price_scale": 5, "time": "2026-11-16T12:00:00Z", "stale": False}  # fmt: skip
    old = dict(fresh, instrument="GBP_USD", time="2026-11-16T10:00:00Z")
    gold = dict(fresh, instrument="XAU_USD", price_scale=3)
    for p in (fresh, old, gold):
        redis.set(f"price:{p['instrument']}", json.dumps(p))
    r = c.get("/api/v1/prices", params={"instruments": "EUR_USD,GBP_USD,XAU_USD,AUD_USD"})
    items = {p["instrument"]: p for p in r.json()["items"]}
    assert set(items) == {"EUR_USD", "GBP_USD"}  # gold not entitled, AUD has no price yet
    assert items["EUR_USD"]["stale"] is False and items["GBP_USD"]["stale"] is True


def test_status_data(free, data):
    c, _ = free
    items = c.get("/api/v1/status/data").json()["items"]
    eur = [s for s in items if s["instrument"] == "EUR_USD" and s["timeframe"] == "5m"]
    assert eur and eur[0]["status"] == "ok" and eur[0]["last_candle_time"].endswith("Z")
    assert not any(s["instrument"] == "XAU_USD" for s in items)  # not entitled on Free


def test_series_delayed_lists_only_entitled_instruments(db, data):
    """Review fix: a Free user is not told about commodity series."""
    with db.begin() as conn:
        set_status(conn, "XAU_USD", "delayed")
    try:
        app, _, _ = make_app(db)
        email, _ = new_user(db)
        assert sign_in(app, email).get("/api/v1/setups").json()["series_delayed"] == []
        email, _ = new_user(db, plan="pro_monthly")
        assert sign_in(app, email).get("/api/v1/setups").json()["series_delayed"] == ["XAU_USD"]
    finally:
        with db.begin() as conn:
            set_status(conn, "XAU_USD", "ok")
