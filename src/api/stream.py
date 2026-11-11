"""Live stream: fan out JSON messages to connected WebSocket clients."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.core.timeutils import utc_now

MESSAGE_TYPES = {"event", "prediction", "signal", "order", "status"}


class Broadcaster:
    """Delivers messages to every subscriber. Safe to publish from worker threads."""

    def __init__(self, max_queue: int = 1000) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._max_queue = max_queue

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(self._max_queue)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def _fan_out(self, message: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            # A client that cannot keep up loses messages rather than blocking the others.
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(message)

    def publish(self, message_type: str, data: Any) -> None:
        if message_type not in MESSAGE_TYPES:
            raise ValueError(f"unknown stream message type: {message_type}")
        message = {"type": message_type, "data": data, "ts": utc_now().isoformat()}
        if self._loop is None or not self._subscribers:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._fan_out(message)
        else:
            self._loop.call_soon_threadsafe(self._fan_out, message)


router = APIRouter()


@router.websocket("/api/v1/stream")
async def stream(websocket: WebSocket) -> None:
    services = websocket.app.state.services
    broadcaster: Broadcaster = services.broadcaster
    await websocket.accept()
    queue = broadcaster.subscribe()
    try:
        await websocket.send_json(
            {"type": "status", "data": services.status(), "ts": utc_now().isoformat()}
        )
        while True:
            await websocket.send_json(await queue.get())
    except WebSocketDisconnect:
        pass
    finally:
        broadcaster.unsubscribe(queue)
