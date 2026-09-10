from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from src.oracle_sol.brain_packet_compiler import BrainPacketCompiler
from src.oracle_sol.contracts import SolEvidenceSnapshot, SystemStatus, MarketEvent
from src.oracle_sol.desk_protocol import desk_input, validate_desk_memo, synthesis_desks, compact_desk_input


@pytest.fixture
def packet():
    root = Path(__file__).parent / "fixtures"
    raw = json.loads((root / "bridge_recorded_snapshot_20260904.json").read_text())
    raw["system_status"] = SystemStatus(raw["system_status"])
    snapshot = SolEvidenceSnapshot(**raw)
    events = [MarketEvent(**json.loads(line)) for line in
              (root / "bridge_recorded_events_20260904.jsonl").read_text().splitlines()]
    return BrainPacketCompiler().compile_packet(snapshot.market_session_date, 2, snapshot, None, events, [], [])


def memo(packet, side="CALL"):
    return {"side": side, "state": "UNRESOLVED",
            "claim": {"claim": "Recorded event requires confirmation.",
                      "evidence_ids": [packet.unseen_event_ids[-1]]},
            **{name: [] for name in ("support", "contradiction", "missing_confirmation", "temporal_change", "internal_tension")}}


def test_mirrored_inputs_have_identical_neutral_evidence_and_no_mutation(packet):
    call = desk_input(packet, "CALL", "side_specialist")
    put = desk_input(packet, "PUT", "side_specialist")
    assert call["neutral_context"] == put["neutral_context"]
    assert call["evidence"] == put["evidence"]
    assert call["unseen_event_ids"] == put["unseen_event_ids"]
    assert call["valid_evidence_ids"] == put["valid_evidence_ids"]
    assert all(value["evidence_id"] == key for key, value in call["evidence"].items())
    call["neutral_context"].clear()
    assert packet.canonical_state
    assert put["neutral_context"]


def test_falsifier_attacks_same_side(packet):
    result = desk_input(packet, "PUT", "side_falsifier")
    assert result["side"] == "PUT"
    assert "SAME assigned side" in result["protocol"]["role"]


def test_desk_preserves_compiled_continuity_and_response_without_new_citations(packet):
    before = deepcopy(packet.to_dict())
    result = desk_input(packet, "CALL", "side_falsifier")
    assert result["option_continuity"] == packet.option_continuity
    assert result["aggression_response_sequence"] == packet.aggression_response_sequence
    assert set(result["valid_evidence_ids"]) == set(packet.valid_evidence_ids)
    result["option_continuity"].clear()
    result["aggression_response_sequence"].clear()
    result["evidence"].clear()
    assert packet.to_dict() == before


def test_missing_confirmation_is_not_exempt_from_evidence_validation(packet):
    raw = memo(packet)
    raw["missing_confirmation"] = [{"claim": "Premium confirmation is missing.", "evidence_ids": []}]
    assert validate_desk_memo(raw, packet, "CALL") == "CLAIM_WITHOUT_EVIDENCE"
    raw["missing_confirmation"] = []
    assert validate_desk_memo(raw, packet, "CALL") is None


def test_recorded_oi_and_sensorium_deltas_are_not_flow_aggression(packet):
    # Genuine Sep-4 events include CLOSED_OI_DELTA and SENSORIUM_DELTA,
    # neither of which establishes an aggression event.
    assert any("CLOSED_OI_DELTA" in eid for eid in packet.unseen_event_ids)
    assert packet.aggression_response_sequence == []


def test_compact_input_is_lossless_including_provenance_and_nulls(packet):
    original = desk_input(packet, "CALL", "side_specialist")
    compact = compact_desk_input(original)
    restored = {}
    for eid, row in compact["evidence"].items():
        restored[eid] = {**compact["evidence_metadata"][row["metadata_ref"]],
                         "field": row["field"], "value": row["value"], "evidence_id": eid}
    assert restored == original["evidence"]
    assert compact["valid_evidence_ids"] == original["valid_evidence_ids"]
    assert compact["protocol"] == original["protocol"]


def test_input_coverage_can_explain_missing_not_contrary_evidence(packet):
    coverage = packet.resolve_evidence("coverage:input")
    assert coverage["value"]["unavailable"]
    raw = memo(packet)
    note = {"claim": "Some inputs are unavailable in this packet.", "evidence_ids": ["coverage:input"]}
    raw["missing_confirmation"] = [note]
    assert validate_desk_memo(raw, packet, "CALL") is None
    raw["missing_confirmation"] = [{"claim": "Absorption inputs are unavailable.", "evidence_ids": ["coverage:input"]}]
    assert validate_desk_memo(raw, packet, "CALL") is None
    raw["missing_confirmation"] = [{"claim": "Absorption inputs are unavailable, so bullish buying is ready.", "evidence_ids": ["coverage:input"]}]
    assert validate_desk_memo(raw, packet, "CALL") == "INPUT_COVERAGE_CLAIM_OUT_OF_SCOPE"
    raw["missing_confirmation"] = [note]
    for section in ("support", "contradiction", "temporal_change"):
        raw[section] = [note]
        assert validate_desk_memo(raw, packet, "CALL") == "MISSING_INPUT_IS_NOT_MARKET_EVIDENCE"
        raw[section] = []


def test_actual_falsifier_cannot_deny_recorded_call_premium_increase():
    from scripts.arena_recorded_temporal import recorded_temporal_packet
    packet, source_hash = recorded_temporal_packet()
    record = json.loads((Path(__file__).parent / "fixtures/desk_gpt_falsifier_recorded_20260906.json").read_text())
    assert source_hash == record["source_hash"]
    assert record["http_status"] == 200
    assert validate_desk_memo(record["output"], packet, "CALL") == "PREMIUM_CHANGE_WITHOUT_TEMPORAL_EVIDENCE"
    raw = deepcopy(record["output"])
    event_id = next(eid for eid in packet.unseen_event_ids if "SENSORIUM_DELTA" in eid)
    raw["missing_confirmation"][0]["evidence_ids"] = [event_id]
    assert validate_desk_memo(raw, packet, "CALL") == "CLAIM_CONTRADICTS_RECORDED_PREMIUM_CHANGE"


def test_schema_and_unknown_citations_rejected_without_dropping(packet):
    raw = memo(packet)
    assert validate_desk_memo(raw, packet, "CALL") is None
    raw["claim"]["evidence_ids"].append("model:other-desk")
    assert validate_desk_memo(raw, packet, "CALL") == "MODEL_CLAIM_UNSUPPORTED"
    assert raw["claim"]["evidence_ids"][-1] == "model:other-desk"


@pytest.mark.parametrize("text", ["Call OI is bullish", "institutional absorption", "bullish gamma", "call-side absorption"])
def test_existing_semantic_firewall_applies_to_every_desk_claim(packet, text):
    raw = memo(packet)
    raw["claim"]["claim"] = text
    assert validate_desk_memo(raw, packet, "CALL") is not None


def test_blind_symmetric_order_and_preserved_tension(packet):
    call, put = memo(packet), memo(packet, "PUT")
    call["internal_tension"] = [deepcopy(call["claim"])]
    forward = synthesis_desks(packet, call, put)
    backward = synthesis_desks(replace(packet, revision=3), call, put)
    assert forward[0]["memo"]["side"] == backward[1]["memo"]["side"] == "CALL"
    assert forward[0]["memo"]["internal_tension"] == call["internal_tension"]
    assert all(item["status"] == "UNTRUSTED_MODEL_HYPOTHESIS" for item in forward)
    assert "provider" not in json.dumps(forward)


def test_actual_arena_response_cannot_promote_premium_levels_to_demand():
    from scripts.brain_arena_desk_probe import recorded_input
    record = json.loads((Path(__file__).parent / "fixtures/desk_gpt_recorded_20260906.json").read_text())
    packet, _, source_hash = recorded_input("CALL", "side_specialist")
    assert source_hash == record["source_hash"]
    assert record["http_status"] == 200
    assert record["response_model"] == "openai/gpt-oss-120b"
    assert validate_desk_memo(record["output"], packet, "CALL") == "PREMIUM_LEVEL_IS_NOT_DEMAND"
