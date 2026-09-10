"""Phase 1.3 Semantic Truth Firewall & Grounding Tests.

Verifies:
1. Call OI increase alone cannot support CALL direction.
2. Put OI increase alone cannot support PUT direction.
3. OI + price/premium corroboration can be described as inference when supported.
4. Positive net GEX cannot be called "net call gamma" without call-side decomposition.
5. Positive GEX alone cannot support CALL direction.
6. Negative GEX alone cannot support PUT direction.
7. Numeric absorption value cannot be labeled HIGH/LOW unless producer exposes that label.
8. NIFTY futures absorption cannot be described as CALL-side or PUT-side absorption.
9. Failed aggression direction requires actual aggression direction.
10. Institutional attribution remains prohibited.
11. Every WHY_NOW directional statement resolves canonical evidence.
12. READY requires grounded NOW reasoning.
13. Invalid semantic output does not advance ThesisGraph cursor.
14. Qwen/GPT provider failure preserves last valid result.
15. VOB unchanged.
16. Broker execution disabled.
"""

import json
import subprocess
from datetime import datetime, timezone
import pytest

from src.oracle_sol.brain_packet_compiler import BrainPacket, BrainPacketCompiler
from src.oracle_sol.evidence_gate import EvidenceGate
from src.oracle_sol.thesis_graph import ThesisGraph, ThesisMarketState
from src.oracle_sol.contracts import SolEvidenceSnapshot, PrimarySynthesisOutput, QwenObservation
from src.oracle_sol.synthesizer_adapter import SynthesizerAdapter
from src.oracle_sol.qwen_sentinel_adapter import QwenSentinelAdapter


@pytest.fixture
def base_packet():
    return BrainPacket(
        packet_id="pkt_test_phase1_3",
        session_id="2026-09-03",
        revision=100,
        compiled_at="2026-09-03T10:00:00Z",
        canonical_state={
            "spot_price": 24000.0,
            "futures_price": 24020.0,
            "basis": 20.0,
            "atm_strike": 24000.0,
            "ce_atm_premium": 120.0,
            "pe_atm_premium": 95.0,
            "total_net_gex_inr_cr": 95.5,
            "dealer_regime": "LONG_GAMMA_PIN",
            "seller_absorption": 0.3028,
            "buyer_absorption": 0.0,
            "order_flow_response_state": "MIXED",
            "failed_aggression": 0.3028,
            "flow_net_delta": 0.05,
            "flow_aggression": 1.1,
            "call_oi_build": {"status": "LIVE", "side": "CE", "current_to_normal_x": 2.0},
            "put_oi_build": {"status": "QUIET", "side": "PE", "current_to_normal_x": 0.2},
        },
        what_changed=[],
        unseen_event_ids=[],
        unseen_events_summary=[],
        previous_thesis=None,
        verified_external_events=[],
        external_quotes=[],
        valid_evidence_ids=[
            "metric:spot_price",
            "metric:futures_price",
            "metric:basis",
            "metric:atm_strike",
            "metric:ce_atm_premium",
            "metric:pe_atm_premium",
            "metric:total_net_gex_inr_cr",
            "metric:dealer_regime",
            "metric:seller_absorption",
            "metric:buyer_absorption",
            "metric:failed_aggression",
            "metric:flow_net_delta",
            "metric:flow_aggression",
            "metric:call_oi_build",
            "metric:put_oi_build",
        ],
        canonical_levels=[24000.0, 24050.0, 23950.0],
        evidence_registry={},
    )


@pytest.fixture
def gate():
    graph = ThesisGraph()
    return EvidenceGate(graph)


def make_valid_response(state="CALL_DEVELOPING"):
    return {
        "observer": {"what_changed": "Spot test"},
        "market_story": "Spot held firm with passive bid absorption.",
        "call_case": {
            "argument": "Call side supported by underlying spot progress and premium response.",
            "evidence_ids": ["metric:spot_price", "metric:ce_atm_premium"],
        },
        "put_case": {
            "argument": "Put side lacks progress.",
            "evidence_ids": ["metric:pe_atm_premium"],
        },
        "no_trade_case": {"argument": "Range remains active."},
        "reversal_analysis": {"argument": "No reversal detected."},
        "reversal_watch": {
            "direction": "NONE",
            "failed_move": "NOT_DETECTED",
            "evidence_ids": ["metric:flow_net_delta"],
        },
        "option_buyer_analysis": {
            "option_buyer_side": "CALL_FAVOURABLE",
            "evidence_ids": ["metric:ce_atm_premium"],
        },
        "contradictions": {"argument": "Basis slightly high."},
        "temporal_analysis": {"argument": "Past 15m bullish."},
        "external_context": {"argument": "No shocks."},
        "counterfactual": "Break below 23950 invalidates.",
        "human_miss_candidate": "None.",
        "synthesis": {
            "state": state,
            "setup_family": "CONTINUATION",
            "supporting_evidence_ids": ["metric:spot_price"],
            "contradicting_evidence_ids": [],
            "watch_next": ["24050.0"],
            "invalidation_conditions": ["Break below 23950.0"],
        },
        "entry_window": "APPROACHING",
        "why_now": [
            "Spot advanced +20 pts while CE premium expanded (metric:spot_price, metric:ce_atm_premium)",
            "Passive bid refill absorbed sellers in NIFTY futures (metric:seller_absorption, metric:flow_net_delta)",
        ],
        "what_would_change_my_mind": ["Break below 23950.0 (metric:spot_price)"],
    }


def test_01_call_oi_increase_alone_cannot_support_call(gate, base_packet):
    raw = make_valid_response("CALL_DEVELOPING")
    raw["call_case"]["evidence_ids"] = ["metric:call_oi_build"]
    raw["call_case"]["argument"] = "Call OI build confirms call buying."
    raw["why_now"] = ["Call OI build is bullish and supports CALL (metric:call_oi_build)"]
    
    result = gate.validate_and_commit(raw, base_packet, "test-model", "test-prompt")
    assert not result.is_valid
    assert "OI_DIRECTIONAL_INFERENCE_UNSUPPORTED" in (result.error_details or "")


def test_02_put_oi_increase_alone_cannot_support_put(gate, base_packet):
    raw = make_valid_response("PUT_DEVELOPING")
    raw["put_case"]["evidence_ids"] = ["metric:put_oi_build"]
    raw["put_case"]["argument"] = "Put OI build confirms put buying."
    raw["why_now"] = ["Put OI build is bearish and supports PUT (metric:put_oi_build)"]
    
    result = gate.validate_and_commit(raw, base_packet, "test-model", "test-prompt")
    assert not result.is_valid
    assert "OI_DIRECTIONAL_INFERENCE_UNSUPPORTED" in (result.error_details or "")


def test_03_oi_with_corroboration_passes(gate, base_packet):
    raw = make_valid_response("CALL_DEVELOPING")
    raw["call_case"]["evidence_ids"] = ["metric:call_oi_build", "metric:spot_price", "metric:ce_atm_premium"]
    raw["call_case"]["argument"] = "Call OI increased while spot advanced and CE premium rose; consistent with call positioning."
    raw["why_now"] = [
        "Spot advanced while CE premium expanded (metric:spot_price, metric:ce_atm_premium)",
        "Call OI increased alongside spot rise, consistent with call demand (metric:call_oi_build, metric:spot_price)",
    ]
    result = gate.validate_and_commit(raw, base_packet, "test-model", "test-prompt")
    assert result.is_valid, result.error_details


def test_04_positive_gex_cannot_be_called_net_call_gamma(gate, base_packet):
    raw = make_valid_response("CALL_DEVELOPING")
    raw["why_now"] = ["Total net GEX is positive, indicating net call gamma (metric:total_net_gex_inr_cr)"]
    result = gate.validate_and_commit(raw, base_packet, "test-model", "test-prompt")
    assert not result.is_valid
    assert "GEX_CALL_GAMMA_MISLABEL" in (result.error_details or "")


def test_05_positive_gex_alone_cannot_support_call(gate, base_packet):
    raw = make_valid_response("CALL")
    raw["call_case"]["evidence_ids"] = ["metric:total_net_gex_inr_cr"]
    raw["call_case"]["argument"] = "Positive GEX supports call direction."
    result = gate.validate_and_commit(raw, base_packet, "test-model", "test-prompt")
    assert not result.is_valid
    assert "GEX_DIRECTIONAL_INFERENCE_UNSUPPORTED" in (result.error_details or "")


def test_06_negative_gex_alone_cannot_support_put(gate, base_packet):
    raw = make_valid_response("PUT")
    raw["put_case"]["evidence_ids"] = ["metric:total_net_gex_inr_cr"]
    raw["put_case"]["argument"] = "Negative GEX supports put direction."
    result = gate.validate_and_commit(raw, base_packet, "test-model", "test-prompt")
    assert not result.is_valid
    assert "GEX_DIRECTIONAL_INFERENCE_UNSUPPORTED" in (result.error_details or "")


def test_07_numeric_absorption_cannot_be_labeled_high_without_producer_bucket(gate, base_packet):
    raw = make_valid_response("CALL_DEVELOPING")
    raw["why_now"] = ["Seller absorption is high (0.3028) in the order flow (metric:seller_absorption)"]
    result = gate.validate_and_commit(raw, base_packet, "test-model", "test-prompt")
    assert not result.is_valid
    assert "ABSORPTION_QUALITATIVE_INVENTION" in (result.error_details or "")


def test_08_nifty_futures_absorption_cannot_be_misattributed_to_option_side(gate, base_packet):
    raw = make_valid_response("CALL_DEVELOPING")
    raw["why_now"] = ["Absorption on the call side was observed (metric:seller_absorption)"]
    result = gate.validate_and_commit(raw, base_packet, "test-model", "test-prompt")
    assert not result.is_valid
    assert "UNDERLYING_FLOW_MISATTRIBUTED_TO_OPTION_SIDE" in (result.error_details or "")

    raw2 = make_valid_response("CALL_DEVELOPING")
    raw2["market_story"] = "Sellers taking aggression on the call side."
    result2 = gate.validate_and_commit(raw2, base_packet, "test-model", "test-prompt")
    assert not result2.is_valid
    assert "UNDERLYING_FLOW_MISATTRIBUTED_TO_OPTION_SIDE" in (result2.error_details or "")


def test_09_failed_aggression_direction_requires_actual_flow_evidence(gate, base_packet):
    raw = make_valid_response("CALL_DEVELOPING")
    raw["market_story"] = "Spot held firm with buyers active."
    raw["reversal_watch"] = {"direction": "PUT_TO_CALL", "evidence_ids": ["metric:spot_price"]}
    result = gate.validate_and_commit(raw, base_packet, "test-model", "test-prompt")
    assert not result.is_valid
    assert "FAILED_AGGRESSION_DIRECTION_UNSUPPORTED" in (result.error_details or "")


def test_10_institutional_attribution_prohibited(gate, base_packet):
    raw = make_valid_response("CALL_DEVELOPING")
    raw["market_story"] = "Institutions are buying at 24000."
    result = gate.validate_and_commit(raw, base_packet, "test-model", "test-prompt")
    assert not result.is_valid
    assert "INSTITUTIONAL_CLAIM_UNSUPPORTED" in (result.error_details or "")


def test_11_why_now_must_resolve_canonical_evidence(gate, base_packet):
    raw = make_valid_response("CALL_DEVELOPING")
    raw["why_now"] = ["Spot is moving higher without any evidence cited"]
    result = gate.validate_and_commit(raw, base_packet, "test-model", "test-prompt")
    assert not result.is_valid
    assert "WHY_NOW_EVIDENCE_UNRESOLVED" in (result.error_details or "")


def test_12_ready_requires_grounded_now_reasoning(gate, base_packet):
    raw = make_valid_response("CALL")
    raw["entry_window"] = "READY"
    raw["what_would_change_my_mind"] = []
    raw["synthesis"]["invalidation_conditions"] = []
    result = gate.validate_and_commit(raw, base_packet, "test-model", "test-prompt")
    assert not result.is_valid
    assert "ENTRY_WINDOW_UNGROUNDED" in (result.error_details or "")


def test_13_invalid_semantic_output_does_not_advance_cursor(gate, base_packet):
    initial_cursor = gate.thesis_graph.get_cursor()
    raw = make_valid_response("CALL_DEVELOPING")
    raw["why_now"] = ["Call absorption on the call side (metric:seller_absorption)"]
    result = gate.validate_and_commit(raw, base_packet, "test-model", "test-prompt")
    assert not result.is_valid
    assert gate.thesis_graph.get_cursor() == initial_cursor


def test_14_qwen_gpt_failure_preserves_last_valid_result(base_packet):
    adapter = SynthesizerAdapter(backend_adapter=None)
    
    obs = adapter.synthesize(base_packet)
    assert obs.status in ("UNAVAILABLE", "AWAITING_FIRST_ANALYSIS", "RATE_LIMITED")
    assert obs.current_state in ("AWAITING_FIRST_ANALYSIS", "NO_TRADE", "UNRESOLVED")
    
    adapter.last_synthesis = PrimarySynthesisOutput(
        current_state="CALL_DEVELOPING",
        setup_family="CONTINUATION",
        entry_window="APPROACHING",
        why_now=["Spot rose with CE premium (metric:spot_price)"],
        reversal_watch={"direction": "NONE", "status": "NONE"},
        option_buyer_side="CALL_FAVOURABLE",
        premium_confirmation="CONFIRMING",
        what_would_change_my_mind=["Break below 23950"],
        five_hypotheses={},
        evidence_ids=["metric:spot_price"],
        model_name="openai/gpt-oss-120b",
        status="CURRENT",
        input_revision=100,
        synthesized_at="2026-09-03T10:00:00Z",
    )
    
    preserved = adapter.synthesize(base_packet)
    assert preserved.current_state == "CALL_DEVELOPING"
    assert preserved.why_now == ["Spot rose with CE premium (metric:spot_price)"]


def test_15_vob_unchanged():
    res = subprocess.run(
        ["git", "diff", "CITADEL_MASTER/"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.stdout == "", f"CITADEL_MASTER/ was modified! Diff:\n{res.stdout}"


def test_16_broker_execution_disabled():
    from src.oracle_sol.phase1_coordinator import Phase1CognitiveCoordinator
    coord = Phase1CognitiveCoordinator()
    assert getattr(coord, "broker_submission", False) is False
    assert getattr(coord, "live_trading", False) is False
    assert getattr(coord, "paper_only", True) is True
    assert getattr(coord, "execution_influence", "ZERO") == "ZERO" 
