"""Tests proving strict benchmark isolation and zero production state mutation."""

import os
import shutil
import tempfile
from pathlib import Path
import pytest

from src.oracle_sol.brain_packet_compiler import BrainPacket
from src.oracle_sol.evidence_gate import EvidenceGate
from src.oracle_sol.thesis_graph import ThesisGraph
from scripts.run_groq_canaries_and_benchmark import create_isolated_gate


@pytest.fixture
def clean_benchmark_dir():
    bench_dir = Path("reports/benchmark_graphs")
    bench_dir.mkdir(parents=True, exist_ok=True)
    yield bench_dir


def test_isolated_gate_does_not_mutate_production(clean_benchmark_dir):
    prod_path = Path("data/sol_shadow/sol_active_thesis_2026-09-02.json")
    prod_mtime_before = prod_path.stat().st_mtime if prod_path.exists() else None

    # Create isolated gates for Model A and Model B
    gate_a = create_isolated_gate("model_a", "pkt_test_100", is_sequential=False)
    gate_b = create_isolated_gate("model_b", "pkt_test_100", is_sequential=False)

    packet_a = BrainPacket(
        packet_id="pkt_test_100",
        session_id="2026-09-02",
        revision=10,
        compiled_at="2026-09-02T15:00:00Z",
        canonical_state={"spot_price": 23900.0},
        what_changed={},
        unseen_event_ids=["evt_a"],
        unseen_events_summary=[],
        previous_thesis=None,
        verified_external_events=[],
        external_quotes=[],
        valid_evidence_ids=["evt_a", "metric:spot_price"],
        packet_hash="hash_a",
    )

    valid_response_a = {
        "observer": {"what_changed": "A move"},
        "call_case": {"argument": "A call"},
        "put_case": {"argument": "None"},
        "no_trade_case": {"argument": "None"},
        "skeptic": {"attack_on_preferred": "None"},
        "temporal_analyst": {"evolution_from_previous": "None"},
        "option_buyer_analyst": {"underlying_direction": "UP", "option_buying_suitability": "GOOD", "volatility_or_theta_risk": "LOW"},
        "external_context_analyst": {"interpretation": "None", "cited_external_event_ids": []},
        "synthesis": {"state": "CALL"},
    }

    # Commit to Model A isolated gate
    res_a = gate_a.validate_and_commit(valid_response_a, packet_a, "model_a", "sys")
    assert res_a.is_valid is True
    assert res_a.status == "COMMITTED"

    # Verify Model B has ZERO state leakage from Model A
    active_b = gate_b.thesis_graph.get_active_thesis()
    assert active_b is None  # Clean, zero leakage!
    assert gate_b.thesis_graph.get_cursor() is None

    # Verify production file was NOT mutated
    if prod_path.exists():
        prod_mtime_after = prod_path.stat().st_mtime
        assert prod_mtime_after == prod_mtime_before


def test_sequential_isolation_preserves_monotonicity(clean_benchmark_dir):
    seq_file = clean_benchmark_dir / "bench_graph_seq_model_seq.jsonl"
    if seq_file.exists():
        seq_file.unlink()
    gate_seq = create_isolated_gate("model_seq", "pkt_none", is_sequential=True)

    pkt1 = BrainPacket(
        packet_id="pkt_seq_1",
        session_id="2026-09-02",
        revision=2,
        compiled_at="2026-09-02T10:00:00Z",
        canonical_state={"spot_price": 23800.0},
        what_changed={},
        unseen_event_ids=["evt_1"],
        unseen_events_summary=[],
        previous_thesis=None,
        verified_external_events=[],
        external_quotes=[],
        valid_evidence_ids=["evt_1", "metric:spot_price"],
        packet_hash="hash_1",
    )

    pkt2 = BrainPacket(
        packet_id="pkt_seq_2",
        session_id="2026-09-02",
        revision=5,
        compiled_at="2026-09-02T10:05:00Z",
        canonical_state={"spot_price": 23820.0},
        what_changed={},
        unseen_event_ids=["evt_2"],
        unseen_events_summary=[],
        previous_thesis=None,
        verified_external_events=[],
        external_quotes=[],
        valid_evidence_ids=["evt_2", "metric:spot_price"],
        packet_hash="hash_2",
    )

    resp = {
        "observer": {"what_changed": "Move"},
        "call_case": {"argument": "Call"},
        "put_case": {"argument": "None"},
        "no_trade_case": {"argument": "None"},
        "skeptic": {"attack_on_preferred": "None"},
        "temporal_analyst": {"evolution_from_previous": "None"},
        "option_buyer_analyst": {"underlying_direction": "UP", "option_buying_suitability": "GOOD", "volatility_or_theta_risk": "LOW"},
        "external_context_analyst": {"interpretation": "None", "cited_external_event_ids": []},
        "synthesis": {"state": "CALL"},
    }

    # Chronological: rev 2 then rev 5
    res1 = gate_seq.validate_and_commit(resp, pkt1, "seq_model", "sys")
    assert res1.is_valid is True
    assert res1.status == "COMMITTED"

    res2 = gate_seq.validate_and_commit(resp, pkt2, "seq_model", "sys")
    assert res2.is_valid is True
    assert res2.status == "COMMITTED"
    assert gate_seq.thesis_graph.get_cursor() == "evt_2"
