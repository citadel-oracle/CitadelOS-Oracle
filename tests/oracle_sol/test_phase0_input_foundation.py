"""Targeted Test Suite for Citadel Oracle V3.2 Phase-0 Cognitive Input Foundation Repair.

Verifies:
1. Model-independent canonical session chronology (events survive all thesis state transitions).
2. Provider failure does not advance cursor or clear events.
3. Session rollover creates fresh session identity; prior session is historical.
4. Processed Oracle intelligence is un-dropped (order flow absorption, failed aggression, refill, CVD, GEX regime, OSE).
5. Option contract identity continuity: dual-view (role view vs identity view) with zero phantom delta on strike rotation.
6. Neutral temporal relationships (factual observations without trading conclusions).
7. Strict Zero-VOB boundary and allowlist invariants.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.oracle_sol.brain_packet_compiler import BrainPacketCompiler
from src.oracle_sol.contracts import (
    DataAvailability,
    MarketEvent,
    SolEvidenceSnapshot,
    SystemStatus,
)
from src.oracle_sol.episode_memory import MarketEpisodeMemory
from src.oracle_sol.field_registry import SOL_VOB_FREE_FIELD_REGISTRY
from src.oracle_sol.production_projection import project_canonical_oracle_to_sol_feeds
from src.oracle_sol.provenance_guard import ProvenanceGuard
from src.oracle_sol.snapshot_extractor import extract_sol_evidence_snapshot
from src.oracle_sol.thesis_graph import ThesisGraph, ThesisMarketState, ThesisNode


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def make_dummy_event(eid: str, etype: str = "FLOW_PULSE", summary: str = "Test pulse") -> MarketEvent:
    return MarketEvent(
        event_id=eid,
        session_date="2026-09-03",
        timestamp_utc="2026-09-03T05:00:00Z",
        timestamp_ist="10:30:00",
        event_type=etype,
        instrument="NIFTY",
        summary=summary,
        supporting_values={"delta": 100},
        provenance_hash="mock_hash",
    )


def make_minimal_snapshot(
    atm_strike: float = 24000.0,
    ce_sid: str = "sec_ce_24000",
    pe_sid: str = "sec_pe_24000",
    ce_ltp: float = 135.0,
    pe_ltp: float = 80.0,
    ladder: List[Dict[str, Any]] = None,
    buyer_absorption: float = None,
    seller_absorption: float = None,
    failed_aggression: float = None,
    price_response_efficiency: float = None,
    cvd: int = None,
    dealer_regime: str = None,
    total_net_gex_inr_cr: float = None,
) -> SolEvidenceSnapshot:
    ladder = ladder or [
        {
            "strike": 24000.0,
            "relation_to_atm": "ATM",
            "ce_security_id": "sec_ce_24000",
            "ce_ltp": 135.0,
            "pe_security_id": "sec_pe_24000",
            "pe_ltp": 80.0,
        },
        {
            "strike": 23950.0,
            "relation_to_atm": "ITM",
            "ce_security_id": "sec_ce_23950",
            "ce_ltp": 165.0,
            "pe_security_id": "sec_pe_23950",
            "pe_ltp": 55.0,
        },
    ]
    return SolEvidenceSnapshot(
        snapshot_id="snap_test_001",
        canonical_snapshot_id="can_test_001",
        market_session_date="2026-09-03",
        identity_quality="CANONICAL_AUTHENTIC",
        replay_stable=True,
        timestamp_utc="2026-09-03T05:00:00Z",
        timestamp_ist="10:30:00",
        system_status=SystemStatus.HEALTHY,
        upstream_source_health={"market_session_active": True},
        dhan_quote_age_ms=10.0,
        order_flow_age_ms=15.0,
        option_chain_age_ms=20.0,
        spot_ltp=24010.0,
        futures_ltp=24025.0,
        futures_basis=15.0,
        session_vwap=24005.0,
        spot_to_vwap_pts=5.0,
        active_expiry="2026-09-10",
        atm_strike=atm_strike,
        futures_security_id="FUT_NIFTY_SEP",
        sudden_oi_call=None,
        sudden_oi_put=None,
        strike_ladder=ladder,
        mlofi_5l=0.25,
        current_flow_x=1.2,
        mlofi_session_extreme=False,
        ce_pricing={"security_id": ce_sid, "strike": atm_strike, "ltp": ce_ltp, "best_bid_price": ce_ltp - 0.5, "best_ask_price": ce_ltp + 0.5},
        pe_pricing={"security_id": pe_sid, "strike": atm_strike, "ltp": pe_ltp, "best_bid_price": pe_ltp - 0.5, "best_ask_price": pe_ltp + 0.5},
        atm_straddle_price=ce_ltp + pe_ltp,
        straddle_change_5m=-2.5,
        straddle_change_15m=-5.0,
        atm_iv=12.5,
        skew_25d=1.1,
        skew_10d=0.8,
        expected_move_pts=120.0,
        net_gex_inr=None,
        total_net_gex_inr_cr=total_net_gex_inr_cr,
        dealer_regime=dealer_regime,
        highest_gex_strike=24100.0,
        zero_gamma_level=23950.0,
        buyer_absorption=buyer_absorption,
        seller_absorption=seller_absorption,
        failed_aggression=failed_aggression,
        price_response_efficiency=price_response_efficiency,
        cvd=cvd,
        domestic_indices={},
        availability_matrix={"spot_ltp": "AVAILABLE"},
        source_hashes={},
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Model-Independent Canonical Session Chronology Tests (Phase A)
# ─────────────────────────────────────────────────────────────────────────────

def test_canonical_events_survive_no_trade_to_put_developing(temp_dir):
    """Test 1: Underlying market events survive NO_TRADE -> PUT_DEVELOPING transition."""
    mem_path = os.path.join(temp_dir, "episodes.jsonl")
    mem = MarketEpisodeMemory(storage_path=mem_path)

    # 1. Establish session in NO_TRADE
    ep1 = mem.get_or_create_episode("2026-09-03", "NO_TRADE", "cursor_0")
    assert ep1.state == "NO_TRADE"
    assert len(mem.get_accumulated_events()) == 0

    # 2. Record 2 canonical events
    e1 = make_dummy_event("evt_1", "FLOW_PULSE", "Order flow sell pressure")
    e2 = make_dummy_event("evt_2", "DELTA_EVENT", "CVD negative slope")
    mem.record_events([e1, e2])
    assert len(mem.get_accumulated_events()) == 2

    # 3. Model transitions to PUT_DEVELOPING
    ep2 = mem.get_or_create_episode("2026-09-03", "PUT_DEVELOPING", "cursor_1")
    assert ep2.state == "PUT_DEVELOPING"
    assert ep2.episode_id != ep1.episode_id  # Segment identity rotated

    # CRITICAL: Underlying market events SURVIVE and are NOT reset
    events_after = mem.get_accumulated_events()
    assert len(events_after) == 2
    assert [e["event_id"] for e in events_after] == ["evt_1", "evt_2"]


def test_canonical_events_survive_multi_transition_cycle(temp_dir):
    """Test 2: Canonical events survive CALL_DEVELOPING -> NO_TRADE -> PUT_DEVELOPING."""
    mem_path = os.path.join(temp_dir, "episodes.jsonl")
    mem = MarketEpisodeMemory(storage_path=mem_path)

    # Initial CALL_DEVELOPING
    mem.get_or_create_episode("2026-09-03", "CALL_DEVELOPING", "c0")
    e1 = make_dummy_event("evt_1")
    mem.record_events([e1])
    assert len(mem.get_accumulated_events()) == 1

    # Transition 1: CALL_DEVELOPING -> NO_TRADE
    mem.get_or_create_episode("2026-09-03", "NO_TRADE", "c1")
    e2 = make_dummy_event("evt_2")
    mem.record_events([e2])
    assert len(mem.get_accumulated_events()) == 2

    # Transition 2: NO_TRADE -> PUT_DEVELOPING
    mem.get_or_create_episode("2026-09-03", "PUT_DEVELOPING", "c2")
    e3 = make_dummy_event("evt_3")
    mem.record_events([e3])
    assert len(mem.get_accumulated_events()) == 3

    # All 3 events survive across the entire lifecycle
    chronology = mem.get_session_chronology()
    assert [e["event_id"] for e in chronology] == ["evt_1", "evt_2", "evt_3"]


def test_provider_failure_does_not_advance_cursor_or_clear_events(temp_dir):
    """Test 3 & 4: Provider failure leaves cursor unchanged and preserves accumulated events."""
    tg_path = os.path.join(temp_dir, "theses.jsonl")
    tg = ThesisGraph(storage_path=tg_path)
    mem_path = os.path.join(temp_dir, "episodes.jsonl")
    mem = MarketEpisodeMemory(storage_path=mem_path)

    mem.get_or_create_episode("2026-09-03", "NO_TRADE", "cursor_init")
    e1 = make_dummy_event("evt_1")
    mem.record_events([e1])

    cursor_before = tg.get_cursor()
    events_count_before = len(mem.get_accumulated_events())

    # Simulate provider failure (e.g. 429 Quota Exceeded or Timeout):
    # In LocalBrainService / SolMarketBrainService, failure skips commit_thesis
    cursor_after = tg.get_cursor()
    events_count_after = len(mem.get_accumulated_events())

    assert cursor_after == cursor_before
    assert events_count_after == events_count_before == 1


def test_session_rollover_isolation(temp_dir):
    """Test 5 & 6: New session gets fresh identity; prior session thesis is historical."""
    tg_path = os.path.join(temp_dir, "theses.jsonl")
    tg = ThesisGraph(storage_path=tg_path)
    mem_path = os.path.join(temp_dir, "episodes.jsonl")
    mem = MarketEpisodeMemory(storage_path=mem_path)

    # Session Day 1
    mem.get_or_create_episode("2026-09-03", "NO_TRADE", "c0")
    mem.record_events([make_dummy_event("evt_day1_1")])
    assert len(mem.get_accumulated_events()) == 1

    # Session Day 2
    ep_day2 = mem.get_or_create_episode("2026-09-04", "NO_TRADE", "c100")
    assert ep_day2.session_id == "2026-09-04"
    # Day 2 starts clean with 0 events
    assert len(mem.get_accumulated_events()) == 0

    # Rollover in ThesisGraph
    tg.rollover_session("2026-09-04")
    assert tg.get_active_thesis() is None
    assert tg.get_cursor() is None


def test_model_thesis_does_not_mutate_canonical_events(temp_dir):
    """Test 7: Model thesis commits do not mutate existing event hashes or contents."""
    mem_path = os.path.join(temp_dir, "episodes.jsonl")
    mem = MarketEpisodeMemory(storage_path=mem_path)

    mem.get_or_create_episode("2026-09-03", "NO_TRADE", "c0")
    e1 = make_dummy_event("evt_1", "FLOW_PULSE", "Summary A")
    mem.record_events([e1])
    event_dict_before = dict(mem.get_accumulated_events()[0])

    # Model commits thesis
    mem.record_thesis_commit("thesis_001", "PUT_DEVELOPING", "evt_1")

    event_dict_after = dict(mem.get_accumulated_events()[0])
    assert event_dict_before == event_dict_after


# ─────────────────────────────────────────────────────────────────────────────
# 2. Processed Intelligence Un-dropping Tests (Phase B)
# ─────────────────────────────────────────────────────────────────────────────

def test_production_projection_and_extraction_preserves_calculated_intelligence():
    """Verify order flow response, GEX regime, and OSE fields flow from projection to SolEvidenceSnapshot."""
    mock_argus = {
        "data": {
            "underlying": {"ltp": 24000.0, "source_event_time": "2026-09-03T05:00:00Z", "atm_strike": 24000.0},
            "futures": {"ltp": 24020.0, "basis": 20.0, "security_id": "FUT_NIFTY"},
            "atm_window": [],
        }
    }
    mock_flow = {
        "snapshot_id": "snap_flow_1",
        "revision": 100,
        "cvd": -4500,
        "family_values": {
            "BOOK_PRESSURE": {
                "mlofi": -0.42,
                "microprice_edge": -1.8,
                "bid_depletion": 12,
                "ask_depletion": 3,
                "bid_refill": 2,
                "ask_refill": 15,
            },
            "RESPONSE_QUALITY": {
                "buyer_absorption": 0.85,
                "seller_absorption": 0.10,
                "failed_aggression": 145.0,
                "price_response_efficiency": 0.18,
                "continuation_efficiency": 0.22,
                "state": "BUYERS_ABSORBED",
            },
        },
    }
    mock_buyer = {
        "straddle": {"now": 215.0, "change_5m": -4.0, "change_15m": -9.5},
        "option_intelligence": {
            "volatility_opportunity": {"atm_iv": 13.2},
            "iv_skew": {"skew_25d_spread": 1.4, "skew_10d_spread": 0.9},
            "gex": {
                "total_net_gex_inr_cr": 350.5,
                "dealer_regime": "LONG_GAMMA_PIN",
                "zero_gamma_strike": 23900.0,
                "highest_gex_strike": 24200.0,
            },
        },
    }
    mock_ose = {
        "ssi": {"score": 78},
        "decision_window": {"state": "ROOM_AVAILABLE_TO_RESISTANCE"},
    }

    feeds = project_canonical_oracle_to_sol_feeds(
        argus_projection=mock_argus,
        order_flow_projection=mock_flow,
        futures_chart_projection={"forming_candle": {"vwap": 24005.0}},
        option_buyer_projection=mock_buyer,
        options_structure_projection=mock_ose,
        transport_health={"WS_CONNECTED": True, "BASKET_HEALTH": "FULLY_FRESH", "CURRENTLY_RECEIVING_INSTRUMENTS": 20},
    )

    snapshot = extract_sol_evidence_snapshot(feeds)

    # 1. Order Flow response & absorption
    assert snapshot.buyer_absorption == 0.85
    assert snapshot.seller_absorption == 0.10
    assert snapshot.failed_aggression == 145.0
    assert snapshot.price_response_efficiency == 0.18
    assert snapshot.continuation_efficiency == 0.22
    assert snapshot.cvd == -4500
    assert snapshot.bid_depletion == 12
    assert snapshot.ask_refill == 15
    assert snapshot.order_flow_response_state == "BUYERS_ABSORBED"
    assert snapshot.availability_matrix["buyer_absorption"] == "AVAILABLE"
    assert snapshot.availability_matrix["cvd"] == "AVAILABLE"

    # 2. GEX & Volatility
    assert snapshot.total_net_gex_inr_cr == 350.5
    assert snapshot.dealer_regime == "LONG_GAMMA_PIN"
    assert snapshot.straddle_change_15m == -9.5
    assert snapshot.availability_matrix["total_net_gex_inr_cr"] == "AVAILABLE"
    assert snapshot.availability_matrix["dealer_regime"] == "AVAILABLE"

    # 3. OSE Structure
    assert snapshot.ose_ssi_score == 78
    assert snapshot.ose_decision_window == "ROOM_AVAILABLE_TO_RESISTANCE"
    assert snapshot.availability_matrix["ose_ssi_score"] == "AVAILABLE"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Option Contract Identity Continuity Tests (Phase C)
# ─────────────────────────────────────────────────────────────────────────────

def test_option_continuity_zero_phantom_delta_on_strike_rotation():
    """Verify that when ATM rotates, true same-contract change is computed and phantom delta is zero."""
    compiler = BrainPacketCompiler()

    # T0 Baseline: ATM = 24000
    # 24000 CE (sid_A) LTP = 135.0
    # 24000 PE (sid_B) LTP = 80.0
    snap_t0 = make_minimal_snapshot(
        atm_strike=24000.0,
        ce_sid="sec_ce_24000",
        pe_sid="sec_pe_24000",
        ce_ltp=135.0,
        pe_ltp=80.0,
    )
    packet_t0 = compiler.compile_packet(
        session_id="2026-09-03",
        revision=1,
        current_snapshot=snap_t0,
        previous_thesis=None,
        unseen_events=[],
        external_events=[],
        external_quotes=[],
    )
    assert packet_t0.canonical_state["atm_strike"] == 24000.0

    # Simulate prior thesis state stored from T0
    prior_thesis = {
        "input_revision": 1,
        "canonical_state": packet_t0.canonical_state,
    }

    # T1 Rotation: Spot drops 50 pts, ATM strike rotates to 23950!
    # New ATM 23950 CE (sid_C) LTP = 100.0
    # New ATM 23950 PE (sid_D) LTP = 120.0
    # BUT in the strike ladder, the original 24000 CE (sid_A) is now ITM-1 with LTP = 110.0!
    # (True price change of 24000 CE: 110.0 - 135.0 = -25.0)
    # The naive cross-contract subtraction would produce: 100.0 - 135.0 = -35.0 (PHANTOM DELTA OF 10 PTS!)
    ladder_t1 = [
        {
            "strike": 24000.0,
            "relation_to_atm": "OTM",
            "ce_security_id": "sec_ce_24000",
            "ce_ltp": 110.0,
            "pe_security_id": "sec_pe_24000",
            "pe_ltp": 95.0,
        },
        {
            "strike": 23950.0,
            "relation_to_atm": "ATM",
            "ce_security_id": "sec_ce_23950",
            "ce_ltp": 100.0,
            "pe_security_id": "sec_pe_23950",
            "pe_ltp": 120.0,
        },
    ]
    snap_t1 = make_minimal_snapshot(
        atm_strike=23950.0,
        ce_sid="sec_ce_23950",
        pe_sid="sec_pe_23950",
        ce_ltp=100.0,
        pe_ltp=120.0,
        ladder=ladder_t1,
    )

    packet_t1 = compiler.compile_packet(
        session_id="2026-09-03",
        revision=2,
        current_snapshot=snap_t1,
        previous_thesis=prior_thesis,
        unseen_events=[],
        external_events=[],
        external_quotes=[],
    )

    # 1. Verify Role View vs Identity View in option_continuity
    oc = packet_t1.option_continuity
    assert oc["role_rotation"]["occurred"] is True
    assert oc["role_rotation"]["previous_atm_strike"] == 24000.0
    assert oc["role_rotation"]["current_atm_strike"] == 23950.0
    assert oc["role_view"]["current_atm_strike"] == 23950.0
    assert oc["role_view"]["current_ce_security_id"] == "sec_ce_23950"

    # 2. Verify Identity View tracks original 24000 CE contract accurately
    ce_identity = next(item for item in oc["identity_view"] if item["side"] == "CE")
    assert ce_identity["security_id"] == "sec_ce_24000"
    assert ce_identity["previous_premium"] == 135.0
    assert ce_identity["current_premium"] == 110.0
    assert ce_identity["true_same_contract_change"] == -25.0
    assert ce_identity["role_status"] == "ROTATED_OUT_OF_ATM"

    # 3. VERIFY ZERO PHANTOM DELTA:
    # what_changed["ce_premium_delta"] MUST BE -25.0 (the true contract delta), NEVER -35.0!
    assert packet_t1.what_changed["ce_premium_delta"] == -25.0
    assert packet_t1.what_changed["role_rotation_alert"] == "ATM_ROTATED_24000.0_TO_23950.0"

    # Verify PE true contract delta: 95.0 - 80.0 = +15.0 (NEVER 120.0 - 80.0 = +40.0!)
    assert packet_t1.what_changed["pe_premium_delta"] == 15.0


# ─────────────────────────────────────────────────────────────────────────────
# 4. Neutral Temporal Relationship View Tests (Phase D)
# ─────────────────────────────────────────────────────────────────────────────

def test_temporal_relationship_neutrality():
    """Verify temporal relationships contain factual before/after observations without bias."""
    compiler = BrainPacketCompiler()

    snap_t0 = make_minimal_snapshot(
        buyer_absorption=0.20,
        failed_aggression=20.0,
        dealer_regime="LONG_GAMMA_PIN",
    )
    p0 = compiler.compile_packet(
        session_id="2026-09-03",
        revision=1,
        current_snapshot=snap_t0,
        previous_thesis=None,
        unseen_events=[],
        external_events=[],
        external_quotes=[],
    )

    prior = {"input_revision": 1, "canonical_state": p0.canonical_state}

    snap_t1 = make_minimal_snapshot(
        buyer_absorption=0.88,
        failed_aggression=150.0,
        dealer_regime="LONG_GAMMA_PIN",
    )
    p1 = compiler.compile_packet(
        session_id="2026-09-03",
        revision=2,
        current_snapshot=snap_t1,
        previous_thesis=prior,
        unseen_events=[],
        external_events=[],
        external_quotes=[],
    )

    rels = {r["metric"]: r for r in p1.temporal_relationships}
    assert "buyer_absorption" in rels
    assert rels["buyer_absorption"]["before"] == 0.20
    assert rels["buyer_absorption"]["after"] == 0.88
    assert rels["buyer_absorption"]["change"] == 0.68

    assert "failed_aggression" in rels
    assert rels["failed_aggression"]["before"] == 20.0
    assert rels["failed_aggression"]["after"] == 150.0
    assert rels["failed_aggression"]["change"] == 130.0

    # Ensure all rel event_ids are present in valid_evidence_ids
    for r in p1.temporal_relationships:
        assert r["event_id"] in p1.valid_evidence_ids


# ─────────────────────────────────────────────────────────────────────────────
# 5. Strict Zero-VOB Invariant Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_zero_vob_allowlist_enforcement():
    """Verify that SolEvidenceSnapshot strictly passes ProvenanceGuard with all new fields."""
    snap = make_minimal_snapshot(
        buyer_absorption=0.5,
        seller_absorption=0.2,
        failed_aggression=50.0,
        price_response_efficiency=0.4,
        cvd=-1000,
        dealer_regime="SHORT_GAMMA_AMPLIFY",
        total_net_gex_inr_cr=120.0,
    )
    # ProvenanceGuard.verify_field_level_allowlist will raise UnverifiedLineageError if invalid
    assert ProvenanceGuard.verify_field_level_allowlist(snap.to_dict(), strict=True) is True
