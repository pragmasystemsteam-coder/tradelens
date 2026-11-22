"""SQL for ``email_outbox`` (DD 2.6)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

INSERT = text(
    "INSERT INTO email_outbox (kind, user_id, to_email, subject, payload, dedupe_key)"
    " VALUES (:kind, :user_id, :to, :subject, CAST(:payload AS jsonb), :dedupe_key)"
    " ON CONFLICT (dedupe_key) DO NOTHING RETURNING id"
)
SELECT_BY_KEY = text("SELECT id FROM email_outbox WHERE dedupe_key = :dedupe_key")
# Due rows, plus rows left in 'sending' by a worker that died; SKIP LOCKED lets two workers share.
CLAIM_DUE = text(
    "UPDATE email_outbox o SET status = 'sending', locked_at = :now, attempts = o.attempts + 1,"
    " max_attempts = :max_attempts"
    " WHERE o.id IN (SELECT id FROM email_outbox"
    "   WHERE (status IN ('queued', 'retry') AND next_attempt_at <= :now)"
    "      OR (status = 'sending' AND locked_at <= :stale)"
    "   ORDER BY next_attempt_at, id LIMIT :limit FOR UPDATE SKIP LOCKED)"
    " RETURNING o.id, o.kind, o.to_email, o.subject, o.payload, o.attempts"
)
MARK_SENT = text(
    "UPDATE email_outbox SET status = 'sent', sent_at = :now, locked_at = NULL,"
    " last_error = NULL, payload = payload - CAST(:scrub AS text[]) WHERE id = :id"
)
MARK_RETRY = text(
    "UPDATE email_outbox SET status = 'retry', next_attempt_at = :at, locked_at = NULL,"
    " last_error = :error WHERE id = :id"
)
MARK_FAILED = text(
    "UPDATE email_outbox SET status = 'failed', failed_at = :now, locked_at = NULL,"
    " last_error = :error WHERE id = :id"
)


def insert(
    conn: Connection, kind: str, to: str, subject: str, payload: dict[str, Any],
    dedupe_key: str | None, user_id: str | None,
) -> int:  # fmt: skip
    """Insert a queued row (or find the row with the same ``dedupe_key``) and return its ID."""
    params = {"kind": kind, "user_id": user_id, "to": to, "subject": subject,
              "payload": json.dumps(payload), "dedupe_key": dedupe_key}  # fmt: skip
    new_id = conn.execute(INSERT, params).scalar()
    if new_id is None:
        new_id = conn.execute(SELECT_BY_KEY, {"dedupe_key": dedupe_key}).scalar_one()
    return int(new_id)


def claim_due(
    conn: Connection, now: datetime, stale: datetime, limit: int, max_attempts: int
) -> list[dict[str, Any]]:
    """Mark up to ``limit`` due rows ``sending`` and return them."""
    params = {"now": now, "stale": stale, "limit": limit, "max_attempts": max_attempts}
    return [dict(r) for r in conn.execute(CLAIM_DUE, params).mappings()]


def mark_sent(conn: Connection, row_id: int, now: datetime, scrub: Sequence[str]) -> None:
    """Sent: drop the payload keys that may carry tokens."""
    conn.execute(MARK_SENT, {"id": row_id, "now": now, "scrub": list(scrub)})


def mark_retry(conn: Connection, row_id: int, at: datetime, error: str) -> None:
    """Failed attempt with attempts left: try again at ``at``."""
    conn.execute(MARK_RETRY, {"id": row_id, "at": at, "error": error})


def mark_failed(conn: Connection, row_id: int, now: datetime, error: str) -> None:
    """No attempts left."""
    conn.execute(MARK_FAILED, {"id": row_id, "now": now, "error": error})
