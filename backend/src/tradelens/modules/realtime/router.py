"""``GET /stream``: live updates over Server-Sent Events (DD 4.4; task 2.8)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from tradelens.core.config import AppConfig
from tradelens.core.deps import (
    Viewer,
    get_async_redis,
    get_config,
    get_instrument_classes,
    get_stream_viewer,
)
from tradelens.modules.realtime.service import (
    StreamSpec,
    acquire_stream,
    event_stream,
    keep_stream,
    parse_topics,
    release_stream,
)

router = APIRouter(prefix="/api/v1", tags=["realtime"])
HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.get("/stream")
async def stream(
    request: Request,
    viewer: Annotated[Viewer, Depends(get_stream_viewer)],
    aredis: Annotated[Any, Depends(get_async_redis)],  # noqa: ANN401 - redis.asyncio.Redis
    cfg: Annotated[AppConfig, Depends(get_config)],
    instruments: Annotated[Mapping[str, str], Depends(get_instrument_classes)],
    topics: Annotated[str, Query(max_length=1000)] = "",
) -> StreamingResponse:
    """Open a stream of ``scanner``, ``chart:{instrument}`` and ``price:{instrument}`` topics.

    ``data`` and ``user`` are always on. A refused topic answers before any stream opens.
    """
    channels = parse_topics(topics, instruments, viewer.limits, user_id=viewer.user_id)
    await acquire_stream(aredis, viewer.user_id, cfg.sse_max_streams)
    try:
        allowed = frozenset(c for c, a in instruments.items() if viewer.limits.allows_asset(a))
        spec = StreamSpec(viewer.user_id, viewer.session_id, channels, allowed,
                          throttle_s=cfg.sse_price_throttle_ms / 1000,
                          ping_s=float(cfg.sse_ping_seconds))  # fmt: skip
        pubsub = aredis.pubsub()
    except Exception:
        await release_stream(aredis, viewer.user_id)
        raise

    released = False

    async def release_once() -> None:
        nonlocal released
        if not released:
            released = True
            await release_stream(aredis, viewer.user_id)

    async def body() -> AsyncIterator[str]:
        try:
            async for chunk in event_stream(
                pubsub, spec, disconnected=request.is_disconnected,
                on_ping=lambda: keep_stream(aredis, viewer.user_id),
            ):  # fmt: skip
                yield chunk
        finally:
            await release_once()

    return SlotStreamingResponse(body(), release_once, media_type="text/event-stream",
                                 headers=HEADERS)  # fmt: skip


class SlotStreamingResponse(StreamingResponse):
    """A stream that frees its slot even when the client left before the body started."""

    def __init__(
        self,
        content: AsyncIterator[str],
        release: Callable[[], Awaitable[None]],
        **kwargs: Any,  # noqa: ANN401 - StreamingResponse keyword arguments
    ) -> None:
        super().__init__(content, **kwargs)
        self._release = release

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Send the stream; release the slot however it ends (released only once)."""
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._release()
