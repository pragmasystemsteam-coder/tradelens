"""Worker entry point: ``python -m tradelens.worker.main``.

Runs the heartbeat (main thread) and, when ``DATABASE_URL`` is set, the candle ingest job in a
background thread every 5 minutes (CR-004). Candle-close processing by the engine follows in
task 1.9.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import FrameType

from redis.exceptions import RedisError

from tradelens.core.config import AppConfig, env_int
from tradelens.core.db import get_engine
from tradelens.core.logging import configure_logging
from tradelens.core.redis import create_redis
from tradelens.integrations.providers import build_candle_provider
from tradelens.modules.market_data.public import IngestService, load_instrument_specs
from tradelens.worker.heartbeat import HeartbeatStore, beat
from tradelens.worker.jobs.ingest import run_ingest_loop

DEFAULT_CONFIG_DIR = "config"
DEFAULT_HISTORY = 2500
DEFAULT_GRACE_SECONDS = 60
DEFAULT_OFFSET_SECONDS = 2
SHUTDOWN_JOIN_SECONDS = 20

logger = logging.getLogger(__name__)


def run_heartbeat(
    redis: HeartbeatStore,
    interval: float,
    ttl: int,
    stop: threading.Event,
    clock: Callable[[], float] = time.time,
) -> None:
    """Write the heartbeat every ``interval`` seconds until ``stop`` is set.

    A Redis outage is logged and retried; it never stops the worker.

    Args:
        redis: Redis client.
        interval: Seconds between beats.
        ttl: Heartbeat TTL in seconds.
        stop: Event that ends the loop.
        clock: Time source (injected for tests).
    """
    while not stop.is_set():
        try:
            beat(redis, clock(), ttl)
        except (RedisError, OSError) as exc:
            logger.warning("heartbeat write failed (%s)", type(exc).__name__)
        stop.wait(interval)


def utc_now() -> datetime:
    """The worker clock (UTC)."""
    return datetime.now(UTC)


def build_ingest_service(
    env: Mapping[str, str], clock: Callable[[], datetime] = utc_now
) -> IngestService:
    """Build the ingest service from the environment (provider chosen by MARKET_DATA_PROVIDER).

    Raises:
        ValueError: On invalid provider settings.
    """
    specs = load_instrument_specs(Path(env.get("CONFIG_DIR", DEFAULT_CONFIG_DIR)))
    provider = build_candle_provider(env, specs, clock)
    return IngestService(
        provider,
        specs,
        history_count=env_int(env, "BACKFILL_MIN_CANDLES", DEFAULT_HISTORY),
        grace=timedelta(seconds=env_int(env, "CANDLE_RETRY_MAX_SECONDS", DEFAULT_GRACE_SECONDS)),
    )


def start_ingest(
    env: Mapping[str, str], database_url: str, stop: threading.Event
) -> threading.Thread | None:
    """Start the ingest loop in a thread, or log why it is not started.

    Raises:
        ValueError: On invalid provider settings (the worker must not run half-configured).
    """
    if not database_url:
        logger.warning("DATABASE_URL not set: candle ingestion is off")
        return None
    service = build_ingest_service(env)
    offset = env_int(env, "SCHEDULER_OFFSET_SECONDS", DEFAULT_OFFSET_SECONDS)
    thread = threading.Thread(
        target=run_ingest_loop,
        args=(get_engine(database_url), service, utc_now, stop, offset),
        name="ingest",
        daemon=True,
    )
    thread.start()
    logger.info("candle ingestion started", extra={"provider": env.get("MARKET_DATA_PROVIDER")})
    return thread


def main() -> int:
    """Start the worker and run until SIGTERM or SIGINT.

    Returns:
        The process exit code.
    """
    configure_logging()
    config = AppConfig.from_env()
    stop = threading.Event()

    def request_stop(signum: int, _frame: FrameType | None) -> None:
        logger.info("worker stopping (signal %s)", signum)
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    logger.info("worker started")
    ingest = start_ingest(os.environ, config.database_url, stop)
    run_heartbeat(
        create_redis(config.redis_url),
        config.heartbeat_interval_seconds,
        config.heartbeat_ttl_seconds,
        stop,
    )
    if ingest is not None:
        ingest.join(timeout=SHUTDOWN_JOIN_SECONDS)  # let a running pass finish its statement
    return 0


if __name__ == "__main__":
    sys.exit(main())
