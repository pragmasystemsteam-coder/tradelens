"""Run the Playwright smoke scripts against a throwaway local stack (``make e2e``; DD 7.7).

``--load`` runs ``scripts/loadcheck.py`` against the API instead (task 2.10).

Starts PostgreSQL 16 and Redis 7 containers on 127.0.0.1, migrates and seeds the database,
adds two test users (Free and Pro) with fresh random passwords, synthetic 1H candles with
engine output and four setups, then runs the API (uvicorn) and the customer web app
(``next start``, proxying ``/api`` to the API) and finally ``npx playwright test`` in
``web/``. Everything is removed afterwards. Playwright uses the installed Google Chrome
(``channel: chrome``), so no browser download is needed.

Never point this at real data: it creates and deletes its own containers.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"
PG, REDIS = "tradelens-e2e-db", "tradelens-e2e-redis"
PG_PORT, REDIS_PORT, API_PORT, WEB_PORT = 55433, 56379, 8100, 3100
PASSWORD = "e2e-only"  # noqa: S105 - throwaway local container bound to 127.0.0.1
OWNER, DB = "tradelens_owner", "tradelens_e2e"
DB_URL = f"postgresql+psycopg://{OWNER}:{PASSWORD}@127.0.0.1:{PG_PORT}/{DB}"
WAIT_S = 90
LOAD_USERS = 17  # 100 SSE streams at 6 per user
NPX = "npx.cmd" if os.name == "nt" else "npx"
NPM = "npm.cmd" if os.name == "nt" else "npm"
FACTORS = [
    {"code": "break", "score": "Q", "points": 25, "max": 25, "reason": "strong"},
    {"code": "sweep", "score": "Q", "points": 20, "max": 20, "reason": "sweep_found"},
    {"code": "fvg", "score": "Q", "points": 20, "max": 20, "reason": "fvg_found"},
    {"code": "ob_fresh", "score": "Q", "points": 15, "max": 15, "reason": "ob_fresh"},
    {"code": "room", "score": "Q", "points": 8, "max": 15, "reason": "room_ge1"},
    {"code": "spread_session", "score": "Q", "points": 5, "max": 5, "reason": "ok"},
    {"code": "htf_trend", "score": "C", "points": 40, "max": 40, "reason": "agree_all"},
    {"code": "htf_zone", "score": "C", "points": 0, "max": 30, "reason": "none"},
    {"code": "ltf_confirm", "score": "C", "points": 0, "max": 30, "reason": "pending"},
]
SETUPS = [("EUR_USD", "forex", "bull", 72), ("GBP_USD", "forex", "bear", 64),
          ("USD_JPY", "forex", "bull", 48), ("XAU_USD", "metal", "bull", 70)]  # fmt: skip


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run docker with Git Bash path conversion disabled."""
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    return subprocess.run(  # noqa: S603
        ["docker", *args],  # noqa: S607 - docker from PATH, as in the Makefile
        check=check, text=True, capture_output=True, env=env,
    )  # fmt: skip


def start_containers() -> None:
    """PostgreSQL with the project's init scripts, and Redis."""
    for name in (PG, REDIS):
        docker("rm", "-f", name, check=False)
    init_dir = (REPO / "deploy" / "postgres-init").as_posix()
    docker(
        "run", "-d", "--rm", "--name", PG, "-p", f"127.0.0.1:{PG_PORT}:5432",
        "-e", f"POSTGRES_USER={OWNER}", "-e", f"POSTGRES_PASSWORD={PASSWORD}",
        "-e", f"POSTGRES_DB={DB}", "-e", "APP_DB_USER=tradelens_app",
        "-e", f"APP_DB_PASSWORD={PASSWORD}",
        "-v", f"{init_dir}:/docker-entrypoint-initdb.d:ro", "postgres:16-alpine",
    )  # fmt: skip
    docker("run", "-d", "--rm", "--name", REDIS, "-p", f"127.0.0.1:{REDIS_PORT}:6379",
           "redis:7-alpine")  # fmt: skip
    deadline = time.monotonic() + WAIT_S
    dsn = f"postgresql://{OWNER}:{PASSWORD}@127.0.0.1:{PG_PORT}/{DB}"
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=2) as conn:
                found = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'tradelens_app'")
                if found.fetchone():
                    return
        except psycopg.OperationalError:
            pass
        time.sleep(1)
    raise SystemExit("PostgreSQL E2E container not ready")


def seed_data() -> dict[str, str]:
    """Migrate, seed, add users, candles, engine output and setups; return E2E settings."""
    from alembic import command
    from alembic.config import Config
    from argon2 import PasswordHasher
    from redis import Redis
    from sqlalchemy import create_engine, text

    from tradelens.cli.seed import seed
    from tradelens.integrations.fakes.synthetic import SyntheticProvider
    from tradelens.modules.accounts.public import create_account
    from tradelens.modules.analysis.output_store import SqlAnalysisStore
    from tradelens.modules.analysis.process import CloseBatch, to_engine
    from tradelens.modules.analysis.public import group_rows, load_scanner_rows, official_rule
    from tradelens.modules.billing.public import create_manual_subscription
    from tradelens.modules.market_data.candles import to_stored
    from tradelens.modules.market_data.public import SqlCandleStore, load_instrument_specs
    from tradelens.worker.publish import scanner_updated
    from tradelens_engine.multi import step_batch

    cfg = Config(str(REPO / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "backend" / "migrations"))
    os.environ["DATABASE_MIGRATION_URL"] = DB_URL
    command.upgrade(cfg, "head")
    engine = create_engine(DB_URL)
    password = secrets.token_urlsafe(18)
    hasher = PasswordHasher()
    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    provider = SyntheticProvider(load_instrument_specs(REPO / "config"), lambda: end)
    made: list[str] = []
    with engine.begin() as conn:
        seed(conn, REPO / "config")
        create_account(conn, "free@e2e.test", "customer", hasher.hash(password))
        pro = create_account(conn, "pro@e2e.test", "customer", hasher.hash(password))
        create_manual_subscription(conn, pro, "pro_monthly")
        rule = official_rule(conn)
        store = SqlCandleStore(conn)
        for code, asset, direction, combined in SETUPS:
            bars = provider.fetch(code, "1h", count=600, end=end - timedelta(hours=1))
            store.add([to_stored(b, code, "1h", "synthetic") for b in bars])
            # Finished 5m candles inside the current hour, for the forming candle (display).
            now5 = datetime.now(UTC).replace(second=0, microsecond=0)
            now5 -= timedelta(minutes=now5.minute % 5)
            if (n5 := (now5 - end) // timedelta(minutes=5)) > 0:
                live5 = SyntheticProvider(load_instrument_specs(REPO / "config"), lambda t=now5: t)
                five = live5.fetch(code, "5m", count=n5, end=now5 - timedelta(minutes=5))
                store.add(
                    [to_stored(b, code, "5m", "synthetic") for b in five if b.open_time >= end]
                )
            rows = store.load(code, "1h", None)
            result = step_batch({}, {"1h": [to_engine(r) for r in rows]}, rule.settings,
                                instrument=code, rule_version=rule.version)  # fmt: skip
            batch = CloseBatch(code, rule.settings_hash, rule.version, result, asset_class=asset)
            SqlAnalysisStore(conn).save_batch(batch)
            p = {"i": code, "h": rule.settings_hash, "d": direction, "r": rows[-300].open_time}
            zone = conn.execute(text(
                "SELECT id, low, high, confirm_time, origin_time FROM zones WHERE instrument = :i"
                " AND timeframe = '1h' AND settings_hash = :h AND direction = :d"
                " AND state IN ('confirmed','touched','mitigated_50','filled')"
                " AND confirm_time >= :r"
                " ORDER BY confirm_time DESC LIMIT 1"), p).mappings().one()  # fmt: skip
            event = conn.execute(text(
                "SELECT id FROM market_events WHERE instrument = :i AND timeframe = '1h'"
                " AND settings_hash = :h AND type IN ('bos','choch') AND direction = :d"
                " ORDER BY confirm_time DESC LIMIT 1"), p).scalar_one()  # fmt: skip
            sid = secrets.token_hex(16)
            far = zone["low"] if direction == "bull" else zone["high"]
            conn.execute(text(
                "INSERT INTO setups (id, instrument, asset_class, timeframe, profile,"
                " settings_hash, rule_version, scoring_version, direction, break_event_id,"
                " break_type, patterns, sessions, spread, q, c, combined, counter_trend, factors,"
                " explanation, ob_zone_id, invalidation, status, status_time, origin_time,"
                " confirm_time) VALUES (:id, :i, :a, '1h', 'intraday', :h, :v, 's1.0', :d, :ev,"
                " 'bos', ARRAY['bos','displacement','ob','sweep'], ARRAY['london'], 0, :q, :q, :q,"
                " false, CAST(:f AS jsonb), :x, :z, :inv, 'confirmed', :t, :o, :t)"),
                {"id": sid, "i": code, "a": asset, "h": rule.settings_hash, "v": rule.version,
                 "d": direction, "ev": event, "q": combined, "f": json.dumps(FACTORS),
                 "z": zone["id"], "inv": far, "t": zone["confirm_time"], "o": zone["origin_time"],
                 "x": "Synthetic E2E setup: break with displacement from a zone."})  # fmt: skip
            made.append(sid)
            conn.execute(text(
                "UPDATE series_status SET status = 'ok', last_candle_time = :t,"
                " last_checked_at = :t WHERE instrument = :i"),
                {"t": rows[-1].open_time, "i": code})  # fmt: skip
        for i in range(LOAD_USERS):
            create_account(conn, f"load{i}@e2e.test", "customer", hasher.hash(password))
        rows = load_scanner_rows(conn, rule.settings_hash, rule.high_quality)
    # Fill the scanner cache exactly as the worker does after a close pass (task 2.3).
    scanner_updated(Redis.from_url(f"redis://127.0.0.1:{REDIS_PORT}/0", decode_responses=True),
                    group_rows(rows), end)  # fmt: skip
    engine.dispose()
    return {"E2E_PASSWORD": password, "E2E_FREE_EMAIL": "free@e2e.test",
            "E2E_PRO_EMAIL": "pro@e2e.test", "E2E_BULL_SETUP": made[0]}  # fmt: skip


def wait_http(url: str, seconds: int = WAIT_S) -> None:
    """Wait until ``url`` answers below 500."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:  # noqa: S310 - local URL
                if r.status < 500:  # noqa: PLR2004
                    return
        except OSError:
            pass
        time.sleep(1)
    raise SystemExit(f"{url} did not come up")


def run_loadcheck(password: str) -> int:
    """``scripts/loadcheck.py`` against the API with the load users (task 2.10)."""
    users = [{"email": f"load{i}@e2e.test", "password": password} for i in range(LOAD_USERS)]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "users.json"
        path.write_text(json.dumps(users), encoding="utf-8")
        cmd = [sys.executable, str(REPO / "scripts" / "loadcheck.py"),
               "--base", f"http://127.0.0.1:{API_PORT}",
               "--origin", f"http://localhost:{WEB_PORT}", "--users", str(path)]  # fmt: skip
        return subprocess.run(cmd, cwd=REPO, check=False).returncode  # noqa: S603


def main() -> int:
    """Stack up, seed, run Playwright, tear down."""
    procs: list[subprocess.Popen[bytes]] = []
    # The load check runs 2 API workers as in deploy/docker-compose.yml. The functional E2E
    # runs 1: on Windows, uvicorn's multi-worker socket sharing intermittently leaves a
    # request unanswered (seen in about 3 of 7 runs; Linux containers are not affected).
    load = "--load" in sys.argv
    start_containers()
    try:
        extra = seed_data()
        # development: sign-up E2E opens the verification link through the dev-only button.
        api_env = {**os.environ, "DATABASE_URL": DB_URL, "APP_ENV": "development",
                   "REDIS_URL": f"redis://127.0.0.1:{REDIS_PORT}/0",
                   "SESSION_SECRET": secrets.token_hex(32), "CSRF_SECRET": secrets.token_hex(32),
                   "APP_URL": f"http://localhost:{WEB_PORT}",
                   # every E2E sign-up comes from one IP; the 5/min limit has its own API test
                   "RATE_LIMIT_ANON_PER_IP_PER_MIN": "60",
                   "CONFIG_DIR": str(REPO / "config")}  # fmt: skip
        procs.append(subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "uvicorn", "tradelens.app.main:create_app", "--factory",
             "--host", "127.0.0.1", "--port", str(API_PORT), "--log-level", "warning",
             "--workers", "2" if load else "1"],
            cwd=REPO, env=api_env))  # fmt: skip
        wait_http(f"http://127.0.0.1:{API_PORT}/healthz")
        if load:
            return run_loadcheck(extra["E2E_PASSWORD"])
        web_env = {**os.environ, "API_INTERNAL_URL": f"http://127.0.0.1:{API_PORT}",
                   "NEXT_TELEMETRY_DISABLED": "1", "APP_ENV": "development"}  # fmt: skip
        subprocess.run([NPM, "run", "build"], cwd=WEB, env=web_env, check=True)  # noqa: S603
        procs.append(subprocess.Popen(  # noqa: S603
            [NPX, "next", "start", "-p", str(WEB_PORT)], cwd=WEB, env=web_env))  # fmt: skip
        wait_http(f"http://localhost:{WEB_PORT}/healthz")
        test_env = {**os.environ, **extra, "E2E_BASE_URL": f"http://localhost:{WEB_PORT}"}
        cmd = [NPX, "playwright", "test", *[a for a in sys.argv[1:] if a != "--load"]]
        return subprocess.run(cmd, cwd=WEB, env=test_env, check=False).returncode  # noqa: S603
    finally:
        for proc in procs:
            if os.name == "nt":  # npx.cmd starts node children: end the whole tree
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],  # noqa: S603, S607
                               capture_output=True, check=False)  # fmt: skip
            else:
                proc.terminate()
        for name in (PG, REDIS):
            docker("rm", "-f", name, check=False)


if __name__ == "__main__":
    sys.exit(main())
