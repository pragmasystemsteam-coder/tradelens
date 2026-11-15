"""DD 4.1 error body on every failure (task 2.4)."""

from api_support import client, make_app


def test_error_body_shape():
    app, _, _ = make_app(engine=None)
    c = client(app)
    r = c.get("/api/v1/does-not-exist", headers={"X-Request-ID": "rid-1"})
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found", "message": "Not found",
                                  "request_id": "rid-1", "details": {}}}  # fmt: skip
    r = c.post("/api/v1/auth/login", json={"email": "a@b.co", "password": "x" * 10, "extra": 1})
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "validation_error" and err["request_id"] == r.headers["X-Request-ID"]
    assert {"field": "extra", "issue": "extra_forbidden"} in err["details"]["errors"]
    r = c.get("/api/v1/me")  # no session cookie
    assert r.status_code == 401 and r.json()["error"]["code"] == "not_authenticated"


def test_unhandled_error_is_500_with_request_id():
    app, _, _ = make_app(engine=None)

    @app.get("/api/v1/boom")
    def boom():
        raise RuntimeError("secret detail")

    r = client(app).get("/api/v1/boom", headers={"X-Request-ID": "rid-2"})
    assert r.status_code == 500
    assert r.json()["error"] == {"code": "internal_error", "message": "Internal error",
                                 "request_id": "rid-2", "details": {}}  # fmt: skip
    assert "secret" not in r.text
