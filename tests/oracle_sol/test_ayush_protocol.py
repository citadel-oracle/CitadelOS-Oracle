import json
from dataclasses import replace
from pathlib import Path

from src.oracle_sol.ayush_analysis_protocol import protocol_for
from src.oracle_sol.ayush_corrections import AyushCorrectionLedger
from src.oracle_sol.brain_packet_compiler import BrainPacketCompiler
from src.oracle_sol.contracts import SolEvidenceSnapshot, SystemStatus
from src.oracle_sol.cognitive_feature_bus import project_features


def recorded_snapshot():
    raw = json.loads((Path(__file__).parent / "fixtures/bridge_recorded_snapshot_20260904.json").read_text())
    raw["system_status"] = SystemStatus(raw["system_status"])
    return SolEvidenceSnapshot(**raw)


def compile_snapshot(snapshot):
    return BrainPacketCompiler().compile_packet(snapshot.market_session_date, 1, snapshot, None, [], [], [])


def test_real_recorded_values_and_source_times_not_compile_time():
    snapshot = recorded_snapshot()
    packet = compile_snapshot(snapshot)
    assert packet.canonical_state["mlofi_5l"] == snapshot.mlofi_5l
    assert packet.canonical_state["flow_net_delta"] is None
    assert packet.canonical_state["skew_25d"] == snapshot.skew_25d
    assert packet.canonical_state["session_vwap"] == snapshot.session_vwap
    for field, ids in packet.cognitive_features["domains"].items():
        for eid in ids:
            assert packet.resolve_evidence(eid) is not None
    if snapshot.mlofi_5l is not None:
        assert packet.resolve_evidence("metric:mlofi_5l")["timestamp"] == snapshot.upstream_source_health["producer_sources"]["order_flow"]["source_timestamp"]
    assert not any("ose_" in name for name in project_features(snapshot)["fields"])


def test_missing_basis_not_recalculated_and_bid_not_ltp():
    snapshot = recorded_snapshot()
    ce = dict(snapshot.ce_pricing or {})
    ce["ltp"] = None
    packet = compile_snapshot(replace(snapshot, ce_pricing=ce, futures_basis=None))
    assert packet.canonical_state["basis"] is None
    assert packet.canonical_state["ce_atm_premium"] is None
    ce["ltp"] = 0.0
    assert compile_snapshot(replace(snapshot, ce_pricing=ce)).canonical_state["ce_atm_premium"] == 0.0


def test_protocol_roles_distinct_without_inferred_preferences():
    roles = [protocol_for(role) for role in ("qwen", "gpt", "gemini")]
    assert len({role["role"] for role in roles}) == 3
    assert all(not role["learned_preferences"] for role in roles)
    assert "strongest_counter_case" in roles[0]["comparison"]
    roles[0]["rules"].clear()
    assert protocol_for("qwen")["rules"]
    for component in protocol_for("synthesis")["inspection"]:
        assert all(component[key] for key in ("used_for", "can_support", "cannot_support",
                                             "must_confirm", "discounted_when", "contradicted_by"))


def test_user_correction_is_durable_idempotent_and_not_evidence(tmp_path):
    ledger = AyushCorrectionLedger(str(tmp_path))
    correction = dict(session_id="2026-09-04", recorded_at="2026-09-05T12:00:00+00:00",
        thesis_id="test-only-thesis", input_revision=1, model_thesis={}, user_choice="UNAVAILABLE",
        disagreement="test annotation", prioritized_evidence=[], overweighted_evidence=[],
        missed_evidence=[], category="USER_DEFINED")
    first = ledger.append(**correction)
    assert ledger.append(**correction) == first
    rows = (tmp_path / "ayush_corrections.jsonl").read_text().splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["status"] == "USER_ANNOTATION_NOT_CANONICAL_EVIDENCE"
