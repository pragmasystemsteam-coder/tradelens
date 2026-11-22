"""E-mail outbox against PostgreSQL: retries, dedupe and reclaim (DD 2.6 email_outbox; task 3.1).

Lives beside the API tests to share their migrated database fixture.
"""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from tradelens.modules.notifications.public import deliver_due, enqueue_email

pytestmark = pytest.mark.integration


@pytest.fixture
def t0():
    """New rows are due from the database's now(), so each test's clock starts just after it."""
    return datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=1)


class Transport:
    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []

    def send(self, message):
        if self.fail:
            raise OSError("smtp down")
        self.sent.append(message)


def tx(db):
    @contextmanager
    def begin():
        with db.begin() as conn:
            yield conn

    return begin


def queue(db, to, dedupe_key=None, kind="verify"):
    with db.begin() as conn:
        return enqueue_email(conn, kind, to, "Verify your email",
                             {"link": "https://app.test/verify-email?token=abc", "ttl_hours": 24},
                             dedupe_key=dedupe_key)  # fmt: skip


def row(db, oid):
    with db.begin() as conn:
        return dict(conn.execute(text("SELECT * FROM email_outbox WHERE id = :i"),
                                 {"i": oid}).mappings().one())  # fmt: skip


@pytest.fixture(autouse=True)
def quiet_outbox(db):
    """Other tests leave queued mail behind: park it so each test sees only its own rows."""
    with db.begin() as conn:
        conn.execute(text("UPDATE email_outbox SET status = 'sent', sent_at = now()"
                          " WHERE status IN ('queued','retry','sending')"))  # fmt: skip


def test_outbox_retry_backoff_then_failed(db, t0):
    oid = queue(db, "retry@example.com")
    down = Transport(fail=True)
    now = t0
    for delay in (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30),
                  timedelta(hours=2)):  # fmt: skip
        assert deliver_due(tx(db), down, now, max_attempts=5) == 1
        r = row(db, oid)
        assert r["status"] == "retry" and r["next_attempt_at"] == now + delay
        assert "smtp down" in r["last_error"]
        assert deliver_due(tx(db), down, now + delay - timedelta(seconds=1), max_attempts=5) == 0
        now += delay
    assert deliver_due(tx(db), down, now, max_attempts=5) == 1
    r = row(db, oid)
    assert (r["status"], r["attempts"], r["failed_at"]) == ("failed", 5, now)
    assert deliver_due(tx(db), down, now + timedelta(days=1), max_attempts=5) == 0


def test_outbox_max_attempts_from_config(db, t0):
    oid = queue(db, "two@example.com")
    down = Transport(fail=True)
    deliver_due(tx(db), down, t0, max_attempts=2)
    deliver_due(tx(db), down, t0 + timedelta(minutes=1), max_attempts=2)
    r = row(db, oid)
    assert (r["status"], r["attempts"], r["max_attempts"]) == ("failed", 2, 2)


def test_outbox_dedupe_key(db, t0):
    a = queue(db, "dupe@example.com", dedupe_key="alert:r1:e1")
    b = queue(db, "dupe@example.com", dedupe_key="alert:r1:e1")
    c = queue(db, "dupe@example.com")
    d = queue(db, "dupe@example.com")
    assert a == b and len({a, c, d}) == 3
    with db.begin() as conn:
        n = conn.execute(text("SELECT count(*) FROM email_outbox WHERE dedupe_key = 'alert:r1:e1'"))
        assert n.scalar() == 1


def test_sent_mail_rendered_and_token_scrubbed(db, t0):
    oid = queue(db, "ok@example.com")
    up = Transport()
    assert deliver_due(tx(db), up, t0, max_attempts=5) == 1
    msg = up.sent[0]
    assert msg.to == "ok@example.com" and msg.subject == "Verify your email"
    assert "https://app.test/verify-email?token=abc" in msg.body
    r = row(db, oid)
    assert (r["status"], r["sent_at"], r["attempts"]) == ("sent", t0, 1)
    assert "link" not in r["payload"]  # tokens scrubbed once sent


def test_sending_reclaimed_after_5_min(db, t0):
    oid = queue(db, "crash@example.com")
    with db.begin() as conn:  # a worker claimed it and died before marking it
        conn.execute(text("UPDATE email_outbox SET status = 'sending', locked_at = :t,"
                          " attempts = 1 WHERE id = :i"), {"t": t0, "i": oid})  # fmt: skip
    up = Transport()
    assert deliver_due(tx(db), up, t0 + timedelta(minutes=4, seconds=59), max_attempts=5) == 0
    assert row(db, oid)["status"] == "sending"
    assert deliver_due(tx(db), up, t0 + timedelta(minutes=5, seconds=1), max_attempts=5) == 1
    r = row(db, oid)
    assert (r["status"], r["attempts"]) == ("sent", 2) and len(up.sent) == 1
