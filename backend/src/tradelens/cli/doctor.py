"""``make doctor``: validate deploy/.env before anything starts (Detailed Design 6.1, 6.8)."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Mapping
from pathlib import Path

from tradelens.core.config import env_bool

PLACEHOLDER = "change-me"
RAZORPAY_KEY_PREFIX = {"test": "rzp_test_", "live": "rzp_live_"}
REQUIRED_KEYS: tuple[str, ...] = (
    "APP_ENV", "SITE_HOST", "APP_HOST", "ADMIN_HOST", "ENABLE_API_DOCS",
    "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "APP_DB_USER", "APP_DB_PASSWORD",
    "DATABASE_URL", "DATABASE_MIGRATION_URL", "REDIS_PASSWORD", "REDIS_URL",
    "SESSION_SECRET", "CSRF_SECRET", "TOTP_ENCRYPTION_KEY",
    "CF_ACCESS_ENABLED", "CF_ACCESS_TEAM_DOMAIN", "CF_ACCESS_AUD",
    "MARKET_DATA_PROVIDER",
    "RAZORPAY_MODE", "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_FROM_ADDRESS",
    "API_INTERNAL_URL", "SITE_URL", "APP_URL", "ADMIN_URL", "TLS_CERT_FILE", "TLS_KEY_FILE",
)  # fmt: skip
# OANDA joins this table when its adapter exists (its keys stay in .env.example).
PROVIDER_KEYS: dict[str, tuple[str, ...]] = {"twelvedata": ("TWELVEDATA_API_KEY",), "fake": ()}
EXIT_OK, EXIT_FAILED = 0, 1


def parse_env(text: str) -> dict[str, str]:
    """Parse a dotenv file: KEY=value lines, # comments, optional export and quotes.

    Args:
        text: File contents.

    Returns:
        Keys mapped to values (the first "=" splits key and value).
    """
    env: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        value = value.strip()
        if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[key.strip()] = value
    return env


def _razorpay_errors(env: Mapping[str, str]) -> list[str]:
    mode = env.get("RAZORPAY_MODE", "")
    if mode not in RAZORPAY_KEY_PREFIX:
        return [f"RAZORPAY_MODE: must be one of {sorted(RAZORPAY_KEY_PREFIX)}"]
    suffix = mode.upper()
    errors = [
        f"{name}: required when RAZORPAY_MODE={mode}"
        for name in (
            f"RAZORPAY_KEY_ID_{suffix}",
            f"RAZORPAY_KEY_SECRET_{suffix}",
            f"RAZORPAY_WEBHOOK_SECRET_{suffix}",
        )
        if not env.get(name, "").strip()
    ]
    key_id = env.get(f"RAZORPAY_KEY_ID_{suffix}", "")
    if key_id and not key_id.startswith(RAZORPAY_KEY_PREFIX[mode]):
        errors.append(
            f"RAZORPAY_KEY_ID_{suffix}: must start with {RAZORPAY_KEY_PREFIX[mode]} in {mode} mode"
        )
    return errors


def _provider_errors(env: Mapping[str, str]) -> list[str]:
    provider = env.get("MARKET_DATA_PROVIDER", "").strip()
    if not provider:
        return []  # reported as a missing required key
    if provider not in PROVIDER_KEYS:
        return [f"MARKET_DATA_PROVIDER: must be one of {sorted(PROVIDER_KEYS)}"]
    errors = [
        f"{key}: required when MARKET_DATA_PROVIDER={provider}"
        for key in PROVIDER_KEYS[provider]
        if not env.get(key, "").strip()
    ]
    if env.get("APP_ENV") == "production":
        if provider == "fake":
            errors.append("MARKET_DATA_PROVIDER: fake data is not allowed in production")
        elif env.get("TWELVEDATA_LIVE_INSTRUMENTS", "").strip() != "all":
            errors.append("TWELVEDATA_LIVE_INSTRUMENTS: must be 'all' in production (no fake data)")
    return errors


def check_env(env: Mapping[str, str]) -> list[str]:
    """Find configuration errors that must stop a deployment.

    Args:
        env: Parsed environment.

    Returns:
        One message per problem; empty when the file is usable.
    """
    errors = [
        f"{key}: required but missing or empty"
        for key in REQUIRED_KEYS
        if not env.get(key, "").strip()
    ]
    errors += [
        f"{key}: still contains the placeholder '{PLACEHOLDER}'"
        for key, value in env.items()
        if PLACEHOLDER in value
    ]
    if env.get("APP_ENV") == "production":
        if not env_bool(env.get("CF_ACCESS_ENABLED")):
            errors.append("CF_ACCESS_ENABLED: must be true in production (admin gate, AD-10)")
        if env_bool(env.get("ENABLE_API_DOCS")):
            errors.append("ENABLE_API_DOCS: must be false in production")
    errors += _razorpay_errors(env)
    errors += _provider_errors(env)
    return errors


def warnings_for(env: Mapping[str, str]) -> list[str]:
    """Find settings that are legal but suspicious in production.

    Args:
        env: Parsed environment.

    Returns:
        One message per warning.
    """
    if env.get("APP_ENV") != "production":
        return []
    found = []
    if env.get("RAZORPAY_MODE") == "test":
        found.append("RAZORPAY_MODE=test in production: no real payments will be taken")
    if env.get("OANDA_ENV") == "practice":
        found.append("OANDA_ENV=practice in production: needs the commercial data licence (CD-08)")
    return found


def docker_available() -> bool:
    """Return True when the docker CLI is on PATH."""
    return shutil.which("docker") is not None


def main(argv: list[str]) -> int:
    """Check ENV_FILE and Docker; print problems.

    Args:
        argv: ``[ENV_FILE]``.

    Returns:
        0 when everything is usable, 1 otherwise.
    """
    path = Path(argv[0]) if argv else Path("deploy/.env")
    if not path.is_file():
        sys.stderr.write(f"doctor: {path} not found (copy deploy/.env.example)\n")
        return EXIT_FAILED
    env = parse_env(path.read_text(encoding="utf-8"))
    errors = check_env(env)
    if not docker_available():
        errors.append("docker: not found on PATH (install Docker Desktop or Docker Engine)")
    for message in warnings_for(env):
        sys.stdout.write(f"WARNING {message}\n")
    for message in errors:
        sys.stdout.write(f"ERROR   {message}\n")
    sys.stdout.write("doctor: OK\n" if not errors else f"doctor: {len(errors)} problem(s)\n")
    return EXIT_OK if not errors else EXIT_FAILED
