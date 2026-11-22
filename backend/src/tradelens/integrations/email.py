"""E-mail transports for the outbox (DD 6.1 Email keys; task 3.1). Standard library only.

``EMAIL_TRANSPORT=smtp`` sends through an SMTP relay (Brevo: smtp-relay.brevo.com:587 with
STARTTLS). ``EMAIL_TRANSPORT=console`` only logs each mail, so local stacks and demos work
without a mailbox; it is refused unless ``APP_ENV`` is development or test, so production can
never silently drop mail. Neither transport logs the SMTP password.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from collections.abc import Mapping
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr

from tradelens.core.config import env_bool, env_int
from tradelens.modules.notifications.public import EmailTransport, OutgoingEmail

log = logging.getLogger("tradelens.email")

CONSOLE_ENVS = frozenset({"development", "test"})
SMTP_TIMEOUT_SECONDS = 20


class ConsoleTransport:
    """Logs the mail instead of sending it (development and demos only)."""

    def send(self, message: OutgoingEmail) -> None:
        """Write the whole message to the log."""
        log.info("email (console transport, not sent)\nTo: %s\nSubject: %s\n\n%s",
                 message.to, message.subject, message.body)  # fmt: skip


@dataclass(frozen=True, slots=True)
class SmtpTransport:
    """Sends through an SMTP relay, upgrading the connection with STARTTLS."""

    host: str
    port: int
    from_address: str
    from_name: str = "TradeLens"
    reply_to: str = ""
    user: str = ""
    password: str = field(default="", repr=False)
    starttls: bool = True
    timeout: int = SMTP_TIMEOUT_SECONDS

    def send(self, message: OutgoingEmail) -> None:
        """Send one plain-text message; raises on any SMTP or network error."""
        msg = EmailMessage()
        msg["From"] = formataddr((self.from_name, self.from_address))
        msg["To"] = message.to
        msg["Subject"] = message.subject
        if self.reply_to:
            msg["Reply-To"] = self.reply_to
        msg.set_content(message.body)
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
            if self.starttls:
                smtp.starttls(context=ssl.create_default_context())
            if self.user:
                smtp.login(self.user, self.password)
            smtp.send_message(msg)


def build_email_transport(env: Mapping[str, str]) -> EmailTransport:
    """The transport named by ``EMAIL_TRANSPORT`` (default: console in development, else smtp).

    Raises:
        ValueError: On an unknown transport, console outside development and test, or smtp
            without ``SMTP_HOST`` and ``EMAIL_FROM_ADDRESS``.
    """
    app_env = env.get("APP_ENV", "development")
    kind = env.get("EMAIL_TRANSPORT") or ("console" if app_env in CONSOLE_ENVS else "smtp")
    kind = kind.strip().lower()
    if kind == "console":
        if app_env not in CONSOLE_ENVS:
            raise ValueError(
                f"EMAIL_TRANSPORT=console is only allowed with APP_ENV=development (got {app_env})"
            )
        return ConsoleTransport()
    if kind != "smtp":
        raise ValueError(f"EMAIL_TRANSPORT must be smtp or console, got {kind!r}")
    host, sender = env.get("SMTP_HOST", ""), env.get("EMAIL_FROM_ADDRESS", "")
    if not host or not sender:
        raise ValueError("SMTP_HOST and EMAIL_FROM_ADDRESS are required for EMAIL_TRANSPORT=smtp")
    return SmtpTransport(
        host=host,
        port=env_int(env, "SMTP_PORT", 587),
        from_address=sender,
        from_name=env.get("EMAIL_FROM_NAME", "TradeLens"),
        reply_to=env.get("EMAIL_REPLY_TO", ""),
        user=env.get("SMTP_USER", ""),
        password=env.get("SMTP_PASSWORD", ""),
        starttls=env_bool(env.get("SMTP_STARTTLS", "true")),
    )
