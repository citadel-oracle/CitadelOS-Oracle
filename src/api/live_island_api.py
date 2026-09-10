"""Live Island Dedicated FastAPI Router.

Exposes:
- GET /v1/oracle/live-island/stream : Dedicated lightweight SSE stream
- GET /v1/oracle/live-island/state : Current 1 Hero + 3 Active + 3 Memory state snapshot
"""

from __future__ import annotations

import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from src.oracle.live_island.hub import LiveIslandIntelligenceHub

router = APIRouter(tags=["LiveIsland"])


@router.get("/v1/oracle/live-island/stream")
async def oracle_live_island_stream(request: Request):
    """Dedicated Live Island SSE stream delivering compact ~300B layout patches."""
    hub = LiveIslandIntelligenceHub.get_instance()
    hub.start()
    hub.broadcaster.set_loop(asyncio.get_running_loop())

    async def event_generator():
        initial = hub.reducer.current_state
        async for msg in hub.broadcaster.subscribe(initial_state=initial):
            if await request.is_disconnected():
                break
            yield msg

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Citadel-Transport": "ORACLE_LIVE_ISLAND_SSE",
        },
    )


@router.get("/v1/oracle/live-island/state")
def oracle_live_island_state():
    """Returns current snapshot of Live Island 1 Hero + 3 Active + 3 Memory state."""
    hub = LiveIslandIntelligenceHub.get_instance()
    return hub.reducer.current_state.to_frontend_payload()
