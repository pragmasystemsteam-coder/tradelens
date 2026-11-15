"""Worker entry point: ``python -m tradelens.worker.main``.

Runs the heartbeat (main thread, every 5 s) and, when ``DATABASE_URL`` is set, three
background threads (DD 8.1 task 1.9):

* close: ingest, engine processing and live messages at every 5-minute boundary + 2 s;
* prices: price ticks into ``price:{instrument}`` / ``prices:{instrument}`` (CR-004: from the
  newest stored 5m candle, as the Twelve Data FREE plan has no price stream);
* stale watch: marks a price stale after ``PRICE_STALE_AFTER_SECONDS`` without a tick.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import FrameType

from redis.exceptions import RedisError
from sqlalchemy import Engine

from tradelens.core.config import AppConfig, env_int
from tradelens.core.db import get_engine
from tradelens.core.logging import configure_logging
from tradelens.core.redis import create_redis
from tradelens.integrations.providers import build_candle_provider
from tradelens.modules.analysis.public import CloseProcessor, SqlAnalysisStore, load_active_rule
from tradelens.modules.market_data.public import (
    IngestService,
    SqlCandleStore,
    load_instrument_specs,
)
from tradelens.worker.heartbeat import HeartbeatStore, beat
from tradelens.worker.jobs.close import CloseJob, run_close_loop
from tradelens.worker.jobs.ingest import run_ingest_once
from tradelens.worker.prices import (
    PriceBook,
    candle_close_ticks,
    run_price_stream,
    run_stale_watch,
)
from tradelens.worker.publish import Publisher

DEFAULT_CONFIG_DIR = "config"
DEFAULT_HISTORY = 2500
DEFAULT_GRACE_SECONDS = 60
DEFAULT_OFFSET_SECONDS = 2
DEFAULT_THROTTLE_MS = 500
DEFAULT_STALE_SECONDS = 10
CANDLE_PRICE_STALE_SECONDS = 420  # one 5m candle + 60 s grace, rounded up
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


@contextmanager
def sql_transaction(engine: Engine) -> Iterator[tuple[SqlCandleStore, SqlAnalysisStore]]:
    """One transaction with the candle store and the analysis store on the same connection."""
    with engine.begin() as conn:
        yield SqlCandleStore(conn), SqlAnalysisStore(conn)


def build_close_job(env: Mapping[str, str], engine: Engine, publisher: Publisher) -> CloseJob:
    """Wire ingest, the engine for the active rule version and the publisher.

    Raises:
        ValueError: On invalid provider settings or no active rule version.
    """
    service = build_ingest_service(env)
    with engine.connect() as conn:
        rule = load_active_rule(conn)
    return CloseJob(
        ingest=lambda: run_ingest_once(engine, service, utc_now),
        transaction=lambda: sql_transaction(engine),
        processor=CloseProcessor(rule.settings, rule.version),
        publisher=publisher,
        clock=utc_now,
    )


def _thread(name: str, target: Callable[..., None], *args: object) -> threading.Thread:
    thread = threading.Thread(target=target, args=args, name=name, daemon=True)
    thread.start()
    return thread


def start_pipeline(
    env: Mapping[str, str], database_url: str, publisher: Publisher, stop: threading.Event
) -> list[threading.Thread]:
    """Start the close, price and stale-watch threads, or log why they are not started.

    Raises:
        ValueError: On invalid settings (the worker must not run half-configured).
    """
    if not database_url:
        logger.warning("DATABASE_URL not set: ingestion and processing are off")
        return []
    engine = get_engine(database_url)
    job = build_close_job(env, engine, publisher)
    specs = load_instrument_specs(Path(env.get("CONFIG_DIR", DEFAULT_CONFIG_DIR)))
    book = PriceBook(
        publisher,
        time.time,
        throttle_ms=env_int(env, "SSE_PRICE_THROTTLE_MS", DEFAULT_THROTTLE_MS),
        # CR-004: prices come from 5m closes, so a price is stale only when a close is missing.
        stale_after_s=max(
            env_int(env, "PRICE_STALE_AFTER_SECONDS", DEFAULT_STALE_SECONDS),
            CANDLE_PRICE_STALE_SECONDS,
        ),
    )
    offset = env_int(env, "SCHEDULER_OFFSET_SECONDS", DEFAULT_OFFSET_SECONDS)
    threads = [
        _thread("close", run_close_loop, job, utc_now, stop, offset),
        _thread(
            "prices",
            run_price_stream,
            candle_close_ticks(engine, specs, stop, on_poll=book.mark_alive),
            book,
            stop,
        ),
        _thread("stale-watch", run_stale_watch, book, stop),
    ]
    logger.info("worker pipeline started", extra={"provider": env.get("MARKET_DATA_PROVIDER")})
    return threads


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
    redis = create_redis(config.redis_url)
    threads = start_pipeline(os.environ, config.database_url, redis, stop)
    run_heartbeat(redis, config.heartbeat_interval_seconds, config.heartbeat_ttl_seconds, stop)
    for thread in threads:
        thread.join(timeout=SHUTDOWN_JOIN_SECONDS)  # let a running pass finish its statement
    return 0


if __name__ == "__main__":
    sys.exit(main())
