"""Worker entry point: ``python -m tradelens.worker.main``.

Day 1 runs only the heartbeat; the scheduler, ingestion and candle-close processing arrive in
task 1.9.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from collections.abc import Callable
from types import FrameType

from redis.exceptions import RedisError

from tradelens.core.config import AppConfig
from tradelens.core.logging import configure_logging
from tradelens.core.redis import create_redis
from tradelens.worker.heartbeat import HeartbeatStore, beat

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
    run_heartbeat(
        create_redis(config.redis_url),
        config.heartbeat_interval_seconds,
        config.heartbeat_ttl_seconds,
        stop,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
