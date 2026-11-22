"""Public interface of notifications for other modules and the worker (ADR-0001 section 4)."""

from tradelens.modules.notifications.service import (
    KINDS,
    TEMPLATE_FIELDS,
    EmailTransport,
    OutgoingEmail,
    compose,
    deliver_due,
    enqueue_email,
    queue_email,
    retry_delay,
)

__all__ = [
    "KINDS",
    "TEMPLATE_FIELDS",
    "EmailTransport",
    "OutgoingEmail",
    "compose",
    "deliver_due",
    "enqueue_email",
    "queue_email",
    "retry_delay",
]
