"""Watchlists (DD 4.2, 4.3, 7.4; task 2.7; FR-WATCH-01, FR-WATCH-02, NFR-10)."""

import json

import pytest
from api_support import make_app, new_user, sign_in
from seed_api import T0, insert_setup, set_status

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def data(db):
    with db.begin() as conn:
        best = insert_setup(conn, "EUR_USD", "1h", "bull", 82, confirm_time=T0)
        insert_setup(conn, "EUR_USD", "4h", "bear", 61, confirm_time=T0)
        insert_setup(conn, "EUR_USD", "1h", "bull", 95, status="invalidated", confirm_time=T0)
        set_status(conn, "EUR_USD", "ok", T0)
        set_status(conn, "GBP_USD", "delayed", T0)
    return {"best": best}


def client_for(db, plan=None):
    app, _, redis = make_app(db)
    email, _ = new_user(db, plan=plan)
    return sign_in(app, email), redis


def test_second_watchlist_free_403_upgrade(db):
    c, _ = client_for(db)
    assert c.post("/api/v1/watchlists", json={"name": "Majors"}).status_code == 201
    r = c.post("/api/v1/watchlists", json={"name": "Second"})
    assert r.status_code == 403
    err = r.json()["error"]
    assert err["code"] == "plan_required"
    assert err["details"] == {"limit_key": "max_watchlists", "limit": 1, "current": 1,
                              "upgrade": True}  # fmt: skip
    body = c.get("/api/v1/watchlists").json()
    assert [w["name"] for w in body["items"]] == ["Majors"]
    assert body["limits"] == {"max_watchlists": 1, "max_watchlist_items": 11}


def test_fourth_watchlist_pro_422(db):
    c, _ = client_for(db, "pro_monthly")
    for name in ("A", "B", "C"):
        assert c.post("/api/v1/watchlists", json={"name": name}).status_code == 201
    r = c.post("/api/v1/watchlists", json={"name": "D"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "plan_limit"
    assert r.json()["error"]["details"]["upgrade"] is False
    dup = c.post("/api/v1/watchlists", json={"name": "A"})
    assert dup.status_code in (409, 422)  # at the cap the limit answers first


def test_duplicate_name_conflict_and_rename_delete(db):
    c, _ = client_for(db, "pro_monthly")
    a = c.post("/api/v1/watchlists", json={"name": "Alpha"}).json()["id"]
    assert c.post("/api/v1/watchlists", json={"name": "Alpha"}).status_code == 409
    b = c.post("/api/v1/watchlists", json={"name": "Beta"}).json()["id"]
    assert c.patch(f"/api/v1/watchlists/{b}", json={"name": "Alpha"}).status_code == 409
    assert c.patch(f"/api/v1/watchlists/{b}", json={"name": "Gamma"}).status_code == 200
    assert c.delete(f"/api/v1/watchlists/{a}").status_code == 204
    assert [w["name"] for w in c.get("/api/v1/watchlists").json()["items"]] == ["Gamma"]


def test_add_commodity_free_403(db):
    c, _ = client_for(db)
    wid = c.post("/api/v1/watchlists", json={"name": "Mine"}).json()["id"]
    r = c.put(f"/api/v1/watchlists/{wid}/items/XAU_USD")
    assert r.status_code == 403 and r.json()["error"]["details"]["limit_key"] == "asset_classes"
    assert c.put(f"/api/v1/watchlists/{wid}/items/EUR_USD").status_code == 204
    assert c.put(f"/api/v1/watchlists/{wid}/items/EUR_USD").status_code == 204  # idempotent
    assert c.put(f"/api/v1/watchlists/{wid}/items/NOPE").status_code == 404
    assert c.get("/api/v1/watchlists").json()["items"][0]["instruments"] == ["EUR_USD"]
    assert c.delete(f"/api/v1/watchlists/{wid}/items/EUR_USD").status_code == 204
    assert c.get("/api/v1/watchlists").json()["items"][0]["instruments"] == []


def test_best_setup_and_data_status(db, data):
    c, redis = client_for(db)
    wid = c.post("/api/v1/watchlists", json={"name": "Watch"}).json()["id"]
    for code in ("EUR_USD", "GBP_USD"):
        assert c.put(f"/api/v1/watchlists/{wid}/items/{code}").status_code == 204
    redis.set("price:EUR_USD", json.dumps({"instrument": "EUR_USD", "bid": 108001, "ask": 108001,
                                          "mid": 108001, "price_scale": 5,
                                          "time": "2026-11-16T12:00:00Z", "stale": False}))  # fmt: skip
    body = c.get(f"/api/v1/watchlists/{wid}").json()
    items = {i["instrument"]: i for i in body["items"]}
    eur, gbp = items["EUR_USD"], items["GBP_USD"]
    assert eur["best_setup"]["id"] == data["best"] and eur["best_setup"]["combined"] == 82
    assert eur["data_status"] == "ok" and eur["last_price"] == 108001
    assert eur["price_scale"] == 5 and eur["custom_applied"] is False
    assert gbp["data_status"] == "delayed" and gbp["best_setup"] is None
    assert gbp["last_price"] is None
    assert body["name"] == "Watch"


def test_cross_user_watchlist_404(db):
    a, _ = client_for(db)
    b, _ = client_for(db)
    wid = a.post("/api/v1/watchlists", json={"name": "Private"}).json()["id"]
    assert b.get(f"/api/v1/watchlists/{wid}").status_code == 404
    assert b.patch(f"/api/v1/watchlists/{wid}", json={"name": "x"}).status_code == 404
    assert b.delete(f"/api/v1/watchlists/{wid}").status_code == 404
    assert b.put(f"/api/v1/watchlists/{wid}/items/EUR_USD").status_code == 404
    assert b.delete(f"/api/v1/watchlists/{wid}/items/EUR_USD").status_code == 404
    assert b.get("/api/v1/watchlists/not-a-uuid").status_code == 404
    assert a.get(f"/api/v1/watchlists/{wid}").status_code == 200


def test_watchlist_items_capped(db):
    c, _ = client_for(db, "pro_monthly")
    wid = c.post("/api/v1/watchlists", json={"name": "All"}).json()["id"]
    codes = [i["code"] for i in c.get("/api/v1/instruments").json()["items"]]
    for code in codes:  # 11 instruments, max_watchlist_items is 11
        assert c.put(f"/api/v1/watchlists/{wid}/items/{code}").status_code == 204
    assert len(c.get(f"/api/v1/watchlists/{wid}").json()["items"]) == 11


def test_profile_needs_custom_settings(db):
    c, _ = client_for(db)
    wid = c.post("/api/v1/watchlists", json={"name": "P"}).json()["id"]
    r = c.get(f"/api/v1/watchlists/{wid}", params={"profile_version_id": "x"})
    assert r.status_code == 403 and r.json()["error"]["details"]["limit_key"] == "custom_settings"
