import pytest
from src.oracle_sol.contracts import SolEvidenceSnapshot, MarketEvent, SystemStatus
from src.oracle_sol.brain_packet_compiler import BrainPacketCompiler
from src.oracle_sol.thesis_graph import ThesisGraph, COGNITIVE_SHADOW_SYSTEM_PROMPT
from src.oracle_sol.evidence_gate import EvidenceGate
from tests.test_cognitive_shadow_v1 import _make_dummy_snapshot, _make_dummy_event, _make_valid_15_section_payload

def test_semantic_gate_v2_invented_price_level_rejected():
    tg = ThesisGraph()
    gate = EvidenceGate(tg)
    payload = _make_valid_15_section_payload("evt_001")
    payload["call_case"]["argument"] = "Breakout above invented level 28500 expected."
    
    compiler = BrainPacketCompiler()
    packet = compiler.compile_packet("sess_1", 1, _make_dummy_snapshot(), None, [_make_dummy_event("evt_001")], [], [])
    
    res = gate.validate_and_commit(payload, packet, "gpt-oss", COGNITIVE_SHADOW_SYSTEM_PROMPT)
    assert res.is_valid is False
    assert res.status == "SEMANTIC_CLAIM_REJECTED"
    assert "INVENTED_PRICE_LEVEL" in res.error_details

def test_semantic_gate_v2_unsupported_oi_directional_claim_rejected():
    tg = ThesisGraph()
    gate = EvidenceGate(tg)
    payload = _make_valid_15_section_payload("evt_001")
    payload["put_case"]["argument"] = "Massive put buying indicates aggressive bearish sentiment."
    payload["put_case"]["evidence_ids"] = ["metric:put_oi_build"]  # ONLY OI cited, no flow/price/premium!
    
    compiler = BrainPacketCompiler()
    packet = compiler.compile_packet("sess_1", 1, _make_dummy_snapshot(), None, [_make_dummy_event("evt_001")], [], [])
    
    res = gate.validate_and_commit(payload, packet, "gpt-oss", COGNITIVE_SHADOW_SYSTEM_PROMPT)
    assert res.is_valid is False
    assert res.status == "SEMANTIC_CLAIM_REJECTED"
    assert "OI_DIRECTIONAL_INFERENCE_UNSUPPORTED" in res.error_details

def test_semantic_gate_v2_cross_section_contradiction_rejected():
    tg = ThesisGraph()
    gate = EvidenceGate(tg)
    payload = _make_valid_15_section_payload("evt_001")
    payload["market_story"]["narrative"] = "Sellers were aggressively absorbed at VWAP."
    payload["reversal_analysis"]["absorption_or_exhaustion"] = "No absorption or failed move detected."
    
    compiler = BrainPacketCompiler()
    packet = compiler.compile_packet("sess_1", 1, _make_dummy_snapshot(), None, [_make_dummy_event("evt_001")], [], [])
    
    res = gate.validate_and_commit(payload, packet, "gpt-oss", COGNITIVE_SHADOW_SYSTEM_PROMPT)
    assert res.is_valid is False
    assert res.status == "SEMANTIC_CLAIM_REJECTED"
    assert "CROSS_SECTION_CONTRADICTION" in res.error_details

def test_semantic_gate_v2_valid_payload_committed_with_research_states():
    tg = ThesisGraph()
    gate = EvidenceGate(tg)
    payload = _make_valid_15_section_payload("evt_001")
    
    compiler = BrainPacketCompiler()
    packet = compiler.compile_packet("sess_1", 1, _make_dummy_snapshot(), None, [_make_dummy_event("evt_001")], [], [])
    
    res = gate.validate_and_commit(payload, packet, "gpt-oss", COGNITIVE_SHADOW_SYSTEM_PROMPT)
    assert res.is_valid is True
    assert res.status == "COMMITTED"
    node = res.committed_thesis
    assert node.setup_family in {"CONTINUATION", "PULLBACK", "BREAKOUT", "REVERSAL", "FAILED_AGGRESSION", "UNRESOLVED", "NO_TRADE"}
    assert node.reversal_state in {"DEVELOPING", "NOT_DETECTED", "UNRESOLVED"}
