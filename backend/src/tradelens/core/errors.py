"""API errors with the DD 4.1 error body (``{"error": {code, message, request_id, details}}``).

Services raise ``ApiError``; ``app.exception_handlers`` turns it into the JSON body with the
request ID. No web framework is imported here, so services and repositories may use it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class ApiError(Exception):
    """An error the API answers with a fixed status and code (DD 4.1 table)."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """Create the error.

        Args:
            status: HTTP status.
            code: Machine-readable code, e.g. ``plan_required``.
            message: Human-readable message (never contains secrets).
            details: Extra fields for the client.
            headers: Response headers, e.g. ``Retry-After``.
        """
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = dict(details or {})
        self.headers = dict(headers or {})


def not_found(what: str = "Not found") -> ApiError:
    """404 ``not_found``: missing, or owned by another user (NFR-10)."""
    return ApiError(404, "not_found", what)


def not_authenticated() -> ApiError:
    """401 ``not_authenticated``: no valid session."""
    return ApiError(401, "not_authenticated", "Sign in to continue")


def session_ended() -> ApiError:
    """401 ``session_ended``: the session was revoked (third sign-in, FR-ACC-05)."""
    return ApiError(401, "session_ended", "You were signed out because you signed in elsewhere")


def validation_error(field: str, issue: str) -> ApiError:
    """400 ``validation_error`` with one ``{field, issue}`` detail."""
    return ApiError(400, "validation_error", "Invalid request",
                    {"errors": [{"field": field, "issue": issue}]})  # fmt: skip


def rate_limited(retry_after: int) -> ApiError:
    """429 ``rate_limited`` with ``Retry-After``."""
    return ApiError(429, "rate_limited", "Too many requests, try again shortly",
                    {"retry_after": retry_after}, {"Retry-After": str(retry_after)})  # fmt: skip
