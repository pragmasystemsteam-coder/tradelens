"""Run the integration tests against a throwaway PostgreSQL 16 container (``make test-db``).

Starts ``postgres:16-alpine`` on 127.0.0.1:55432 with ``deploy/postgres-init`` (roles and
extensions), waits until it accepts connections, runs ``pytest -m integration`` with
``TEST_DATABASE_URL`` set, and always removes the container. Cross-platform: no shell syntax,
so it works the same from mingw32-make on Windows and from make on Linux/CI.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parents[1]
NAME = "tradelens-testdb"
PORT = 55432
PASSWORD = "testdb-only"  # noqa: S105 - throwaway local container bound to 127.0.0.1
OWNER = "tradelens_owner"
DB = "tradelens_test"
SQLA_URL = f"postgresql+psycopg://{OWNER}:{PASSWORD}@127.0.0.1:{PORT}/{DB}"
WAIT_SECONDS = 60
POLL_SECONDS = 1.0


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a docker command with Git Bash path conversion disabled."""
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["docker", *args],  # noqa: S607 - docker from PATH, as in the Makefile
        check=check,
        text=True,
        capture_output=True,
        env=env,
    )


def wait_ready() -> None:
    """Wait until the init scripts have run and the server accepts the owner's connections."""
    deadline = time.monotonic() + WAIT_SECONDS
    dsn = f"postgresql://{OWNER}:{PASSWORD}@127.0.0.1:{PORT}/{DB}"
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=2) as conn:
                row = conn.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname = 'tradelens_app'"
                ).fetchone()
                if row:
                    return
        except psycopg.OperationalError:
            pass
        time.sleep(POLL_SECONDS)
    raise SystemExit(f"PostgreSQL test container not ready after {WAIT_SECONDS} s")


def main() -> int:
    """Start the container, run the integration tests, remove the container."""
    docker("rm", "-f", NAME, check=False)
    init_dir = (REPO / "deploy" / "postgres-init").as_posix()
    docker(
        "run", "-d", "--rm", "--name", NAME, "-p", f"127.0.0.1:{PORT}:5432",
        "-e", f"POSTGRES_USER={OWNER}", "-e", f"POSTGRES_PASSWORD={PASSWORD}",
        "-e", f"POSTGRES_DB={DB}", "-e", "APP_DB_USER=tradelens_app",
        "-e", f"APP_DB_PASSWORD={PASSWORD}",
        "-v", f"{init_dir}:/docker-entrypoint-initdb.d:ro", "postgres:16-alpine",
    )  # fmt: skip
    try:
        wait_ready()
        env = {**os.environ, "TEST_DATABASE_URL": SQLA_URL}
        cmd = [sys.executable, "-m", "pytest", "-m", "integration", *sys.argv[1:]]
        return subprocess.run(cmd, cwd=REPO, env=env, check=False).returncode  # noqa: S603
    finally:
        docker("rm", "-f", NAME, check=False)


if __name__ == "__main__":
    sys.exit(main())
