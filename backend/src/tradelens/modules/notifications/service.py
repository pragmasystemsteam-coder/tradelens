"""E-mail outbox: queue, render and deliver with retries (DD 2.6 email_outbox, DD-7; task 3.1).

Every customer e-mail is a row in ``email_outbox`` written in the same transaction as the change
that caused it, so a rolled-back sign-up never sends mail. The worker's mailer thread claims due
rows, renders the template for the row's ``kind`` and hands the message to the configured
transport (``integrations.email``). A failed send retries after 1 min, 5 min, 30 min, then every
2 h until ``EMAIL_OUTBOX_MAX_ATTEMPTS`` (default 5) is spent; a row stuck in ``sending`` for
5 minutes (a worker that died mid-send) is claimed again. Links carrying tokens are removed from
the payload once the mail is sent.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from importlib import resources
from string import Template
from typing import Any, Protocol

from sqlalchemy import Connection

from tradelens.modules.notifications import repository

log = logging.getLogger("tradelens.notifications")

KINDS = (
    "verify", "reset", "already_registered", "alert", "refund_requested", "refund_approved",
    "refund_rejected", "refund_completed", "payment_failed", "subscription_ended", "trial_ending",
)  # fmt: skip
# Placeholders each template needs (``$name`` in templates/<kind>.txt).
TEMPLATE_FIELDS: dict[str, tuple[str, ...]] = {
    "verify": ("link", "ttl_hours"),
    "reset": ("link", "ttl_minutes"),
    "already_registered": ("login_link", "reset_link"),
    "alert": ("summary", "link"),
    "refund_requested": ("amount", "reference"),
    "refund_approved": ("amount", "reference"),
    "refund_rejected": ("amount", "reference", "reason"),
    "refund_completed": ("amount", "reference"),
    "payment_failed": ("grace_until", "link"),
    "subscription_ended": ("plan", "link"),
    "trial_ending": ("trial_ends", "link"),
}
SECRET_FIELDS = ("link", "reset_link")  # may carry a one-time token: dropped once sent
BACKOFF_SECONDS = (60, 300, 1800, 7200)  # after attempt 1, 2, 3, then every 2 h
RECLAIM_AFTER = timedelta(minutes=5)
DEFAULT_MAX_ATTEMPTS = 5
BATCH = 20
ERROR_CHARS = 500


@dataclass(frozen=True, slots=True)
class OutgoingEmail:
    """A rendered e-mail ready for a transport."""

    to: str
    subject: str
    body: str
    kind: str


class EmailTransport(Protocol):
    """Sends one e-mail or raises (any exception counts as a failed attempt)."""

    def send(self, message: OutgoingEmail) -> None:
        """Deliver ``message``."""
        ...


@lru_cache(maxsize=len(KINDS))
def _template(kind: str) -> tuple[str, Template]:
    if kind not in KINDS:
        raise ValueError(f"unknown e-mail kind {kind!r}")
    raw = resources.files("tradelens.modules.notifications") / "templates" / f"{kind}.txt"
    text = raw.read_text(encoding="utf-8").replace("\r\n", "\n")  # git may check out CRLF
    head, _, body = text.partition("\n\n")
    if not head.startswith("Subject: "):
        raise ValueError(f"template {kind}.txt must start with 'Subject: '")
    return head.removeprefix("Subject: ").strip(), Template(body)


def compose(kind: str, payload: Mapping[str, Any]) -> tuple[str, str]:
    """The subject and plain-text body of an e-mail.

    Raises:
        KeyError: When ``payload`` lacks a placeholder of the template.
        ValueError: On an unknown kind.
    """
    subject, body = _template(kind)
    values = {k: str(v) for k, v in payload.items()}
    return Template(subject).substitute(values), body.substitute(values)


def retry_delay(attempts: int) -> int:
    """Seconds before the next try after ``attempts`` failed attempts."""
    return BACKOFF_SECONDS[min(max(attempts, 1), len(BACKOFF_SECONDS)) - 1]


def enqueue_email(
    conn: Connection, kind: str, to: str, subject: str, payload: Mapping[str, Any],
    dedupe_key: str | None = None, *, user_id: str | None = None,
) -> int:  # fmt: skip
    """Queue an e-mail in the caller's transaction (DD 8.3 task 3.1).

    A second call with the same ``dedupe_key`` queues nothing and returns the first row's ID.

    Returns:
        The outbox row ID.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown e-mail kind {kind!r}")
    return repository.insert(conn, kind, to, subject, dict(payload), dedupe_key, user_id)


def queue_email(
    conn: Connection, kind: str, to: str, payload: Mapping[str, Any], *,
    user_id: str | None = None, dedupe_key: str | None = None,
) -> int:  # fmt: skip
    """Queue an e-mail whose subject comes from its template (checks every field is present)."""
    subject, _ = compose(kind, payload)
    return enqueue_email(conn, kind, to, subject, payload, dedupe_key, user_id=user_id)


def deliver_due(
    begin: Callable[[], AbstractContextManager[Connection]],
    transport: EmailTransport,
    now: datetime,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    limit: int = BATCH,
) -> int:
    """Send the due e-mails once; each outcome is saved in its own short transaction.

    Args:
        begin: Opens a transaction (``engine.begin``).
        transport: Where messages go (SMTP or the development console).
        now: Current UTC time.
        max_attempts: Attempts before a row is ``failed`` (``EMAIL_OUTBOX_MAX_ATTEMPTS``).
        limit: Rows claimed per call.

    Returns:
        How many rows were claimed (sent, retried or failed).
    """
    with begin() as conn:
        rows = repository.claim_due(conn, now, now - RECLAIM_AFTER, limit, max_attempts)
    for row in rows:
        try:
            _, body = compose(row["kind"], row["payload"])
            transport.send(OutgoingEmail(row["to_email"], row["subject"], body, row["kind"]))
        except Exception as exc:  # noqa: BLE001 - any failure is a retry, never a crash
            error = f"{type(exc).__name__}: {exc}"[:ERROR_CHARS]
            with begin() as conn:
                if row["attempts"] >= max_attempts:
                    repository.mark_failed(conn, row["id"], now, error)
                else:
                    retry_at = now + timedelta(seconds=retry_delay(row["attempts"]))
                    repository.mark_retry(conn, row["id"], retry_at, error)
            details = {"outbox_id": row["id"], "kind": row["kind"], "attempt": row["attempts"],
                       "error": error}  # fmt: skip
            log.warning("email not sent", extra=details)
            continue
        with begin() as conn:
            repository.mark_sent(conn, row["id"], now, SECRET_FIELDS)
        log.info("email sent", extra={"outbox_id": row["id"], "kind": row["kind"]})
    return len(rows)
