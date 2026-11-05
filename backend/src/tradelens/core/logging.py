"""Structured JSON logging with request IDs (coding standards: never print)."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    """Formats a log record as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        """Render ``record`` as JSON with ts, level, logger, message and request_id.

        Args:
            record: The record to format.

        Returns:
            One line of JSON.
        """
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id is not None:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "info") -> None:
    """Send all logs to stderr as JSON.

    Args:
        level: Log level name (debug, info, warning, error).
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
