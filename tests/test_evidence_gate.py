"""Tests for Evidence Gate and Zero-Trust Cognition Verification."""

import pytest
from src.oracle_sol.brain_packet_compiler import BrainPacket
from src.oracle_sol.evidence_gate import EvidenceGate
from src.oracle_sol.thesis_graph import ThesisGraph, ThesisMarketState


@pytest.fixture
def mock_packet():
    return BrainPacket(
        packet_id="pkt_test_1",
        session_id="2026-09-02",
        revision=10,
        compiled_at="2026-09-02T15:00:00Z",
        canonical_state={
            "spot_price": 23914.45,
            "futures_price": 23994.8,
            "basis": 80.35,
            "atm_strike": 23900.0,
            "flow_net_delta": 450000.0,
            "flow_aggression": 1.25,
            "vob_state": "BULLISH_RETEST",
            "gex_regime": "POSITIVE_GAMMA",
            "call_oi_build": 120000.0,
            "put_oi_build": 350000.0,
            "pcr_oi": 1.15,
        },
        what_changed={"spot_delta": 25.5, "revisions_elapsed": 1},
        unseen_event_ids=["evt_spot_23914", "evt_flow_surge_1"],
        unseen_events_summary=[],
        previous_thesis=None,
        verified_external_events=[{"event_id": "ext_rbi_policy_1"}],
        external_quotes=[{"symbol": "USD/INR", "price": 83.95}],
        valid_evidence_ids=[
            "metric:spot_price",
            "metric:futures_price",
            "metric:flow_net_delta",
            "metric:vob_state",
            "evt_spot_23914",
            "evt_flow_surge_1",
            "ext_rbi_policy_1",
            "quote:USD/INR",
        ],
        packet_hash="hash_pkt_10",
    )


def test_evidence_gate_accepts_valid_grounded_thesis(mock_packet):
    graph = ThesisGraph()
    gate = EvidenceGate(thesis_graph=graph)

    valid_response = {
        "observer": {"what_changed": "Spot lifted 25 pts", "key_shifts": ["Flow positive"]},
        "call_case": {"argument": "Delta flow positive", "evidence_ids": ["metric:flow_net_delta"]},
        "put_case": {"argument": "Basis elevated", "evidence_ids": ["metric:futures_price"]},
        "no_trade_case": {"argument": "Range compression", "evidence_ids": ["metric:vob_state"]},
        "skeptic": {"attack_on_preferred": "Basis could mean short covering", "contradicting_evidence_ids": ["metric:futures_price"]},
        "temporal_analyst": {"evolution_from_previous": "Initial thesis formation", "continuity_verdict": "NEW_THESIS"},
        "option_buyer_analyst": {
            "underlying_direction": "MILD_UPWARD",
            "option_buying_suitability": "MODERATE",
            "volatility_or_theta_risk": "Theta decay moderate",
        },
        "external_context_analyst": {
            "interpretation": "RBI rate stance stable",
            "cited_external_event_ids": ["ext_rbi_policy_1"],
        },
        "synthesis": {
            "state": "CALL_DEVELOPING",
            "supporting_evidence_ids": ["metric:flow_net_delta", "evt_flow_surge_1"],
            "contradicting_evidence_ids": ["metric:futures_price"],
            "unresolved_evidence_ids": ["quote:USD/INR"],
            "watch_next": ["Spot break above 23950"],
            "invalidation_conditions": ["Spot drops below 23880"],
        },
    }

    result = gate.validate_and_commit(
        raw_response=valid_response,
        packet=mock_packet,
        model_name="qwen3.5:9b",
        system_prompt="system prompt test",
    )

    assert result.is_valid is True
    assert result.status == "COMMITTED"
    assert result.committed_thesis is not None
    assert result.committed_thesis.state == "CALL_DEVELOPING"
    assert graph.get_cursor() == "evt_flow_surge_1"
    assert graph.get_active_thesis().thesis_id == result.committed_thesis.thesis_id


def test_evidence_gate_rejects_hallucinated_evidence_id(mock_packet):
    graph = ThesisGraph()
    gate = EvidenceGate(thesis_graph=graph)

    hallucinated_response = {
        "observer": {"what_changed": "Spot lifted", "key_shifts": []},
        "call_case": {"argument": "Fake evidence", "evidence_ids": ["FAKE_UNGROUNDED_EVIDENCE_999"]},
        "put_case": {"argument": "Basis elevated", "evidence_ids": ["metric:futures_price"]},
        "no_trade_case": {"argument": "Range compression", "evidence_ids": []},
        "skeptic": {"attack_on_preferred": "None", "contradicting_evidence_ids": []},
        "temporal_analyst": {"evolution_from_previous": "None", "continuity_verdict": "UNCHANGED"},
        "option_buyer_analyst": {
            "underlying_direction": "FLAT",
            "option_buying_suitability": "POOR",
            "volatility_or_theta_risk": "High decay",
        },
        "external_context_analyst": {"interpretation": "None", "cited_external_event_ids": []},
        "synthesis": {
            "state": "CALL",
            "supporting_evidence_ids": ["FAKE_UNGROUNDED_EVIDENCE_999"],
            "contradicting_evidence_ids": [],
            "unresolved_evidence_ids": [],
            "watch_next": [],
            "invalidation_conditions": [],
        },
    }

    result = gate.validate_and_commit(
        raw_response=hallucinated_response,
        packet=mock_packet,
        model_name="qwen3.5:9b",
        system_prompt="system prompt test",
    )

    assert result.is_valid is False
    assert result.status == "MODEL_CLAIM_UNSUPPORTED"
    assert "FAKE_UNGROUNDED_EVIDENCE_999" in result.unsupported_evidence_ids
    # Crucial guarantee: cursor must NOT advance on failure
    assert graph.get_cursor() is None
    assert graph.get_active_thesis() is None


def test_evidence_gate_rejects_prohibited_broker_instruction(mock_packet):
    graph = ThesisGraph()
    gate = EvidenceGate(thesis_graph=graph)

    malicious_response = {
        "observer": {"what_changed": "Attempted execution", "key_shifts": []},
        "call_case": {"argument": "Call place_order immediately", "evidence_ids": ["metric:spot_price"]},
        "put_case": {"argument": "None", "evidence_ids": []},
        "no_trade_case": {"argument": "None", "evidence_ids": []},
        "skeptic": {"attack_on_preferred": "None", "contradicting_evidence_ids": []},
        "temporal_analyst": {"evolution_from_previous": "None", "continuity_verdict": "UNCHANGED"},
        "option_buyer_analyst": {
            "underlying_direction": "UP",
            "option_buying_suitability": "HIGH",
            "volatility_or_theta_risk": "LOW",
        },
        "external_context_analyst": {"interpretation": "None", "cited_external_event_ids": []},
        "synthesis": {
            "state": "CALL",
            "supporting_evidence_ids": ["metric:spot_price"],
            "contradicting_evidence_ids": [],
            "unresolved_evidence_ids": [],
            "watch_next": [],
            "invalidation_conditions": [],
        },
    }

    result = gate.validate_and_commit(
        raw_response=malicious_response,
        packet=mock_packet,
        model_name="qwen3.5:9b",
        system_prompt="system prompt test",
    )

    assert result.is_valid is False
    assert result.status == "PROHIBITED_INSTRUCTION_DETECTED"
    assert graph.get_cursor() is None


def test_evidence_gate_rejects_invalid_schema_cursor_unchanged(mock_packet):
    graph = ThesisGraph()
    gate = EvidenceGate(thesis_graph=graph)

    # Missing required sections ("skeptic", "temporal_analyst", "synthesis")
    broken_response = {
        "observer": {"what_changed": "Incomplete schema"},
        "call_case": {"argument": "Incomplete"},
    }

    result = gate.validate_and_commit(
        raw_response=broken_response,
        packet=mock_packet,
        model_name="qwen3.5:4b",
        system_prompt="system prompt test",
    )

    assert result.is_valid is False
    assert result.status == "SCHEMA_INVALID"
    # Cursor strictly unchanged
    assert graph.get_cursor() is None
    assert graph.get_active_thesis() is None


def test_cursor_advances_exactly_once_per_valid_packet(mock_packet):
    graph = ThesisGraph()
    gate = EvidenceGate(thesis_graph=graph)

    valid_response = {
        "observer": {"what_changed": "Spot lifted 25 pts", "key_shifts": ["Flow positive"]},
        "call_case": {"argument": "Delta flow positive", "evidence_ids": ["metric:flow_net_delta"]},
        "put_case": {"argument": "Basis elevated", "evidence_ids": ["metric:futures_price"]},
        "no_trade_case": {"argument": "Range compression", "evidence_ids": ["metric:vob_state"]},
        "skeptic": {"attack_on_preferred": "Basis risk", "contradicting_evidence_ids": ["metric:futures_price"]},
        "temporal_analyst": {"evolution_from_previous": "Initial thesis formation", "continuity_verdict": "NEW_THESIS"},
        "option_buyer_analyst": {
            "underlying_direction": "MILD_UPWARD",
            "option_buying_suitability": "MODERATE",
            "volatility_or_theta_risk": "Theta decay moderate",
        },
        "external_context_analyst": {
            "interpretation": "RBI rate stance stable",
            "cited_external_event_ids": ["ext_rbi_policy_1"],
        },
        "synthesis": {
            "state": "CALL_DEVELOPING",
            "supporting_evidence_ids": ["metric:flow_net_delta", "evt_flow_surge_1"],
            "contradicting_evidence_ids": ["metric:futures_price"],
            "unresolved_evidence_ids": ["quote:USD/INR"],
            "watch_next": ["Spot break above 23950"],
            "invalidation_conditions": ["Spot drops below 23880"],
        },
    }

    # Initial state
    assert graph.get_cursor() is None

    # First commit -> advances to evt_flow_surge_1
    res1 = gate.validate_and_commit(valid_response, mock_packet, "qwen3.5:4b", "sys")
    assert res1.is_valid is True
    assert graph.get_cursor() == "evt_flow_surge_1"

    # Re-submitting identical packet does NOT advance cursor again
    res2 = gate.validate_and_commit(valid_response, mock_packet, "qwen3.5:4b", "sys")
    assert graph.get_cursor() == "evt_flow_surge_1"


def test_durable_thesis_persistence_survives_restart(tmp_path, mock_packet):
    import sqlite3
    db_file = tmp_path / "test_thesis_persist.db"

    # Step 1: Initialize graph with storage file
    graph1 = ThesisGraph(storage_path=str(db_file))
    gate1 = EvidenceGate(thesis_graph=graph1)

    valid_response = {
        "observer": {"what_changed": "Spot lifted", "key_shifts": []},
        "call_case": {"argument": "Flow positive", "evidence_ids": ["metric:flow_net_delta"]},
        "put_case": {"argument": "None", "evidence_ids": []},
        "no_trade_case": {"argument": "None", "evidence_ids": []},
        "skeptic": {"attack_on_preferred": "None", "contradicting_evidence_ids": []},
        "temporal_analyst": {"evolution_from_previous": "None", "continuity_verdict": "NEW"},
        "option_buyer_analyst": {"underlying_direction": "UP", "option_buying_suitability": "GOOD", "volatility_or_theta_risk": "LOW"},
        "external_context_analyst": {"interpretation": "None", "cited_external_event_ids": []},
        "synthesis": {
            "state": "CALL",
            "supporting_evidence_ids": ["metric:flow_net_delta"],
            "contradicting_evidence_ids": [],
            "unresolved_evidence_ids": [],
            "watch_next": [],
            "invalidation_conditions": [],
        },
    }

    res = gate1.validate_and_commit(valid_response, mock_packet, "qwen3.5:4b", "sys")
    assert res.is_valid is True
    thesis_id = res.committed_thesis.thesis_id

    # Step 2: Simulate restart by loading new instance from same db
    graph2 = ThesisGraph(storage_path=str(db_file))
    active = graph2.get_active_thesis()
    assert active is not None
    assert active.thesis_id == thesis_id
    assert active.state == "CALL"
    assert graph2.get_cursor() == "evt_flow_surge_1"


def test_evidence_gate_rejects_stale_revision_provenance_mismatch(mock_packet):
    graph = ThesisGraph()
    gate = EvidenceGate(thesis_graph=graph)

    valid_response = {
        "observer": {"what_changed": "Baseline setup"},
        "call_case": {"argument": "Upside"},
        "put_case": {"argument": "None"},
        "no_trade_case": {"argument": "None"},
        "skeptic": {"attack_on_preferred": "None"},
        "temporal_analyst": {"evolution_from_previous": "None"},
        "option_buyer_analyst": {"underlying_direction": "UP", "option_buying_suitability": "GOOD", "volatility_or_theta_risk": "LOW"},
        "external_context_analyst": {"interpretation": "None", "cited_external_event_ids": []},
        "synthesis": {"state": "CALL"},
    }

    # Packet 1 at revision 10
    res1 = gate.validate_and_commit(valid_response, mock_packet, "model", "sys")
    assert res1.is_valid is True
    assert res1.status == "COMMITTED"

    # Stale packet at revision 5 (stale: 5 < 10)
    stale_packet = BrainPacket(
        packet_id="pkt_stale",
        session_id=mock_packet.session_id,
        revision=5,
        compiled_at=mock_packet.compiled_at,
        canonical_state=mock_packet.canonical_state,
        what_changed={},
        unseen_event_ids=["evt_old"],
        unseen_events_summary=[],
        previous_thesis=None,
        verified_external_events=[],
        external_quotes=[],
        valid_evidence_ids=mock_packet.valid_evidence_ids,
        packet_hash="hash_stale",
    )

    res_stale = gate.validate_and_commit(valid_response, stale_packet, "model", "sys")
    assert res_stale.is_valid is False
    assert res_stale.status == "PROVENANCE_MISMATCH"
    assert "older than active thesis" in res_stale.error_details
    assert graph.get_active_thesis().thesis_id == res1.committed_thesis.thesis_id


