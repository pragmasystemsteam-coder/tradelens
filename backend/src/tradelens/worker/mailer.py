"""The mailer thread: sends queued e-mails from ``email_outbox`` (DD 2.6, DD-7; task 3.1).

Every few seconds it calls ``notifications.deliver_due``; when a batch was full it loops at once.
A database outage is logged and retried on the next tick, never fatal.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from tradelens.modules.notifications.public import EmailTransport, deliver_due

logger = logging.getLogger(__name__)

POLL_SECONDS = 5.0
BATCH = 20


def run_mailer(
    engine: Engine,
    transport: EmailTransport,
    clock: Callable[[], datetime],
    stop: threading.Event,
    *,
    max_attempts: int,
    poll_seconds: float = POLL_SECONDS,
) -> None:
    """Deliver due e-mails until ``stop`` is set."""
    logger.info("mailer started", extra={"transport": type(transport).__name__})
    while not stop.is_set():
        try:
            claimed = deliver_due(engine.begin, transport, clock(), max_attempts=max_attempts,
                                  limit=BATCH)  # fmt: skip
        except (SQLAlchemyError, OSError):
            logger.exception("mailer pass failed; retrying")
            claimed = 0
        if claimed < BATCH:
            stop.wait(poll_seconds)
