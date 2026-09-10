"""Unit Tests for Live Island Reducer: Capacity, Hysteresis, Coalescing, and Memory."""

import time
import pytest

from src.oracle.live_island.contracts import (
    ArchetypeType,
    EventBias,
    LiveIslandEvent,
    NumericTrend,
    PresentationPhase,
    SeverityLevel,
)
from src.oracle.live_island.reducer import LiveIslandReducer
from src.oracle.live_island.registry import LiveIslandRegistry


def _make_event(
    event_id: str,
    family: str,
    severity: str = SeverityLevel.MEDIUM.value,
    priority: float = 2.0,
    val: str = "10.0",
) -> LiveIslandEvent:
    return LiveIslandEvent(
        id=event_id,
        family=family,
        title=f"Event {event_id}",
        short_title=f"{event_id} {val}",
        current_value=val,
        severity=severity,
        priority_weight=priority,
    )


def test_capacity_enforcement():
    """Enforces exactly 1 Hero + max 3 Active Companions (total active <= 4), max 3 Memory."""
    registry = LiveIslandRegistry(burst_window_ms=0)  # Immediate dispatch for deterministic test
    reducer = LiveIslandReducer(registry=registry)

    # Dispatch 5 distinct family events
    for i in range(1, 6):
        reducer.dispatch_event(_make_event(f"ev_{i}", f"fam_{i}", priority=float(i)))

    state = reducer.current_state
    # Active events strictly capped at 4 (1 Hero + 3 Companions)
    assert len(state.active_events) == 4
    # Evicted 5th event moved lowest-priority companion (ev_2) to Memory
    assert len(state.memory_events) == 1
    assert state.memory_events[0].id == "ev_2"


def test_in_place_event_update():
    """Verifies that subsequent updates to the same family update in-place without creating duplicates."""
    registry = LiveIslandRegistry(burst_window_ms=0)
    reducer = LiveIslandReducer(registry=registry)

    # Initial PCR = 0.90
    reducer.dispatch_event(_make_event("pcr", "pcr", val="0.90"))
    assert len(reducer.current_state.active_events) == 1
    assert reducer.current_state.active_events[0].current_value == "0.90"

    # Updated PCR = 0.95
    reducer.dispatch_event(_make_event("pcr", "pcr", val="0.95"))
    state = reducer.current_state
    # Must remain exactly 1 event
    assert len(state.active_events) == 1
    assert state.active_events[0].current_value == "0.95"
    assert state.active_events[0].previous_value == "0.90"


def test_hero_hysteresis_and_critical_override():
    """Verifies Hero tenure lock and critical override behavior."""
    registry = LiveIslandRegistry(burst_window_ms=0, hero_min_tenure_ms=1000, hero_takeover_margin=1.25)
    reducer = LiveIslandReducer(registry=registry)

    # 1. Establish initial Hero: VIX (Medium severity, priority 2.0)
    reducer.dispatch_event(_make_event("vix", "vix", severity=SeverityLevel.MEDIUM.value, priority=2.0))
    assert reducer.current_state.active_events[0].id == "vix"

    # 2. Challenger with slightly higher priority (3.0) arrives immediately (within 1000ms)
    reducer.dispatch_event(_make_event("pcr", "pcr", severity=SeverityLevel.HIGH.value, priority=3.0))
    state = reducer.current_state
    # VIX must remain Hero due to hysteresis tenure lock!
    assert state.active_events[0].id == "vix"
    assert state.active_events[1].id == "pcr"

    # 3. Critical event (GEX Flip) arrives immediately: MUST bypass tenure lock!
    reducer.dispatch_event(_make_event("gex", "gex", severity=SeverityLevel.CRITICAL.value, priority=4.5))
    state_after_critical = reducer.current_state
    # GEX Flip immediately takes Hero!
    assert state_after_critical.active_events[0].id == "gex"
    assert state_after_critical.active_events[1].id == "vix"


def test_microburst_coalescing():
    """Verifies that events arriving within burst_window_ms are batched together."""
    dispatched_states = []

    def on_change(state):
        dispatched_states.append(state)

    registry = LiveIslandRegistry(burst_window_ms=50)  # 50ms burst window
    reducer = LiveIslandReducer(registry=registry, on_state_change=on_change)

    # Dispatch 3 events rapidly (within 10ms)
    reducer.dispatch_event(_make_event("e1", "f1", priority=1.0))
    reducer.dispatch_event(_make_event("e2", "f2", priority=2.0))
    reducer.dispatch_event(_make_event("e3", "f3", priority=3.0))

    # Before burst window expires, 0 dispatches
    assert len(dispatched_states) == 0

    # Wait for burst window to expire
    time.sleep(0.08)

    # Exactly ONE coalesced dispatch occurs with all 3 events
    assert len(dispatched_states) == 1
    final_state = dispatched_states[0]
    assert len(final_state.active_events) == 3
    assert final_state.burst_count == 3
    # Sorted by priority descending: e3 should be Hero!
    assert final_state.active_events[0].id == "e3"


def test_contradictory_memory_eviction():
    """Verifies that opposite directional events clear obsolete memory."""
    registry = LiveIslandRegistry(burst_window_ms=0)
    reducer = LiveIslandReducer(registry=registry)

    # Evict an UP event to memory
    ev_up = _make_event("vix", "vix", val="15.0")
    ev_up.numeric_trend = NumericTrend.UP.value
    reducer._add_to_memory(ev_up)
    assert len(reducer.current_state.memory_events) == 1

    # Opposite DOWN event arrives
    ev_down = _make_event("vix_down", "vix", val="12.0")
    ev_down.numeric_trend = NumericTrend.DOWN.value
    reducer.dispatch_event(ev_down)

    # Contradictory UP memory must be wiped!
    state = reducer.current_state
    assert len(state.memory_events) == 0


def test_settled_hero_yields_to_fair_priority():
    """Verifies that once a Hero transitions to SETTLED, an incoming event with priority >= hero takes over without 1.25x margin."""
    registry = LiveIslandRegistry(burst_window_ms=0, hero_min_tenure_ms=0, hero_takeover_margin=1.25)
    reducer = LiveIslandReducer(registry=registry)

    # 1. Establish initial Buildup Hero (priority 2.8)
    buildup = _make_event("buildup_23550", "buildup", priority=2.8)
    reducer.dispatch_event(buildup)
    assert reducer.current_state.active_events[0].id == "buildup_23550"

    # In IMPACT phase, an event with priority 3.0 (< 2.8 * 1.25 = 3.5) cannot take Hero
    oi_shift = _make_event("oi_shift", "oi_shift", priority=3.0)
    reducer.dispatch_event(oi_shift)
    assert reducer.current_state.active_events[0].id == "buildup_23550"
    assert reducer.current_state.active_events[1].id == "oi_shift"

    # 2. Advance Buildup to SETTLED phase
    reducer.current_state.active_events[0].phase = PresentationPhase.SETTLED.value

    # 3. New event PCR with priority 3.0 (>= 2.8) arrives: MUST take Hero now that Buildup is SETTLED!
    pcr = _make_event("pcr_lead", "pcr", priority=3.0)
    reducer.dispatch_event(pcr)
    assert reducer.current_state.active_events[0].id == "pcr_lead"
    assert reducer.current_state.active_events[1].id == "buildup_23550"

