import json
from datetime import datetime

from scripts.brain_arena_desk_probe import recorded_input


def test_real_temporal_packet_preserves_ids_time_and_contracts():
    packet, text, source_hash = recorded_input("CALL", "side_specialist", "temporal")
    assert source_hash == "73f84fd4b221394406b6f11ed10916d77b67a0e91a4c933534a4a30d1c02be93"
    assert len(packet.unseen_event_ids) == 8
    assert set(packet.unseen_event_ids) <= set(packet.valid_evidence_ids)
    assert packet.previous_thesis is None
    assert packet.canonical_state["flow_net_delta"] is None
    assert packet.canonical_state["mlofi_5l"] is None
    assert packet.aggression_response_sequence == []
    for eid in packet.unseen_event_ids:
        event = packet.resolve_evidence(eid)["value"]
        assert datetime.fromisoformat(event["timestamp_utc"]) <= datetime.fromisoformat("2026-09-04T04:19:51+00:00")
        if event["event_type"] == "SENSORIUM_DELTA":
            for side in ("ce_pricing", "pe_pricing"):
                delta = event["supporting_values"]["diffs"][side]
                assert delta["before"]["security_id"] == delta["after"]["security_id"]
                assert delta["before"]["source_timestamp"] < delta["after"]["source_timestamp"]
    _, put, _ = recorded_input("PUT", "side_specialist", "temporal")
    assert json.loads(put)["evidence"] == json.loads(text)["evidence"]
    assert recorded_input("CALL", "side_specialist", "temporal")[1] == text
