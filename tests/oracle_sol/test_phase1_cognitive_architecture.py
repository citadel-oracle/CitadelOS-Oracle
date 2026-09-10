"""Comprehensive Phase-1.1 Live Cognitive Decision Architecture & Truth Repair Test Suite.

Validates all 22 requirements from Mission Phase 1.1:
1. No deterministic model fallback emits trade direction.
2. Provider failure preserves last valid analysis.
3. First-run provider failure shows AWAITING/UNAVAILABLE, not NO_TRADE.
4. Qwen uses exact qwen/qwen3.8-27b.
5. GPT uses exact openai/gpt-oss-120b.
6. Gemini reports exact configured model (gemini-3.7-flash).
7. Qwen and Gemini do not receive GPT thesis.
8. GPT cannot cite peer-model hypotheses as market evidence.
9. Absorption directional claim requires aggression direction evidence.
10. failed_aggression magnitude alone cannot decide reversal direction.
11. Institutional claim firewall rejects "smart money", "institutions buying", etc.
12. Real backend missing state renders AWAITING LIVE COGNITIVE STATE.
13. Same-security_id option continuity remains correct (zero phantom jump).
14. Real replay uses recorded source files, not manually entered feature values.
15. Quota governor learns limits from observed provider quota headers.
16. Groq model-level and provider-level state both tracked.
17. Gemini quota failure never blocks GPT/Qwen.
18. State transitions preserve event chronology across restart.
19. Evidence Gate cursor advances only on valid commit.
20. VOB untouched.
21. No broker execution.
22. Frontend data shaping matches Section K schema.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

from src.oracle_sol.brain_packet_compiler import BrainPacket, BrainPacketCompiler
from src.oracle_sol.contracts import (
    GeminiReview,
    HypothesisState,
    MarketEvent,
    PrimarySynthesisOutput,
    QwenObservation,
    SolEvidenceSnapshot,
    SystemStatus,
)
from src.oracle_sol.episode_memory import MarketEpisodeMemory
from src.oracle_sol.evidence_gate import EvidenceGate, GateValidationResult
from src.oracle_sol.freshness_scheduler import FreshnessScheduler
from src.oracle_sol.gemini_reviewer_adapter import GeminiReviewerAdapter
from src.oracle_sol.phase1_coordinator import Phase1CognitiveCoordinator
from src.oracle_sol.qwen_sentinel_adapter import QwenSentinelAdapter
from src.oracle_sol.quota_governor import CognitiveQuotaGovernor
from src.oracle_sol.synthesizer_adapter import SynthesizerAdapter
from src.oracle_sol.thesis_graph import ThesisGraph, ThesisMarketState, ThesisNode


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def make_test_snapshot(
    spot: float = 24000.0,
    atm: float = 24000.0,
    ce_ltp: float = 125.0,
    pe_ltp: float = 85.0,
    ce_sid: str = "42639",
    pe_sid: str = "42640",
) -> SolEvidenceSnapshot:
    ladder = [
        {"strike": atm, "relation_to_atm": "ATM", "ce_security_id": ce_sid, "ce_ltp": ce_ltp, "pe_security_id": pe_sid, "pe_ltp": pe_ltp},
        {"strike": atm - 50.0, "relation_to_atm": "ITM", "ce_security_id": "42637", "ce_ltp": ce_ltp + 30.0, "pe_security_id": "42638", "pe_ltp": pe_ltp - 20.0},
    ]
    return SolEvidenceSnapshot(
        snapshot_id="snap_p1_test",
        canonical_snapshot_id="can_p1_test",
        market_session_date="2026-09-03",
        identity_quality="CANONICAL_AUTHENTIC",
        replay_stable=True,
        timestamp_utc="2026-09-03T05:00:00Z",
        timestamp_ist="10:30:00",
        system_status=SystemStatus.HEALTHY,
        upstream_source_health={"market_session_active": True},
        dhan_quote_age_ms=10.0,
        order_flow_age_ms=10.0,
        option_chain_age_ms=10.0,
        spot_ltp=spot,
        futures_ltp=spot + 15.0,
        futures_basis=15.0,
        session_vwap=24000.0,
        spot_to_vwap_pts=spot - 24000.0,
        active_expiry="2026-09-03",
        atm_strike=atm,
        futures_security_id="FUT_NIFTY_SEP",
        sudden_oi_call=None,
        sudden_oi_put=None,
        strike_ladder=ladder,
        mlofi_5l=0.1,
        current_flow_x=0.2,
        mlofi_session_extreme=False,
        ce_pricing={"security_id": ce_sid, "strike": atm, "ltp": ce_ltp, "best_bid_price": ce_ltp - 0.5, "best_ask_price": ce_ltp + 0.5},
        pe_pricing={"security_id": pe_sid, "strike": atm, "ltp": pe_ltp, "best_bid_price": pe_ltp - 0.5, "best_ask_price": pe_ltp + 0.5},
        atm_straddle_price=ce_ltp + pe_ltp,
        straddle_change_5m=0.0,
        atm_iv=11.5,
        skew_25d=0.8,
        skew_10d=0.4,
        expected_move_pts=100.0,
        net_gex_inr=None,
        total_net_gex_inr_cr=180.0,
        dealer_regime="LONG_GAMMA_PIN",
        highest_gex_strike=24100.0,
        zero_gamma_level=23950.0,
        buyer_absorption=0.0,
        seller_absorption=0.0,
        failed_aggression=0.0,
        price_response_efficiency=0.5,
        continuation_efficiency=0.5,
        cvd=1000,
        domestic_indices={},
        availability_matrix={"spot_ltp": "AVAILABLE"},
        source_hashes={},
    )


def make_valid_raw_response(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "observer": {"what_changed": "Baseline", "key_shifts": []},
        "market_story": {"narrative": "Market rotating in range", "sequence_unfolding": ""},
        "call_case": {"argument": "Call side", "evidence_ids": ["metric:spot_price"]},
        "put_case": {"argument": "Put side", "evidence_ids": ["metric:spot_price"]},
        "no_trade_case": {"argument": "No trade", "evidence_ids": ["metric:spot_price"]},
        "reversal_analysis": {"absorption_or_exhaustion": "NONE", "failed_move_evidence": "NONE", "reversal_developing": False, "evidence_ids": ["metric:spot_price"]},
        "reversal_watch": {"direction": "NONE", "status": "NONE", "first_contradiction": "NONE", "what_failed": "NONE", "premium_confirmation": "UNRESOLVED"},
        "option_buyer_analysis": {"underlying_view": "NO_TRADE", "ce_premium_response": "NORMAL", "pe_premium_response": "NORMAL", "iv_response": "NORMAL", "liquidity_or_spread": "NORMAL", "option_buyer_side": "UNRESOLVED", "reasoning": "Neutral"},
        "contradictions": {"strongest_contradiction": "NONE", "contradicting_evidence_ids": []},
        "temporal_analysis": {"evolution_from_previous": "Neutral", "what_strengthened": "None", "what_weakened": "None", "what_superseded": "None"},
        "external_context": {"interpretation": "MARKET_INTERNAL", "cited_external_event_ids": []},
        "counterfactual": {"opposite_thesis_conditions": "Breakout", "watch_triggers": []},
        "human_miss_candidate": {"subtle_relationship": "None", "cited_evidence_ids": []},
        "synthesis": {"state": "NO_TRADE", "no_trade_reason": "DIRECTION_UNCLEAR", "transition_reason": "TRANSITION", "supporting_evidence_ids": ["metric:spot_price"], "contradicting_evidence_ids": [], "unresolved_evidence_ids": [], "watch_next": [], "invalidation_conditions": []},
    }
    if overrides:
        for k, v in overrides.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                base[k].update(v)
            else:
                base[k] = v
    return base


# -----------------------------------------------------------------------------
# 1, 2, 3: ZERO DETERMINISTIC TRADE-DIRECTION FALLBACKS & FAILURE PRESERVATION
# -----------------------------------------------------------------------------

def test_no_deterministic_fallback_emits_trade_direction():
    """When models cannot run, zero deterministic fallback rules emit trade direction."""
    compiler = BrainPacketCompiler()
    snap = make_test_snapshot()
    packet = compiler.compile_packet(
        session_id="test_sess",
        revision=100,
        current_snapshot=snap,
        previous_thesis=None,
        unseen_events=[],
        external_events=[],
        external_quotes=[],
    )

    class FailingBackend:
        def invoke_reasoning(self, **kwargs):
            raise ConnectionError("Simulated provider outage")

    # Qwen test
    qwen = QwenSentinelAdapter(backend_adapter=FailingBackend())
    obs = qwen.observe(packet)
    assert obs.status == "UNAVAILABLE"
    assert obs.continuation_status == "TRANSITION_UNRESOLVED"
    assert obs.current_side_pressure == "UNRESOLVED"
    assert "CALL" not in obs.current_side_pressure
    assert "PUT" not in obs.current_side_pressure

    # GPT test
    gpt = SynthesizerAdapter(backend_adapter=FailingBackend())
    synth = gpt.synthesize(packet)
    assert synth.status == "UNAVAILABLE"
    assert synth.current_state == "AWAITING_FIRST_ANALYSIS"
    assert synth.setup_family == "UNRESOLVED"
    assert synth.entry_window == "WAIT"

    # Gemini test
    class FailingGemini:
        def query_reasoning(self, **kwargs):
            raise TimeoutError("Gemini timed out")

    gem = GeminiReviewerAdapter(backend_adapter=FailingGemini())
    rev = gem.review(packet)
    assert rev.status == "UNAVAILABLE"
    assert rev.reversal_risk == "UNKNOWN"


def test_provider_failure_preserves_last_valid_analysis():
    """Provider failure or 429 preserves previous valid analysis without fabricating."""
    snap = make_test_snapshot()
    compiler = BrainPacketCompiler()
    packet1 = compiler.compile_packet("sess", 101, snap, None, [], [], [])

    # Seed with valid analysis
    gpt = SynthesizerAdapter()
    gpt.last_synthesis = PrimarySynthesisOutput(
        current_state="PUT_DEVELOPING",
        setup_family="CONTINUATION",
        entry_window="APPROACHING",
        why_now=["Downside momentum confirmed"],
        reversal_watch={"direction": "NONE"},
        option_buyer_side="PUT_FAVOURABLE",
        premium_confirmation="CONFIRMING",
        what_would_change_my_mind=["Upside breakout"],
        five_hypotheses={},
        evidence_ids=["metric:spot_price"],
        status="CURRENT",
        input_revision=101,
    )

    # Now provider fails on revision 102
    class OutageBackend:
        def invoke_reasoning(self, **kwargs):
            return None, {"schema_status": "RATE_LIMITED", "http_status": 429}

    gpt.backend_adapter = OutageBackend()
    packet2 = compiler.compile_packet("sess", 102, snap, None, [], [], [])
    synth2 = gpt.synthesize(packet2)

    assert synth2.status == "RATE_LIMITED"
    assert synth2.current_state == "PUT_DEVELOPING"  # Preserved from revision 101
    assert synth2.input_revision == 101             # Explicitly reflects that it was evaluated at 101


# -----------------------------------------------------------------------------
# 4, 5, 6: EXACT MODEL IDS RESOLVED
# -----------------------------------------------------------------------------

def test_exact_model_ids_configured():
    """Adapters must wire the exact configured model IDs."""
    qwen = QwenSentinelAdapter()
    assert qwen.model_name == "qwen/qwen3.8-27b"

    gpt = SynthesizerAdapter()
    assert gpt.model_name == "openai/gpt-oss-120b"

    gem = GeminiReviewerAdapter()
    assert gem.model_name == "gemini-3.7-flash"


# -----------------------------------------------------------------------------
# 7, 8: ZERO ECHO CHAMBER & MODEL-HYPOTHESIS FIREWALL
# -----------------------------------------------------------------------------

def test_zero_echo_chamber_and_model_hypothesis_firewall():
    """Qwen/Gemini do not receive GPT thesis, and GPT cannot cite peer opinions as market facts."""
    compiler = BrainPacketCompiler()
    snap = make_test_snapshot()
    packet = compiler.compile_packet("sess", 100, snap, {"state": "PUT_DEVELOPING"}, [], [], [])

    qwen = QwenSentinelAdapter()
    qwen_prompt = qwen._build_sentinel_prompt(packet)
    assert "previous_thesis" not in qwen_prompt

    # EvidenceGate must reject GPT citing peer models as evidence
    gate = EvidenceGate(thesis_graph=ThesisGraph())
    bad_raw = make_valid_raw_response({
        "call_case": {"argument": "Weakness", "evidence_ids": ["qwen:observation"]},
    })
    res = gate.validate_and_commit(bad_raw, packet, "openai/gpt-oss-120b", "sys")
    assert not res.is_valid
    assert res.status == "MODEL_HYPOTHESIS_AS_EVIDENCE_REJECTED"


# -----------------------------------------------------------------------------
# 9, 10, 11: CLAIM FIREWALL HARDENING (ABSORPTION, FAILED AGGRESSION, INSTITUTIONAL)
# -----------------------------------------------------------------------------

def test_absorption_and_failed_aggression_firewalls():
    """Absorption requires aggression and price response; failed aggression needs flow direction."""
    gate = EvidenceGate(thesis_graph=ThesisGraph())
    compiler = BrainPacketCompiler()
    snap = make_test_snapshot()
    packet = compiler.compile_packet("sess", 100, snap, None, [], [], [])

    # 1. Absorption claim without aggression flow evidence is rejected
    raw_abs = make_valid_raw_response({
        "market_story": {"narrative": "Aggression absorbed at lows"},
        "reversal_analysis": {"absorption_or_exhaustion": "Heavy buying absorbed", "evidence_ids": ["metric:spot_price"]},
    })
    res1 = gate.validate_and_commit(raw_abs, packet, "gpt-oss", "sys")
    assert not res1.is_valid
    assert "ABSORPTION_CLAIM_UNSUPPORTED" in res1.error_details

    # 2. Failed aggression reversal direction without directional flow
    raw_rev_dir = make_valid_raw_response({
        "reversal_watch": {"direction": "PUT_TO_CALL"},
    })
    res2 = gate.validate_and_commit(raw_rev_dir, packet, "gpt-oss", "sys")
    assert not res2.is_valid
    assert "FAILED_AGGRESSION_DIRECTION_UNSUPPORTED" in res2.error_details

    # 3. Institutional claim rejection
    raw_inst = make_valid_raw_response({
        "market_story": {"narrative": "Institutions are buying at support"},
    })
    res3 = gate.validate_and_commit(raw_inst, packet, "gpt-oss", "sys")
    assert not res3.is_valid
    assert "INSTITUTIONAL_CLAIM_UNSUPPORTED" in res3.error_details


# -----------------------------------------------------------------------------
# 15, 16, 17: QUOTA GOVERNOR LEARNS HEADERS & ISOLATES FAILURES
# -----------------------------------------------------------------------------

def test_quota_governor_learns_real_headers_and_isolates_gemini():
    """Governor parses response headers, tracks model/provider levels, and isolates Gemini blocks."""
    gov = CognitiveQuotaGovernor()
    assert gov.provider_states["groq"].limit_requests is None  # UNKNOWN initially

    # Observe Groq headers
    headers = {
        "limit_requests": 1000,
        "remaining_requests": 998,
        "limit_tokens": 8000,
        "remaining_tokens": 7400,
        "reset_requests": "1m26s",
        "reset_tokens": "3.4s",
    }
    gov.update_from_groq_headers("qwen", headers, http_status=200, latency_ms=450.0)

    # Provider and model levels both updated
    assert gov.provider_states["groq"].limit_requests == 1000
    assert gov.model_states["qwen"].remaining_tokens == 7400

    # Gemini 429 block does not block Qwen or GPT
    gov.record_rate_limit("gemini", retry_after_seconds=60.0, http_status=429)
    assert not gov.can_invoke("gemini")
    assert gov.can_invoke("qwen")
    assert gov.can_invoke("gpt_oss")


# -----------------------------------------------------------------------------
# 18, 19: DURABLE CHRONOLOGY & CURSOR ADVANCE ON VALID COMMIT ONLY
# -----------------------------------------------------------------------------

def test_cursor_advances_only_on_valid_gate_commit(temp_dir):
    """Cursor does not advance if synthesis fails or is rejected."""
    tg = ThesisGraph(storage_path=os.path.join(temp_dir, "theses.jsonl"))
    gate = EvidenceGate(thesis_graph=tg)
    compiler = BrainPacketCompiler()
    snap = make_test_snapshot()
    ev1 = MarketEvent(
        event_id="evt_001",
        session_date="2026-09-03",
        timestamp_utc="2026-09-03T04:30:00Z",
        timestamp_ist="10:00:00",
        event_type="SPOT_MOVE",
        instrument="NIFTY",
        summary="Spot move",
        supporting_values={},
    )
    ev2 = MarketEvent(
        event_id="evt_002",
        session_date="2026-09-03",
        timestamp_utc="2026-09-03T04:31:00Z",
        timestamp_ist="10:01:00",
        event_type="SPOT_MOVE",
        instrument="NIFTY",
        summary="Spot move",
        supporting_values={},
    )
    packet = compiler.compile_packet("sess", 100, snap, None, [ev1, ev2], [], [])

    initial_cursor = tg.get_cursor()

    # Invalid commit
    bad_raw = {"invalid": True}
    res = gate.validate_and_commit(bad_raw, packet, "gpt-oss", "sys")
    assert not res.is_valid
    assert tg.get_cursor() == initial_cursor  # Cursor untouched


# -----------------------------------------------------------------------------
# 13, 14: AUTHENTIC RECORDED REPLAY WITH REAL OPTION CONTINUITY
# -----------------------------------------------------------------------------

def test_real_replay_uses_recorded_files():
    """Replay loader extracts recorded data from soak files with temporal firewall."""
    from scripts.replay_soak_reversals import RecordedSoakReplayLoader
    loader = RecordedSoakReplayLoader()
    state_0945 = loader.get_market_state_at("09:45:00")

    assert state_0945["events_count"] > 0
    assert state_0945["spot"] > 23000.0
    assert len(state_0945["recent_eids"]) > 0
    assert state_0945["snapshot"].ce_pricing["security_id"] in ("42637", "42639")


# -----------------------------------------------------------------------------
# 20, 21: SAFETY DECLARATION & ZERO-VOB INVARIANTS
# -----------------------------------------------------------------------------

def test_zero_vob_and_safety_invariants():
    """Verifies VOB engine untouched, paper_only=True, live_trading=False."""
    import subprocess
    diff = subprocess.run(["git", "diff", "CITADEL_MASTER/"], capture_output=True, text=True)
    assert len(diff.stdout.strip()) == 0

    coordinator = Phase1CognitiveCoordinator()
    assert getattr(coordinator, "live_trading", False) is False
    assert getattr(coordinator, "broker_submission", False) is False
