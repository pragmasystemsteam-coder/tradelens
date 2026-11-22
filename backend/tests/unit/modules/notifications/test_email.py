"""E-mail templates, retry schedule and transports (DD 2.6, 6.1; task 3.1)."""

import logging
from typing import ClassVar

import pytest

from tradelens.integrations.email import ConsoleTransport, SmtpTransport, build_email_transport
from tradelens.modules.notifications.public import (
    KINDS,
    TEMPLATE_FIELDS,
    OutgoingEmail,
    compose,
    retry_delay,
)

LINK = "https://app.test/verify-email?token=tok123"


def test_every_kind_has_template():
    assert set(TEMPLATE_FIELDS) == set(KINDS)
    for kind in KINDS:
        payload = {field: f"<{field}>" for field in TEMPLATE_FIELDS[kind]}
        subject, body = compose(kind, payload)
        assert subject and "\n" not in subject, kind
        for field in TEMPLATE_FIELDS[kind]:
            assert f"<{field}>" in subject + body, (kind, field)
        assert "$" not in body, kind  # every placeholder filled


def test_compose_refuses_missing_field():
    with pytest.raises(KeyError):
        compose("verify", {})


def test_alert_mail_carries_score_notice():
    _, body = compose("alert", dict.fromkeys(TEMPLATE_FIELDS["alert"], "x"))
    assert "They are not a probability of profit." in body


def test_retry_delay_schedule():
    assert [retry_delay(n) for n in (1, 2, 3, 4, 5, 9)] == [60, 300, 1800, 7200, 7200, 7200]


def message():
    return OutgoingEmail(to="trader@example.com", subject="Verify your email",
                         body=f"Open {LINK}\n", kind="verify")  # fmt: skip


def test_console_transport_logs_mail_never_secrets(caplog):
    env = {"EMAIL_TRANSPORT": "console", "APP_ENV": "development", "SMTP_PASSWORD": "pw-secret-1"}
    transport = build_email_transport(env)
    assert isinstance(transport, ConsoleTransport)
    with caplog.at_level(logging.INFO, logger="tradelens.email"):
        transport.send(message())
    logged = caplog.text
    assert LINK in logged and "trader@example.com" in logged
    assert "pw-secret-1" not in logged


@pytest.mark.parametrize("env", ["production", "staging"])
def test_console_transport_refused_outside_development(env):
    with pytest.raises(ValueError, match="EMAIL_TRANSPORT=console"):
        build_email_transport({"EMAIL_TRANSPORT": "console", "APP_ENV": env})


def test_unknown_transport_refused():
    with pytest.raises(ValueError, match="EMAIL_TRANSPORT"):
        build_email_transport({"EMAIL_TRANSPORT": "carrier-pigeon", "APP_ENV": "development"})


def test_smtp_requires_host_and_from():
    with pytest.raises(ValueError, match="SMTP_HOST"):
        build_email_transport({"EMAIL_TRANSPORT": "smtp", "APP_ENV": "production"})


class FakeSMTP:
    instances: ClassVar[list] = []

    def __init__(self, host, port, timeout):
        self.calls = [("connect", host, port, timeout)]
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.calls.append(("starttls",))

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, msg):
        self.calls.append(("send", msg["To"], msg["From"], msg["Subject"], msg["Reply-To"],
                           msg.get_content()))  # fmt: skip


def test_smtp_transport_starttls_login_send(monkeypatch):
    monkeypatch.setattr("tradelens.integrations.email.smtplib.SMTP", FakeSMTP)
    env = {"EMAIL_TRANSPORT": "smtp", "APP_ENV": "production", "SMTP_HOST": "smtp-relay.brevo.com",
           "SMTP_PORT": "587", "SMTP_STARTTLS": "true", "SMTP_USER": "u1", "SMTP_PASSWORD": "p1",
           "EMAIL_FROM_ADDRESS": "no-reply@tradelens.test", "EMAIL_FROM_NAME": "TradeLens",
           "EMAIL_REPLY_TO": "support@tradelens.test"}  # fmt: skip
    transport = build_email_transport(env)
    assert isinstance(transport, SmtpTransport)
    assert "p1" not in repr(transport)
    transport.send(message())
    calls = FakeSMTP.instances[-1].calls
    assert calls[0][:3] == ("connect", "smtp-relay.brevo.com", 587)
    assert calls[1] == ("starttls",) and calls[2] == ("login", "u1", "p1")
    _, to, sender, subject, reply_to, content = calls[3]
    assert (to, subject, reply_to) == ("trader@example.com", "Verify your email",
                                       "support@tradelens.test")  # fmt: skip
    assert sender == "TradeLens <no-reply@tradelens.test>" and LINK in content
