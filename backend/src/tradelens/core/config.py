"""Application configuration read from environment variables (Detailed Design 6.1)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
DEFAULT_APP_ENV = "development"
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 5
DEFAULT_HEARTBEAT_TTL_SECONDS = 15


def env_bool(value: str | None) -> bool:
    """Interpret an environment value as a boolean.

    Args:
        value: Raw value such as "true", "1", "no" or None.

    Returns:
        True only for 1, true, yes or on (any case); False otherwise.
    """
    return (value or "").strip().lower() in TRUE_VALUES


def env_int(source: Mapping[str, str], key: str, default: int) -> int:
    """Read an integer environment variable.

    Args:
        source: Environment mapping.
        key: Variable name.
        default: Value when the variable is unset or empty.

    Returns:
        The integer value.

    Raises:
        ValueError: If the value is not an integer (the message names the variable).
    """
    raw = source.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Settings shared by the API and the worker.

    Attributes:
        app_env: development, staging or production.
        database_url: SQLAlchemy URL of the application role ("" when unset).
        redis_url: Redis URL ("" when unset).
        enable_api_docs: Serve /docs and /openapi.json (must be false in production).
        heartbeat_interval_seconds: How often the worker writes its heartbeat.
        heartbeat_ttl_seconds: Age after which the heartbeat counts as stale.
    """

    app_env: str
    database_url: str
    redis_url: str
    enable_api_docs: bool
    heartbeat_interval_seconds: int
    heartbeat_ttl_seconds: int

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AppConfig:
        """Build the configuration from environment variables.

        Args:
            env: Mapping to read instead of os.environ (used by tests).

        Returns:
            The parsed configuration.

        Raises:
            ValueError: If a numeric variable is not an integer, or the heartbeat TTL
                is not longer than its interval.
        """
        source: Mapping[str, str] = os.environ if env is None else env
        interval = env_int(source, "HEARTBEAT_INTERVAL_SECONDS", DEFAULT_HEARTBEAT_INTERVAL_SECONDS)
        ttl = env_int(source, "HEARTBEAT_TTL_SECONDS", DEFAULT_HEARTBEAT_TTL_SECONDS)
        if ttl <= interval:
            raise ValueError(
                "HEARTBEAT_TTL_SECONDS must be greater than HEARTBEAT_INTERVAL_SECONDS,"
                " or the worker flaps unhealthy"
            )
        return cls(
            app_env=source.get("APP_ENV", DEFAULT_APP_ENV),
            database_url=source.get("DATABASE_URL", ""),
            redis_url=source.get("REDIS_URL", ""),
            enable_api_docs=env_bool(source.get("ENABLE_API_DOCS")),
            heartbeat_interval_seconds=interval,
            heartbeat_ttl_seconds=ttl,
        )
