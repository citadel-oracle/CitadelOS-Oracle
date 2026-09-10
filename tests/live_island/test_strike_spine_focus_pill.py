"""Tests for Enhanced Strike Spine -> Live Island Pill binding, deduplication, and transitions."""

import pytest
from src.oracle.live_island.adapters import BuildupAdapter
from src.oracle.live_island.contracts import (
    ArchetypeType,
    EventBias,
    NumericTrend,
    PresentationPhase,
    SeverityLevel,
)
from src.oracle.live_island.hub import LiveIslandIntelligenceHub
from src.oracle.live_island.registry import LiveIslandRegistry


def test_strike_spine_focus_initial_emission():
    """Verifies that Enhanced Strike Spine structural focus emits faithfully on initial arrival."""
    adapter = BuildupAdapter()

    best_stack = {
        "strike": 23550.0,
        "direction": "CALL",
        "state": "BULLISH STRUCTURE",
        "primary_flow": {
            "label": "CALL_BUYING",
            "arrow": "↓↓",
            "load": 58.92,
        },
        "defence_flow": {
            "label": "PUT_WRITING",
            "arrow": "↓↓",
            "load": 55.21,
        },
        "migration": {
            "state": "BULLISH_SHIFT_UP",
            "label": "Upward migration visible",
        },
    }
    spine = [
        {"strike": 23550.0, "CE": {"positioning": "LONG_BUILDUP"}, "PE": {"positioning": "SHORT_BUILDUP"}}
    ]

    ev = adapter.on_strike_spine_focus(best_stack, spine)
    assert ev is not None
    assert ev.id == "buildup_23550"
    assert ev.family == "buildup"
    assert "23550" in ev.title
    assert "23550 · CALL BUYING" in ev.short_title
    assert ev.event_bias == EventBias.BULLISH.value
    assert ev.numeric_trend == NumericTrend.UP.value
    assert ev.phase == PresentationPhase.IMPACT.value
    assert ev.archetype == ArchetypeType.LEVEL.value
    assert ev.archetype_data["strike"] == 23550
    assert ev.archetype_data["primaryFlow"] == "CALL_BUYING"
    assert ev.archetype_data["defenceFlow"] == "PUT_WRITING"
    assert ev.archetype_data["positioning"] == "LONG_BUILDUP"
    assert ev.archetype_data["load"] == 58.92
    assert "ACCEL ↓↓" in ev.current_value


def test_strike_spine_focus_repeated_identical_state_suppression():
    """Verifies that repeated identical state emits NO new notification."""
    adapter = BuildupAdapter()

    best_stack = {
        "strike": 23550.0,
        "direction": "CALL",
        "state": "BULLISH STRUCTURE",
        "primary_flow": {"label": "CALL_BUYING", "arrow": "↓↓", "load": 58.92},
        "defence_flow": {"label": "PUT_WRITING", "arrow": "↓↓", "load": 55.21},
        "migration": {"state": "BULLISH_SHIFT_UP", "label": "Upward migration visible"},
    }
    spine = [
        {"strike": 23550.0, "CE": {"positioning": "LONG_BUILDUP"}, "PE": {"positioning": "SHORT_BUILDUP"}}
    ]

    ev1 = adapter.on_strike_spine_focus(best_stack, spine)
    assert ev1 is not None

    # Repeated identical call: must return None (NO new notification, NO sound)
    ev2 = adapter.on_strike_spine_focus(best_stack, spine)
    assert ev2 is None

    # Even with repeated calls, identical structure must not re-notify
    best_stack_copy = dict(best_stack)
    ev3 = adapter.on_strike_spine_focus(best_stack_copy, spine)
    assert ev3 is None


def test_strike_spine_focus_migration_transition():
    """Verifies that focus strike migration (e.g. 23500 -> 23550) triggers a notification."""
    adapter = BuildupAdapter()

    stack_23500 = {
        "strike": 23500.0,
        "direction": "CALL",
        "state": "BULLISH STRUCTURE",
        "primary_flow": {"label": "CALL_BUYING", "arrow": "↑", "load": 50.0},
        "defence_flow": {"label": "PUT_WRITING", "arrow": "→", "load": 40.0},
        "migration": {"state": "SCATTERED", "label": "No clean migration"},
    }
    ev1 = adapter.on_strike_spine_focus(stack_23500)
    assert ev1 is not None
    assert ev1.id == "buildup_23500"

    # Migration to 23550
    stack_23550 = {
        "strike": 23550.0,
        "direction": "CALL",
        "state": "BULLISH STRUCTURE",
        "primary_flow": {"label": "CALL_BUYING", "arrow": "↓↓", "load": 58.92},
        "defence_flow": {"label": "PUT_WRITING", "arrow": "↓↓", "load": 55.21},
        "migration": {"state": "BULLISH_SHIFT_UP", "label": "Upward migration visible"},
    }
    ev2 = adapter.on_strike_spine_focus(stack_23550)
    assert ev2 is not None
    assert ev2.id == "buildup_23550"
    assert ev2.archetype_data["oldStrike"] == "23500"
    assert ev2.archetype_data["newStrike"] == "23550"
    assert ev2.severity == SeverityLevel.HIGH.value


def test_strike_spine_focus_flow_regime_flip():
    """Verifies that primary flow change (e.g. CALL_BUYING -> CALL_WRITING) triggers transition."""
    adapter = BuildupAdapter()

    stack_call_buying = {
        "strike": 23550.0,
        "direction": "CALL",
        "state": "BULLISH STRUCTURE",
        "primary_flow": {"label": "CALL_BUYING", "arrow": "↑", "load": 60.0},
        "defence_flow": {"label": "PUT_WRITING", "arrow": "→", "load": 45.0},
    }
    adapter.on_strike_spine_focus(stack_call_buying)

    stack_call_writing = {
        "strike": 23550.0,
        "direction": "PUT",
        "state": "BEARISH STRUCTURE",
        "primary_flow": {"label": "CALL_WRITING", "arrow": "↓↓", "load": 65.0},
        "defence_flow": {"label": "PUT_BUYING", "arrow": "↓↓", "load": 52.0},
    }
    ev_flip = adapter.on_strike_spine_focus(stack_call_writing)
    assert ev_flip is not None
    assert ev_flip.event_bias == EventBias.BEARISH.value
    assert ev_flip.numeric_trend == NumericTrend.DOWN.value
    assert "CALL WRITING" in ev_flip.current_value
    assert ev_flip.previous_value == "CALL BUYING"


def test_hub_ingest_prioritizes_enhanced_strike_spine_over_distant_strike():
    """Verifies Hub ingests focus strike (23550) instead of an unrelated distant strike (23800)."""
    registry = LiveIslandRegistry(burst_window_ms=0, hero_min_tenure_ms=0)
    hub = LiveIslandIntelligenceHub(registry=registry)

    snapshot = {
        "argus": {
            "data": {
                "atm_window": [
                    {"strike": 23800, "ce": {"positioning": "LONG_BUILDUP"}, "pe": {"positioning": "NEUTRAL"}},
                ],
                "tactical_edge": {
                    "argus_prime": {
                        "best_strike_stack": {
                            "strike": 23550.0,
                            "direction": "CALL",
                            "state": "BULLISH STRUCTURE",
                            "primary_flow": {"label": "CALL_BUYING", "arrow": "↓↓", "load": 58.92},
                            "defence_flow": {"label": "PUT_WRITING", "arrow": "↓↓", "load": 55.21},
                            "migration": {"state": "BULLISH_SHIFT_UP", "label": "Upward migration visible"},
                        },
                        "strike_spine": [
                            {"strike": 23550.0, "CE": {"positioning": "LONG_BUILDUP"}, "PE": {"positioning": "SHORT_BUILDUP"}},
                            {"strike": 23800.0, "CE": {"positioning": "LONG_BUILDUP"}, "PE": {"positioning": "NEUTRAL"}},
                        ],
                    }
                }
            }
        }
    }

    hub.ingest_live_analytics_snapshot(snapshot)
    active = hub.reducer.current_state.active_events
    buildup_events = [e for e in active if e.family == "buildup"]

    assert len(buildup_events) == 1
    # MUST be 23550 (the focus strike), NOT 23800!
    assert buildup_events[0].id == "buildup_23550"
    assert "23550" in buildup_events[0].title
    assert "23800" not in buildup_events[0].title
