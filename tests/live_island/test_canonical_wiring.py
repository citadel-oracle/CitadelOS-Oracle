"""Deterministic Integration Tests for Canonical Live Island Producer Wiring."""

import types
import pytest

from src.oracle.live_island.contracts import (
    ArchetypeType,
    EventBias,
    NumericTrend,
    PresentationPhase,
    SeverityLevel,
)
from src.oracle.live_island.hub import LiveIslandIntelligenceHub
from src.oracle.live_island.registry import LiveIslandRegistry


def test_all_11_families_canonical_wiring():
    """Verifies that all 11 required Live Island families successfully hook into the Hub."""
    registry = LiveIslandRegistry(burst_window_ms=0, hero_min_tenure_ms=0)
    hub = LiveIslandIntelligenceHub(registry=registry)
    hub.suppression_guard.set_baseline_ready(True)

    # -------------------------------------------------------------------------
    # 1. India VIX (Fast streaming tick)
    # -------------------------------------------------------------------------
    hub.on_tick({"instrument_key": "NSE_INDEX|India VIX", "ltp": 14.0})
    hub.on_tick({"instrument_key": "NSE_INDEX|India VIX", "ltp": 14.5})  # +3.57% >= 2%
    assert any(e.family == "vix" for e in hub.reducer.current_state.active_events)

    # -------------------------------------------------------------------------
    # 2. Live PCR (Fast streaming tick)
    # -------------------------------------------------------------------------
    hub.on_tick({"instrument_key": "NSE_FO|CE_ATM", "instrument_type": "CE", "oi": 100_000})
    hub.on_tick({"instrument_key": "NSE_FO|PE_ATM", "instrument_type": "PE", "oi": 100_000})
    hub.on_tick({"instrument_key": "NSE_FO|PE_ATM", "instrument_type": "PE", "oi": 110_000})  # +10% >= 5%
    assert any(e.family == "pcr" for e in hub.reducer.current_state.active_events)

    # -------------------------------------------------------------------------
    # 3. Live OI Surge (Fast streaming tick)
    # -------------------------------------------------------------------------
    hub.on_tick({"instrument_key": "NSE_FO|24500CE", "instrument_type": "CE", "oi": 100_000})
    hub.on_tick({"instrument_key": "NSE_FO|24500CE", "instrument_type": "CE", "oi": 180_000})  # +80k >= 50k
    assert any(e.family == "oi" for e in hub.reducer.current_state.active_events)

    # -------------------------------------------------------------------------
    # 4. Fast IV Velocity (Fast streaming tick)
    # -------------------------------------------------------------------------
    hub.on_tick({"instrument_key": "NSE_FO|24500CE", "strike_price": 24500, "iv": 14.0})
    hub.on_tick({"instrument_key": "NSE_FO|24500CE", "strike_price": 24500, "iv": 16.5})  # +2.5 vol pts >= 1.5
    assert any(e.family == "iv_velocity" for e in hub.reducer.current_state.active_events)

    # -------------------------------------------------------------------------
    # 5. Particular Option Premium Acceleration (Fast streaming tick)
    # -------------------------------------------------------------------------
    t0 = 1000.0
    hub.on_tick({"instrument_key": "NSE_FO|24100PE", "instrument_type": "PE", "strike_price": 24100, "ltp": 50.0, "ltt": t0})
    hub.on_tick({"instrument_key": "NSE_FO|24100PE", "instrument_type": "PE", "strike_price": 24100, "ltp": 51.0, "ltt": t0 + 2.0})
    hub.on_tick({"instrument_key": "NSE_FO|24100PE", "instrument_type": "PE", "strike_price": 24100, "ltp": 54.0, "ltt": t0 + 4.0})
    hub.on_tick({"instrument_key": "NSE_FO|24100PE", "instrument_type": "PE", "strike_price": 24100, "ltp": 62.0, "ltt": t0 + 6.0})
    all_events = hub.reducer.current_state.active_events + hub.reducer.current_state.memory_events
    assert any(e.family == "premium_acceleration" for e in all_events)

    # -------------------------------------------------------------------------
    # 6. GEX Polarity Flip (Canonical snapshot)
    # -------------------------------------------------------------------------
    hub.ingest_live_analytics_snapshot({
        "option_buyer_intelligence": {
            "option_intelligence": {"gex": {"total_net_gex_inr_cr": 45.0}}
        }
    })
    hub.ingest_live_analytics_snapshot({
        "option_buyer_intelligence": {
            "option_intelligence": {"gex": {"total_net_gex_inr_cr": -15.0}}
        }
    })
    assert hub.reducer.current_state.active_events[0].id == "gex"
    assert hub.reducer.current_state.active_events[0].archetype == ArchetypeType.POLARITY.value

    # -------------------------------------------------------------------------
    # 7. Sudden OI (Canonical snapshot)
    # -------------------------------------------------------------------------
    hub.ingest_live_analytics_snapshot({
        "option_buyer_intelligence": {
            "sudden_oi": {
                "CALL": {
                    "current_5m_activity": 125_000,
                    "normal_5m_activity": 40_000,
                    "current_to_normal_x": 3.1,
                    "new_session_extreme": True,
                    "top_strike": {"strike": 24600, "new_5m_high": True},
                },
                "PUT": {
                    "current_5m_activity": 20_000,
                    "normal_5m_activity": 30_000,
                    "current_to_normal_x": 0.67,
                    "new_session_extreme": False,
                    "top_strike": {"strike": 24500, "new_5m_high": False},
                }
            }
        }
    })
    all_events = hub.reducer.current_state.active_events + hub.reducer.current_state.memory_events
    assert any(e.family == "sudden_oi" for e in all_events)

    # -------------------------------------------------------------------------
    # 8. Buyers / Writers Dominance (Canonical snapshot)
    # -------------------------------------------------------------------------
    hub.ingest_live_analytics_snapshot({
        "argus": {
            "data": {
                "dominance": {
                    "buyer_dominance_percentage": 50.0,
                    "writer_dominance_percentage": 50.0,
                }
            }
        }
    })
    hub.ingest_live_analytics_snapshot({
        "argus": {
            "data": {
                "dominance": {
                    "buyer_dominance_percentage": 57.0,  # +7pp >= 5pp
                    "writer_dominance_percentage": 43.0,
                }
            }
        }
    })
    all_events = hub.reducer.current_state.active_events + hub.reducer.current_state.memory_events
    assert any(e.family == "dominance" for e in all_events)

    # -------------------------------------------------------------------------
    # 9. Long / Short Buildup (Canonical snapshot)
    # -------------------------------------------------------------------------
    hub.ingest_live_analytics_snapshot({
        "argus": {
            "data": {
                "atm_window": [
                    {"strike": 24500, "ce": {"positioning": "LONG_BUILDUP"}, "pe": {"positioning": "NEUTRAL"}},
                ]
            }
        }
    })
    hub.ingest_live_analytics_snapshot({
        "argus": {
            "data": {
                "atm_window": [
                    {"strike": 24500, "ce": {"positioning": "SHORT_BUILDUP"}, "pe": {"positioning": "NEUTRAL"}},
                ]
            }
        }
    })
    all_events = hub.reducer.current_state.active_events + hub.reducer.current_state.memory_events
    assert any(e.family == "buildup" for e in all_events)

    # -------------------------------------------------------------------------
    # 10. Gamma Blast (Canonical snapshot)
    # -------------------------------------------------------------------------
    hub.ingest_live_analytics_snapshot({
        "argus": {
            "data": {
                "tactical_edge": {
                    "argus_prime": {
                        "expiry_gamma_blast": {
                            "state": "ARMED",
                            "score": 75.0,
                            "direction": "BULLISH",
                        }
                    }
                }
            }
        }
    })
    all_events = hub.reducer.current_state.active_events + hub.reducer.current_state.memory_events
    assert any(e.family == "gamma_blast" for e in all_events)

    # -------------------------------------------------------------------------
    # 11. Max Pain Shift & Mathematical Alignment (MarketInfo REST)
    # -------------------------------------------------------------------------
    hub.ingest_market_info({
        "max_pain": 24500.0,
        "nifty_spot": 24520.0,
    })
    # Max pain moves up to 24550, spot also moves up to 24570 -> ALIGNED
    hub.ingest_market_info({
        "max_pain": 24550.0,
        "nifty_spot": 24570.0,
    })
    all_events = hub.reducer.current_state.active_events + hub.reducer.current_state.memory_events
    mp_ev = next((e for e in all_events if e.family == "max_pain"), None)
    assert mp_ev is not None
    assert mp_ev.archetype == ArchetypeType.LEVEL.value
    assert "ALIGNED" in mp_ev.secondary_value
    assert mp_ev.archetype_data["alignment"] == "ALIGNED"

    # Max pain moves up to 24600, but spot falls to 24530 -> DIVERGING
    hub.ingest_market_info({
        "max_pain": 24600.0,
        "nifty_spot": 24530.0,
    })
    all_events = hub.reducer.current_state.active_events + hub.reducer.current_state.memory_events
    mp_div = next((e for e in all_events if e.family == "max_pain"), None)
    assert mp_div is not None
    assert "DIVERGING" in mp_div.secondary_value
    assert mp_div.archetype_data["alignment"] == "DIVERGING"


def test_counter_bias_buildup_unsuppressed_in_hub():
    """Verifies that counter-bias buildup transitions are emitted even when opposing Spine."""
    registry = LiveIslandRegistry(burst_window_ms=0)
    hub = LiveIslandIntelligenceHub(registry=registry)

    # Set master spine bias to BEAR
    hub.set_spine_bias("bear")

    # Strike 24500 CE transitions to LONG_BUILDUP (bullish counter-bias)
    hub.notify_buildup_update("24500 CE", "SHORT_BUILDUP")
    hub.notify_buildup_update("24500 CE", "LONG_BUILDUP")

    state = hub.reducer.current_state
    buildup_ev = next((e for e in state.active_events if e.family == "buildup"), None)
    assert buildup_ev is not None
    assert buildup_ev.event_bias == EventBias.BULLISH.value
    # The event is NOT suppressed; it is live in active_events with split bias indication
    assert state.spine_bias == "bear"


def test_feed_owner_single_instance_and_clean_teardown():
    """Verifies Upstox V3 single-owner mutex and clean shutdown prevent orphan processes."""
    hub = LiveIslandIntelligenceHub()

    with hub._feed_owner_lock:
        # Mock active feed using SimpleNamespace with _is_running and stop
        hub._feed = types.SimpleNamespace(_is_running=True, stop=lambda: None)

    # Attempting to start feed when one is running should return True without duplicate creation
    reused = hub.start_feed(["NSE_INDEX|Nifty 50"])
    assert reused is True

    # Shutdown clears the feed
    hub.shutdown()
    assert hub._feed is None
    assert hub._is_running is False
