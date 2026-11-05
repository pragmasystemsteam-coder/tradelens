"""HTTP middleware: request IDs for structured logs (coding standards)."""

from __future__ import annotations

import re
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tradelens.core.logging import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"
SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


def pick_request_id(incoming: str | None) -> str:
    """Reuse a caller's request ID only if it is short and safe to log; otherwise make one.

    Args:
        incoming: Value of the X-Request-ID header, if any.

    Returns:
        The request ID to use.
    """
    if incoming and SAFE_REQUEST_ID.fullmatch(incoming):
        return incoming
    return uuid4().hex


class RequestIdMiddleware:
    """Pure ASGI middleware (safe for streaming responses such as SSE).

    Sets ``request_id_var`` for the request so every log line carries it, and echoes the ID in
    the X-Request-ID response header.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one ASGI call."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        raw = headers.get(REQUEST_ID_HEADER.lower().encode("latin-1"))
        request_id = pick_request_id(raw.decode("latin-1") if raw else None)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        token = request_id_var.set(request_id)
        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)
