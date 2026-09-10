"""Dedicated SSE Broadcaster for Live Island State Streaming."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, Optional, Set

from src.oracle.live_island.contracts import LiveIslandPillState

logger = logging.getLogger(__name__)


class LiveIslandBroadcaster:
    """Manages active SSE client subscribers and broadcasts compact state updates."""

    def __init__(self, ping_interval_seconds: float = 15.0) -> None:
        self.ping_interval_seconds = ping_interval_seconds
        self._clients: Set[asyncio.Queue[str]] = set()
        self._lock = asyncio.Lock()
        self._last_payload: Optional[str] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def broadcast_state(self, state: LiveIslandPillState) -> None:
        """Called by thread-safe reducer callback to push state patch to all SSE queues."""
        payload_dict = state.to_frontend_payload()
        data_str = json.dumps(payload_dict)
        frame = f"id: {state.sequence_id}\nevent: live_island_state\ndata: {data_str}\n\n"
        self._last_payload = frame

        if not self._clients:
            return

        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._push_to_all(frame), self._loop)

    async def _push_to_all(self, frame: str) -> None:
        async with self._lock:
            for q in list(self._clients):
                try:
                    q.put_nowait(frame)
                except asyncio.QueueFull:
                    # Drop frame or pop oldest if full
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    q.put_nowait(frame)

    async def subscribe(self, initial_state: Optional[LiveIslandPillState] = None) -> AsyncGenerator[str, None]:
        """Registers a new SSE client, yields initial full state, and streams updates."""
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=32)

        async with self._lock:
            self._clients.add(q)
            logger.info("Live Island SSE client connected. Active subscribers: %d", len(self._clients))

        try:
            # Send initial full state snapshot
            if initial_state is not None:
                payload = json.dumps(initial_state.to_frontend_payload())
                yield f"id: {initial_state.sequence_id}\nevent: live_island_state\ndata: {payload}\n\n"
            elif self._last_payload is not None:
                yield self._last_payload

            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=self.ping_interval_seconds)
                    yield msg
                except asyncio.TimeoutError:
                    # Heartbeat ping
                    yield "event: ping\ndata: {}\n\n"
        finally:
            async with self._lock:
                self._clients.discard(q)
                logger.info("Live Island SSE client disconnected. Remaining subscribers: %d", len(self._clients))
