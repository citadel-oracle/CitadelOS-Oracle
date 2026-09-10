import json
from pathlib import Path

from scripts.arena_recorded_temporal import recorded_temporal_packet
from scripts.arena_synthesis_input import synthesis_input
from scripts.brain_arena_desk_probe import compact_synthesis_schema
from src.oracle_sol.synthesizer_adapter import SYNTHESIZER_OUTPUT_SCHEMA


def test_synthesis_memos_are_blinded_lossless_and_untrusted():
    packet, _ = recorded_temporal_packet()
    payload = synthesis_input(packet)
    records = {r["ordinal"]: r for r in map(json.loads, (Path(__file__).resolve().parents[2] /
        "artifacts/brain_arena_master_override/calls.jsonl").read_text().splitlines()) if r.get("kind") == "RESULT"}
    for item, ordinal in zip(payload["desk_memos"], (16, 19, 21, 22)):
        assert item["status"] == "UNTRUSTED_MODEL_HYPOTHESIS"
        memo = item["memo"]
        for section in ("claim", "support", "contradiction", "missing_confirmation", "temporal_change", "internal_tension"):
            claims = [memo[section]] if section == "claim" else memo[section]
            for claim in claims:
                claim["evidence_ids"] = [payload["citation_ids"][i] for i in claim.pop("citation_codes")]
        assert memo == records[ordinal]["output"]
    assert all(eid in payload["evidence"] for eid in packet.unseen_event_ids)
    assert "requested_model" not in json.dumps(payload)
    assert "response_model" not in json.dumps(payload)


def test_compact_schema_round_trip_is_exact_not_relaxed():
    from copy import deepcopy
    from jsonschema import Draft202012Validator
    schema = compact_synthesis_schema()
    Draft202012Validator.check_schema(schema)
    restored = deepcopy(schema)
    definition = restored.pop("$defs")["hypothesis"]
    for name, ref in restored["properties"]["five_hypotheses"]["properties"].items():
        assert ref == {"$ref": "#/$defs/hypothesis"}
        restored["properties"]["five_hypotheses"]["properties"][name] = deepcopy(definition)
    assert restored == SYNTHESIZER_OUTPUT_SCHEMA
    assert len(json.dumps(schema)) < len(json.dumps(SYNTHESIZER_OUTPUT_SCHEMA))
