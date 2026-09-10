"""Synthetic Sequence and Hub Integration Tests for Live Island."""

import asyncio
import pytest

from src.oracle.live_island.contracts import PresentationPhase, SeverityLevel
from src.oracle.live_island.hub import LiveIslandIntelligenceHub
from src.oracle.live_island.registry import LiveIslandRegistry


def test_hub_synthetic_event_sequence():
    """Feeds deterministic sequence through the complete hub and verifies end-to-end reducer & journal."""
    registry = LiveIslandRegistry(burst_window_ms=0, hero_min_tenure_ms=500)
    hub = LiveIslandIntelligenceHub(registry=registry)

    # 1. Master Spine starts Bearish, Feed Baseline Ready
    hub.set_spine_bias("bear")
    hub.suppression_guard.set_baseline_ready(True)
    assert hub.reducer.current_state.spine_bias == "bear"

    # 2. VIX Shock (+25% spike)
    hub.vix_detector.on_tick({"instrument_key": "NSE_INDEX|India VIX", "ltp": 14.0})
    vix_ev = hub.vix_detector.on_tick({"instrument_key": "NSE_INDEX|India VIX", "ltp": 17.5})
    assert vix_ev is not None
    hub._record_and_dispatch(vix_ev, "VIX_SHOCK")

    state = hub.reducer.current_state
    assert len(state.active_events) == 1
    assert state.active_events[0].id == "vix"

    # 3. PCR Drop (-20% drop)
    hub.pcr_detector.on_tick({"instrument_key": "NSE_FO|CE_1", "instrument_type": "CE", "oi": 100_000})
    hub.pcr_detector.on_tick({"instrument_key": "NSE_FO|PE_1", "instrument_type": "PE", "oi": 100_000})
    pcr_ev = hub.pcr_detector.on_tick({"instrument_key": "NSE_FO|PE_1", "instrument_type": "PE", "oi": 80_000})
    assert pcr_ev is not None
    hub._record_and_dispatch(pcr_ev, "PCR_DROP")

    state = hub.reducer.current_state
    assert len(state.active_events) == 2
    assert state.active_events[0].id == "vix"  # VIX is still Hero
    assert state.active_events[1].id == "pcr"  # PCR is companion

    # 4. GEX Polarity Flip (Critical event takes Hero immediately)
    hub.notify_gex_update(500_000_000.0)
    hub.notify_gex_update(-200_000_000.0)  # Polarity flip to negative!

    state = hub.reducer.current_state
    assert len(state.active_events) == 3
    assert state.active_events[0].id == "gex"  # GEX took Hero!
    assert state.active_events[1].id == "vix"
    assert state.active_events[2].id == "pcr"

    # 5. Verify journal entries recorded
    journal_entries = hub.journal.get_recent(limit=10)
    assert len(journal_entries) >= 3
    event_ids = [e["event_id"] for e in journal_entries]
    assert "vix" in event_ids
    assert "pcr" in event_ids
    assert "gex" in event_ids

    # 6. Verify SSE payload generation
    frontend_payload = state.to_frontend_payload()
    assert frontend_payload["spineBias"] == "bear"
    assert len(frontend_payload["activeEvents"]) == 3
    assert frontend_payload["activeEvents"][0]["archetype"] == "polarity"
    assert frontend_payload["sequenceId"] > 0


@pytest.mark.asyncio
async def test_sse_broadcaster_subscription():
    """Verifies that dedicated SSE broadcaster streams initial state and state updates."""
    hub = LiveIslandIntelligenceHub(registry=LiveIslandRegistry(burst_window_ms=0))
    hub.set_spine_bias("bull")

    gen = hub.broadcaster.subscribe(initial_state=hub.reducer.current_state)
    initial_frame = await anext(gen)

    assert "event: live_island_state" in initial_frame
    assert '"spineBias": "bull"' in initial_frame
    await gen.aclose()
