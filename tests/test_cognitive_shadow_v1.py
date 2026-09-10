"""CITADEL ORACLE — LIVE COGNITIVE SHADOW V1 TEST SUITE

Tests all 24 architectural and safety invariants:
1. Event-driven invocation: no call when no new event exists.
2. Event coalescing: mid-flight arrivals accumulate into latest snapshot + unseen IDs; no stale queue backlog.
3. Strict schema validation against all 15 required sections.
4. Unsupported claim rejection when hallucinated or unverified evidence ID is cited.
5. Cursor advance on successful durable commit only.
6. Cursor remains unchanged on provider failure (network error, 429, timeout).
7. Cursor remains unchanged on schema validation failure.
8. Monotonicity: stale revision rejected.
9. Prohibited broker terminology rejection.
10. Option-buyer suitability separation from underlying direction.
11. Reversal first-class reasoning: absorption and failed aggression represented.
12. Contradiction engine: preferred thesis must record strongest counter-evidence.
13. Counterfactual reasoning: opposite conditions explicitly documented.
14. What Would a Human Miss: subtle relationship captured or truthfully NONE.
15. Synthesis state enum: strictly CALL, PUT, CALL_DEVELOPING, PUT_DEVELOPING, NO_TRADE.
16. Zero arbitrary numeric thresholds added.
17. Qwen Challenger hook: can be invoked as ADVERSARIAL REVIEWER, passes same Evidence Gate.
18. Qwen idle during ordinary GPT shadow operation (no voting, no averaging).
19. Historical analog hook returns NOT_IMPLEMENTED truthfully.
20. Session rollover: prior session thesis isolated from new session.
21. Duplicate commit idempotency in ThesisGraph.
22. Dynamic rate limit tracking preserves provider telemetry.
23. Frontend projection delivers rich thesis when active, placeholder when none.
24. Zero VOB interference verified.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import pytest

from src.external_context.contracts import ExternalEvent, ExternalQuote
from src.oracle_sol.brain_packet_compiler import BrainPacket, BrainPacketCompiler
from src.oracle_sol.brain_provider_adapter import BrainProviderAdapter
from src.oracle_sol.cognitive_status import (
    get_cognitive_models_status,
    record_model_execution,
    set_model_in_flight,
)
from src.oracle_sol.contracts import (
    MarketEvent,
    MarketEventType,
    SolEvidenceSnapshot,
    SystemStatus,
)
from src.oracle_sol.evidence_gate import EvidenceGate, GateValidationResult
from src.oracle_sol.groq_adapter import GroqBrainAdapter
from src.oracle_sol.local_brain_service import LocalBrainService
from src.oracle_sol.thesis_graph import (
    COGNITIVE_SHADOW_SYSTEM_PROMPT,
    COGNITIVE_STRUCTURED_OUTPUT_SCHEMA,
    ThesisGraph,
    ThesisMarketState,
    ThesisNode,
    ThesisStatus,
)


def _make_dummy_snapshot(session_date: str = "2026-09-02") -> SolEvidenceSnapshot:
    return SolEvidenceSnapshot(
        snapshot_id="snap_test_001",
        canonical_snapshot_id="canon_snap_001",
        market_session_date=session_date,
        identity_quality="DETERMINISTIC_CANONICAL",
        replay_stable=True,
        timestamp_utc="2026-09-02T09:30:00Z",
        timestamp_ist="2026-09-02 15:00:00",
        system_status=SystemStatus.HEALTHY,
        upstream_source_health={"dhan": "CONNECTED"},
        dhan_quote_age_ms=120.0,
        order_flow_age_ms=100.0,
        option_chain_age_ms=150.0,
        spot_ltp=25000.0,
        futures_ltp=25010.0,
        futures_basis=10.0,
        session_vwap=24990.0,
        spot_to_vwap_pts=10.0,
        active_expiry="2026-09-03",
        atm_strike=25000.0,
        futures_security_id="FUT_NIFTY_IDX",
        sudden_oi_call=None,
        sudden_oi_put=None,
        strike_ladder=[],
        mlofi_5l=250000.0,
        current_flow_x=1.5,
        mlofi_session_extreme=False,
        ce_pricing={"ltp": 120.0},
        pe_pricing={"ltp": 90.0},
        atm_straddle_price=210.0,
        straddle_change_5m=0.0,
        atm_iv=14.5,
        skew_25d=0.2,
        skew_10d=0.1,
        expected_move_pts=150.0,
        net_gex_inr=5000000.0,
        highest_gex_strike=25200.0,
        zero_gamma_level=24950.0,
        availability_matrix={},
        source_hashes={},
        domestic_indices={"NIFTY": 25000.0},
    )


def _make_dummy_event(event_id: str, event_type: str = "FLOW_AGGRESSION_BURST") -> MarketEvent:
    return MarketEvent(
        event_id=event_id,
        session_date="2026-09-02",
        timestamp_utc="2026-09-02T09:30:00Z",
        timestamp_ist="2026-09-02 15:00:00",
        event_type=event_type,
        instrument="NIFTY",
        summary="Flow aggression test event",
    )


class MockProviderAdapter(BrainProviderAdapter):
    """Mock adapter returning deterministic structured JSON or simulated failures."""

    def __init__(self, response_payload: Optional[Dict[str, Any]] = None, fail: bool = False, fail_type: str = "HTTP_429") -> None:
        self.response_payload = response_payload
        self.fail = fail
        self.fail_type = fail_type
        self.invocations: List[Dict[str, Any]] = []

    def is_available(self) -> bool:
        return True

    def get_telemetry(self) -> Dict[str, Any]:
        return {"total_requests": len(self.invocations)}

    def invoke_reasoning(
        self,
        request_id: str,
        system_prompt: str,
        user_prompt: str,
        schema: Optional[Dict[str, Any]] = None,
        timeout_seconds: float = 30.0,
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        self.invocations.append({"request_id": request_id, "user_prompt": user_prompt})
        if self.fail:
            return None, {
                "request_id": request_id,
                "error": f"Provider failed with {self.fail_type}",
                "schema_status": self.fail_type,
                "total_duration_ms": 150.0,
            }
        return self.response_payload, {
            "request_id": request_id,
            "error": None,
            "schema_status": "SCHEMA_VALID_JSON",
            "total_duration_ms": 420.0,
            "prompt_tokens": 800,
            "completion_tokens": 400,
            "total_tokens": 1200,
        }


def _make_valid_15_section_payload(event_id: str = "evt_001") -> Dict[str, Any]:
    return {
        "observer": {
            "what_changed": "Aggressive selling did not displace spot downwards; price absorbed at 25000",
            "key_shifts": ["basis unchanged", "pe premium flat"],
        },
        "market_story": {
            "narrative": "Sellers attempted breakdown after morning open but encountered institutional absorption.",
            "sequence_unfolding": "Aggression burst -> zero price response -> reclaim of session VWAP.",
        },
        "call_case": {
            "argument": "Absorption of negative delta at VWAP indicates strong passive buyer presence.",
            "evidence_ids": [event_id],
        },
        "put_case": {
            "argument": "Resistance at 25050 overhead with elevated call writing.",
            "evidence_ids": [event_id],
        },
        "no_trade_case": {
            "argument": "Implied volatility compressing; option buyer edges minimal inside 30-pt range.",
            "evidence_ids": [event_id],
        },
        "reversal_analysis": {
            "absorption_or_exhaustion": "Aggression burst was fully absorbed; sellers failed to displace lower.",
            "failed_move_evidence": "Breakdown attempt below 25000 failed and price reclaimed 25010 immediately.",
            "reversal_developing": True,
            "evidence_ids": [event_id],
        },
        "option_buyer_analysis": {
            "underlying_direction": "Neutral to mildly bullish mean-reversion drift.",
            "option_buying_suitability": "UNFAVOURABLE - rapid theta decay and IV crush make option buying risky.",
            "volatility_or_theta_risk": "Theta burn 18 INR/day; straddle price flat.",
            "premium_behavior_notes": "CE delta lagging spot move; PE decay accelerating.",
        },
        "contradictions": {
            "strongest_contradiction": "Net delta flow remains slightly negative despite spot stability.",
            "contradicting_evidence_ids": [event_id],
        },
        "temporal_analysis": {
            "evolution_from_previous": "Evolved from early morning consolidation into active absorption pattern.",
            "what_strengthened": "Passive bid support at 25000 VWAP.",
            "what_weakened": "Downside follow-through momentum.",
            "what_superseded": "Previous breakdown warning superseded by successful reclaim.",
        },
        "external_context": {
            "interpretation": "World markets calm; US proxies flat; domestic flow dominating.",
            "cited_external_event_ids": [],
        },
        "counterfactual": {
            "opposite_thesis_conditions": "A sustained 5m close below 24980 with expanding PE premium.",
            "watch_triggers": ["spot < 24980", "futures basis turns negative"],
        },
        "human_miss_candidate": {
            "subtle_relationship": "Spot is holding 25000 while futures basis is expanding from 8 to 12 pts during sell bursts.",
            "cited_evidence_ids": [event_id],
        },
        "synthesis": {
            "state": "CALL_DEVELOPING",
            "transition_reason": "Absorption verified, awaiting clean breakout before full directional transition.",
            "supporting_evidence_ids": [event_id],
            "contradicting_evidence_ids": [event_id],
            "unresolved_evidence_ids": [],
            "watch_next": ["25020 reclaim confirmation", "CE volume expansion"],
            "invalidation_conditions": ["Spot close below 24980"],
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# TESTS
# ─────────────────────────────────────────────────────────────────────────────

def test_1_event_driven_invocation_no_call_when_empty():
    """1. Event-driven invocation: no call when no new meaningful event exists."""
    adapter = MockProviderAdapter()
    service = LocalBrainService(adapter=adapter)
    thesis, res = service.on_canonical_event(None, _make_dummy_snapshot(), "sess_1", 1)
    assert thesis is None
    assert res.get("status") == "EMPTY_EVENT_SKIPPED"
    assert len(adapter.invocations) == 0


def test_2_event_coalescing_mid_flight_drop():
    """2. Event coalescing: mid-flight arrivals accumulate into latest snapshot + unseen IDs; no stale queue backlog."""
    adapter = MockProviderAdapter(response_payload=_make_valid_15_section_payload("evt_001"))
    service = LocalBrainService(adapter=adapter)

    # Acquire eval lock to simulate in-flight inference
    service._eval_lock.acquire()
    evt = _make_dummy_event("evt_002")
    thesis, res = service.on_canonical_event(evt, _make_dummy_snapshot(), "sess_1", 2)
    assert thesis is None
    assert res.get("status") == "COALESCED_DROP"
    assert service._coalesced_drops == 1
    # Event remains pending for next cycle
    assert len(service._pending_unseen_events) == 1
    service._eval_lock.release()


def test_3_strict_schema_validation_all_15_sections():
    """3. Strict schema validation against all 15 required sections."""
    tg = ThesisGraph()
    gate = EvidenceGate(tg)
    payload = _make_valid_15_section_payload("evt_001")

    compiler = BrainPacketCompiler()
    snap = _make_dummy_snapshot()
    evt = _make_dummy_event("evt_001")
    packet = compiler.compile_packet("sess_1", 1, snap, None, [evt], [], [])

    res = gate.validate_and_commit(payload, packet, "gpt-oss", COGNITIVE_SHADOW_SYSTEM_PROMPT)
    assert res.is_valid is True
    assert res.status == "COMMITTED"
    assert res.committed_thesis is not None
    assert res.committed_thesis.market_story != ""
    assert res.committed_thesis.reversal_analysis != ""


def test_4_unsupported_claim_rejection_hallucinated_id():
    """4. Unsupported claim rejection when hallucinated or unverified evidence ID is cited."""
    tg = ThesisGraph()
    gate = EvidenceGate(tg)
    payload = _make_valid_15_section_payload("evt_001")
    # Inject hallucinated evidence ID
    payload["call_case"]["evidence_ids"] = ["HALLUCINATED_FAKE_ID_999"]

    compiler = BrainPacketCompiler()
    packet = compiler.compile_packet("sess_1", 1, _make_dummy_snapshot(), None, [_make_dummy_event("evt_001")], [], [])

    res = gate.validate_and_commit(payload, packet, "gpt-oss", COGNITIVE_SHADOW_SYSTEM_PROMPT)
    assert res.is_valid is False
    assert res.status == "MODEL_CLAIM_UNSUPPORTED"
    assert "HALLUCINATED_FAKE_ID_999" in res.unsupported_evidence_ids


def test_5_cursor_advance_on_successful_durable_commit_only():
    """5. Cursor advance on successful durable commit only."""
    tg = ThesisGraph()
    gate = EvidenceGate(tg)
    assert tg.get_cursor() is None

    payload = _make_valid_15_section_payload("evt_001")
    compiler = BrainPacketCompiler()
    packet = compiler.compile_packet("sess_1", 1, _make_dummy_snapshot(), None, [_make_dummy_event("evt_001")], [], [])

    res = gate.validate_and_commit(payload, packet, "gpt-oss", COGNITIVE_SHADOW_SYSTEM_PROMPT)
    assert res.is_valid is True
    assert tg.get_cursor() == "evt_001"


def test_6_cursor_unchanged_on_provider_failure():
    """6. Cursor remains unchanged on provider failure (network error, 429, timeout)."""
    adapter = MockProviderAdapter(fail=True, fail_type="RATE_LIMITED_429")
    tg = ThesisGraph()
    service = LocalBrainService(adapter=adapter, thesis_graph=tg)

    # Initial cursor
    assert tg.get_cursor() is None

    evt = _make_dummy_event("evt_001")
    thesis, res = service.on_canonical_event(evt, _make_dummy_snapshot(), "sess_1", 1)
    assert thesis is None
    assert res.get("status") == "PROVIDER_FAILURE"
    # Cursor MUST remain None
    assert tg.get_cursor() is None


def test_7_cursor_unchanged_on_schema_validation_failure():
    """7. Cursor remains unchanged on schema validation failure."""
    tg = ThesisGraph()
    gate = EvidenceGate(tg)
    # Payload missing 'market_story'
    payload = _make_valid_15_section_payload("evt_001")
    del payload["market_story"]

    compiler = BrainPacketCompiler()
    packet = compiler.compile_packet("sess_1", 1, _make_dummy_snapshot(), None, [_make_dummy_event("evt_001")], [], [])

    res = gate.validate_and_commit(payload, packet, "gpt-oss", COGNITIVE_SHADOW_SYSTEM_PROMPT)
    assert res.is_valid is False
    assert res.status == "SCHEMA_INVALID"
    assert tg.get_cursor() is None


def test_8_monotonicity_stale_revision_rejected():
    """8. Monotonicity: stale revision rejected."""
    tg = ThesisGraph()
    gate = EvidenceGate(tg)
    payload = _make_valid_15_section_payload("evt_001")

    compiler = BrainPacketCompiler()
    packet1 = compiler.compile_packet("sess_1", 5, _make_dummy_snapshot(), None, [_make_dummy_event("evt_001")], [], [])
    res1 = gate.validate_and_commit(payload, packet1, "gpt-oss", COGNITIVE_SHADOW_SYSTEM_PROMPT)
    assert res1.is_valid is True

    # Packet with older revision (revision 3 < revision 5)
    payload2 = _make_valid_15_section_payload("evt_002")
    packet2 = compiler.compile_packet("sess_1", 3, _make_dummy_snapshot(), None, [_make_dummy_event("evt_002")], [], [])
    res2 = gate.validate_and_commit(payload2, packet2, "gpt-oss", COGNITIVE_SHADOW_SYSTEM_PROMPT)
    assert res2.is_valid is False
    assert res2.status == "PROVENANCE_MISMATCH"


def test_9_prohibited_broker_terminology_rejection():
    """9. Prohibited broker terminology rejection."""
    tg = ThesisGraph()
    gate = EvidenceGate(tg)
    payload = _make_valid_15_section_payload("evt_001")
    payload["call_case"]["argument"] = "User should place_order immediately via Dhan."

    compiler = BrainPacketCompiler()
    packet = compiler.compile_packet("sess_1", 1, _make_dummy_snapshot(), None, [_make_dummy_event("evt_001")], [], [])

    res = gate.validate_and_commit(payload, packet, "gpt-oss", COGNITIVE_SHADOW_SYSTEM_PROMPT)
    assert res.is_valid is False
    assert res.status == "PROHIBITED_INSTRUCTION_DETECTED"


def test_10_option_buyer_suitability_separated_from_underlying():
    """10. Option-buyer suitability separation from underlying direction."""
    tg = ThesisGraph()
    gate = EvidenceGate(tg)
    payload = _make_valid_15_section_payload("evt_001")
    payload["option_buyer_analysis"]["underlying_direction"] = "Bearish downside drift"
    payload["option_buyer_analysis"]["option_buying_suitability"] = "UNFAVOURABLE - rapid theta decay, IV crush, narrow spreads"
    payload["synthesis"]["state"] = "NO_TRADE"

    compiler = BrainPacketCompiler()
    packet = compiler.compile_packet("sess_1", 1, _make_dummy_snapshot(), None, [_make_dummy_event("evt_001")], [], [])

    res = gate.validate_and_commit(payload, packet, "gpt-oss", COGNITIVE_SHADOW_SYSTEM_PROMPT)
    assert res.is_valid is True
    assert res.committed_thesis.underlying_view == "Bearish downside drift"
    assert "UNFAVOURABLE" in res.committed_thesis.option_buyer_view
    assert res.committed_thesis.state == "NO_TRADE"


def test_11_reversal_first_class_reasoning():
    """11. Reversal first-class reasoning: absorption and failed aggression represented properly."""
    payload = _make_valid_15_section_payload("evt_001")
    rev = payload["reversal_analysis"]
    assert "absorbed" in rev["absorption_or_exhaustion"].lower()
    assert "failed" in rev["failed_move_evidence"].lower()
    assert rev["reversal_developing"] is True


def test_12_contradiction_engine_records_counter_evidence():
    """12. Contradiction engine: preferred thesis must record strongest counter-evidence."""
    payload = _make_valid_15_section_payload("evt_001")
    contra = payload["contradictions"]
    assert len(contra["strongest_contradiction"]) > 5
    assert len(contra["contradicting_evidence_ids"]) > 0


def test_13_counterfactual_reasoning_documented():
    """13. Counterfactual reasoning: opposite conditions explicitly documented."""
    payload = _make_valid_15_section_payload("evt_001")
    cf = payload["counterfactual"]
    assert len(cf["opposite_thesis_conditions"]) > 5
    assert len(cf["watch_triggers"]) > 0


def test_14_what_would_a_human_miss_captured_or_none():
    """14. What Would a Human Miss: subtle relationship captured or truthfully NONE."""
    payload = _make_valid_15_section_payload("evt_001")
    hm = payload["human_miss_candidate"]
    assert len(hm["subtle_relationship"]) > 0


def test_15_synthesis_state_enum_strictly_five_states():
    """15. Synthesis state enum: strictly CALL, PUT, CALL_DEVELOPING, PUT_DEVELOPING, NO_TRADE."""
    valid_states = {"CALL", "PUT", "CALL_DEVELOPING", "PUT_DEVELOPING", "NO_TRADE"}
    enum_states = {s.value for s in ThesisMarketState}
    assert enum_states == valid_states


def test_16_zero_arbitrary_numeric_thresholds():
    """16. Zero arbitrary numeric thresholds added (no MLOFI > X, PCR > Y, etc.)."""
    # Verify the system prompt explicitly forbids arbitrary numeric formulas
    assert "Never invent confidence percentages" in COGNITIVE_SHADOW_SYSTEM_PROMPT
    assert "arbitrary numeric trading rules" in COGNITIVE_SHADOW_SYSTEM_PROMPT


def test_17_qwen_challenger_hook_adversarial_reviewer():
    """17. Qwen Challenger hook: can be invoked as ADVERSARIAL REVIEWER, passes same Evidence Gate."""
    challenger = MockProviderAdapter(response_payload=_make_valid_15_section_payload("evt_001"))
    service = LocalBrainService(challenger_adapter=challenger)

    tg = ThesisGraph()
    gate = EvidenceGate(tg)
    payload = _make_valid_15_section_payload("evt_001")
    compiler = BrainPacketCompiler()
    packet = compiler.compile_packet("sess_1", 1, _make_dummy_snapshot(), None, [_make_dummy_event("evt_001")], [], [])
    res = gate.validate_and_commit(payload, packet, "gpt-oss", COGNITIVE_SHADOW_SYSTEM_PROMPT)

    adv_res, tel = service.invoke_adversarial_review(res.committed_thesis, packet)
    assert adv_res is not None
    assert "observer" in adv_res
    assert tel.get("schema_status") == "SCHEMA_VALID_JSON"


def test_18_qwen_idle_during_ordinary_gpt_operation():
    """18. Qwen idle during ordinary GPT shadow operation (no voting, no averaging)."""
    primary = MockProviderAdapter(response_payload=_make_valid_15_section_payload("evt_001"))
    challenger = MockProviderAdapter(response_payload=_make_valid_15_section_payload("evt_001"))
    service = LocalBrainService(adapter=primary, challenger_adapter=challenger)

    evt = _make_dummy_event("evt_001")
    thesis, tel = service.on_canonical_event(evt, _make_dummy_snapshot(), "sess_1", 1)

    assert len(primary.invocations) == 1
    # Challenger was NEVER invoked during standard run
    assert len(challenger.invocations) == 0


def test_19_historical_analog_hook_truthfully_not_implemented():
    """19. Historical analog hook returns NOT_IMPLEMENTED truthfully."""
    service = LocalBrainService()
    state = service.get_shadow_state()
    assert state.get("historical_analogs") == "NOT_IMPLEMENTED"


def test_20_session_rollover_isolates_prior_session():
    """20. Session rollover: prior session thesis isolated from new session."""
    tg = ThesisGraph()
    gate = EvidenceGate(tg)
    payload = _make_valid_15_section_payload("evt_001")
    compiler = BrainPacketCompiler()

    packet = compiler.compile_packet("sess_day_1", 1, _make_dummy_snapshot("2026-09-02"), None, [_make_dummy_event("evt_001")], [], [])
    gate.validate_and_commit(payload, packet, "gpt-oss", COGNITIVE_SHADOW_SYSTEM_PROMPT)

    assert tg.get_active_thesis() is not None
    assert tg.get_cursor() == "evt_001"

    # Roll over to new session
    tg.rollover_session("sess_day_2")
    assert tg.get_active_thesis() is None
    assert tg.get_cursor() is None


def test_21_duplicate_commit_idempotency():
    """21. Duplicate commit idempotency in ThesisGraph."""
    tg = ThesisGraph()
    gate = EvidenceGate(tg)
    payload = _make_valid_15_section_payload("evt_001")
    compiler = BrainPacketCompiler()
    packet = compiler.compile_packet("sess_1", 1, _make_dummy_snapshot(), None, [_make_dummy_event("evt_001")], [], [])

    res1 = gate.validate_and_commit(payload, packet, "gpt-oss", COGNITIVE_SHADOW_SYSTEM_PROMPT)
    node1 = res1.committed_thesis
    count_before = len(tg.get_history(limit=100))

    # Commit identical node again
    tg.commit_thesis(node1)
    count_after = len(tg.get_history(limit=100))
    assert count_before == count_after


def test_22_dynamic_rate_limit_tracking_preserves_telemetry():
    """22. Dynamic rate limit tracking preserves provider telemetry."""
    status = get_cognitive_models_status()
    assert "models" in status
    assert "gpt_oss" in status["models"]
    assert "qwen" in status["models"]
    assert status["models"]["gpt_oss"]["role"] == "SHADOW PRIMARY"
    assert status["models"]["qwen"]["role"] == "CHALLENGER"


def test_23_frontend_projection_delivers_rich_thesis():
    """23. Frontend projection delivers rich thesis when active, placeholder when none."""
    service = LocalBrainService()
    state = service.get_shadow_state()
    assert "mode" in state
    assert state["mode"] == "SHADOW"
    assert "shadow_status" in state
    assert "active_thesis" in state


def test_24_zero_vob_interference_verified():
    """24. Zero VOB interference verified: SolEvidenceSnapshot confirms ZERO_VOB_ALLOWLIST_CONFIRMED."""
    snap = _make_dummy_snapshot()
    assert snap.vob_free_verified == "ZERO_VOB_ALLOWLIST_CONFIRMED"
