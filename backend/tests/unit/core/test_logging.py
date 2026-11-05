"""Structured JSON logs (coding standards: structured logging, never print)."""

import json
import logging

from tradelens.core.logging import JsonFormatter, request_id_var


def make_record(message: str) -> logging.LogRecord:
    return logging.LogRecord("tradelens.test", logging.WARNING, __file__, 1, message, None, None)


def test_json_formatter_emits_level_logger_and_message():
    line = json.loads(JsonFormatter().format(make_record("db down")))
    assert line["level"] == "WARNING"
    assert line["logger"] == "tradelens.test"
    assert line["message"] == "db down"
    assert line["ts"].endswith("Z")
    assert "request_id" not in line


def test_json_formatter_includes_request_id_when_set():
    token = request_id_var.set("req-123")
    try:
        line = json.loads(JsonFormatter().format(make_record("hello")))
    finally:
        request_id_var.reset(token)
    assert line["request_id"] == "req-123"
