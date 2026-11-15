"""Every failure answers with the DD 4.1 error body and the request ID (task 2.4)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from tradelens.core.errors import ApiError
from tradelens.core.logging import request_id_var

log = logging.getLogger("tradelens.app.errors")
HTTP_CODES = {401: "not_authenticated", 403: "forbidden", 404: "not_found",
              405: "method_not_allowed", 429: "rate_limited"}  # fmt: skip
HTTP_MESSAGES = {404: "Not found", 405: "Method not allowed"}


def error_body(code: str, message: str, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """``{"error": {code, message, request_id, details}}``."""
    return {"error": {"code": code, "message": message, "request_id": request_id_var.get(),
                      "details": dict(details or {})}}  # fmt: skip


def _api_error(_: Request, exc: Exception) -> JSONResponse:
    exc = cast(ApiError, exc)
    return JSONResponse(error_body(exc.code, exc.message, exc.details), exc.status,
                        headers=exc.headers)  # fmt: skip


def _validation(_: Request, exc: Exception) -> JSONResponse:
    exc = cast(RequestValidationError, exc)
    errors = []
    for e in exc.errors():
        loc = [str(p) for p in e.get("loc", ()) if p not in ("body", "query", "path")]
        errors.append({"field": ".".join(loc) or "body", "issue": str(e.get("type", "invalid"))})
    return JSONResponse(error_body("validation_error", "Invalid request", {"errors": errors}), 400)


def _http(_: Request, exc: Exception) -> JSONResponse:
    exc = cast(StarletteHTTPException, exc)
    code = HTTP_CODES.get(exc.status_code, "http_error")
    message = HTTP_MESSAGES.get(exc.status_code, str(exc.detail))
    return JSONResponse(error_body(code, message), exc.status_code, headers=exc.headers)


def _unavailable(_: Request, exc: Exception) -> JSONResponse:
    log.error("dependency unavailable", extra={"error": type(exc).__name__})
    return JSONResponse(error_body("unavailable", "Service temporarily unavailable"), 503)


def internal_error_body() -> dict[str, Any]:
    """The 500 body (no exception text is ever returned)."""
    return error_body("internal_error", "Internal error")


def install(app: FastAPI) -> None:
    """Register the handlers on ``app``."""
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation)
    app.add_exception_handler(StarletteHTTPException, _http)
    for exc in (OperationalError, RedisConnectionError, RedisTimeoutError):
        app.add_exception_handler(exc, _unavailable)
