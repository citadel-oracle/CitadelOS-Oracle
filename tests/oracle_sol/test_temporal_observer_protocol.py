import json
from scripts.arena_recorded_temporal import recorded_temporal_packet
from scripts.brain_arena_desk_probe import recorded_input, failure_blocks_comparison
from src.oracle_sol.temporal_observer_protocol import observer_input, validate_observation


def test_observer_preserves_every_event_without_full_metric_prompt():
    packet, _ = recorded_temporal_packet()
    payload = observer_input(packet)
    assert set(packet.unseen_event_ids) <= payload["evidence"].keys()
    for eid in packet.unseen_event_ids:
        assert payload["evidence"][eid] == packet.resolve_evidence(eid)
    assert payload["previous_accepted_thesis"] is None
    _, text, _ = recorded_input("CALL", "temporal_observer", "temporal")
    _, desk, _ = recorded_input("CALL", "side_falsifier", "temporal")
    assert len(text) < len(desk)


def test_observer_missing_confirmation_is_not_contradiction():
    packet, _ = recorded_temporal_packet()
    note = {"claim": "Some input fields are missing.", "evidence_ids": ["coverage:input"]}
    output = {"developing_view": "UNRESOLVED", "observation": note,
              "strengthening": [], "weakening": [], "contradiction": [], "missing_confirmation": [note]}
    assert validate_observation(output, packet) is None
    output["contradiction"] = [note]
    assert validate_observation(output, packet) == "MISSING_INPUT_IS_NOT_MARKET_EVIDENCE"


def test_413_requires_distinct_role_and_measured_smaller_input():
    failure = {"kind": "RESULT", "provider": "groq", "requested_model": "qwen",
               "role": "side_falsifier", "http_status": 413, "payload_bytes": 20000}
    assert not failure_blocks_comparison(failure, "groq", "qwen", role="temporal_observer", payload_bytes=10000)
    assert failure_blocks_comparison(failure, "groq", "qwen", role="temporal_observer", payload_bytes=20000)
    assert not failure_blocks_comparison(failure, "groq", "qwen", role="side_falsifier", payload_bytes=10000)
