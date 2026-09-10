"""FastAPI Endpoint Verification for Live Island."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.api.live_island_api import router
from src.oracle.live_island.hub import LiveIslandIntelligenceHub

app = FastAPI(title="Citadel Live Island Test App")
app.include_router(router)

client = TestClient(app)


def test_live_island_state_endpoint():
    """Verifies /v1/oracle/live-island/state returns 200 and valid JSON schema."""
    hub = LiveIslandIntelligenceHub.get_instance()
    hub.set_spine_bias("bull")

    resp = client.get("/v1/oracle/live-island/state")
    assert resp.status_code == 200
    data = resp.json()
    assert "spineBias" in data
    assert data["spineBias"] == "bull"
    assert "activeEvents" in data
    assert "memoryEvents" in data
    assert "burstCount" in data
    assert "sequenceId" in data
    assert "stateVersion" in data


@pytest.mark.asyncio
async def test_live_island_stream_generator():
    """Verifies that the stream generator yields valid SSE frames."""
    hub = LiveIslandIntelligenceHub.get_instance()
    hub.set_spine_bias("bear")

    gen = hub.broadcaster.subscribe(initial_state=hub.reducer.current_state)
    frame = await anext(gen)
    assert "event: live_island_state" in frame
    assert '"spineBias": "bear"' in frame
    await gen.aclose()
