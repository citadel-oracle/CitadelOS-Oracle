import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.oracle_sol.luna_input_receipt import persist_receipt, valid_binding, digest
from src.oracle_sol.evidence_gate import EvidenceGate
from src.oracle_sol.privacy_sanitizer import sanitize_brain_packet


def test_immutable_exact_bytes_and_output_binding(tmp_path):
    packet = SimpleNamespace(session_id="2026-09-08", revision=4, unseen_event_ids=["event-a"])
    payload = dict(session_date=packet.session_id, revision=4, evidence_frontier=["event-a"],
                   decision_cutoff_ist="14:35:21", frozen_at_utc="2026-09-08T09:05:21Z")
    body = json.dumps(dict(model="gpt-5.6-luna", messages=[dict(content=json.dumps(payload))])).encode()
    receipt = persist_receipt(tmp_path, body, packet)
    assert receipt == persist_receipt(tmp_path, body, packet)
    saved = (tmp_path / (receipt["receipt_id"] + ".json")).read_bytes()
    response = {"state": "WAIT"}
    receipt["output_hash"] = digest(response)
    assert valid_binding(receipt, response, packet.session_id, 4, "gpt-5.6-luna")
    legacy = deepcopy(receipt)
    del legacy["packet_hash"], legacy["parent_receipt_id"]
    assert valid_binding(legacy, response, packet.session_id, 4, "gpt-5.6-luna")
    assert not valid_binding(receipt, {"state": "CALL"}, packet.session_id, 4, "gpt-5.6-luna")
    assert not valid_binding(receipt, response, packet.session_id, 5, "gpt-5.6-luna")
    assert (tmp_path / (receipt["receipt_id"] + ".json")).read_bytes() == saved
    for field, value in (("request_body", "{}"), ("frontier", []), ("cutoff", "15:30:00"), ("observed_at", "future"), ("packet_hash", "wrong"), ("parent_receipt_id", "wrong")):
        changed = deepcopy(receipt)
        changed[field] = value
        assert not valid_binding(changed, response, packet.session_id, 4, "gpt-5.6-luna")
    with pytest.raises(ValueError):
        persist_receipt(tmp_path, body, SimpleNamespace(session_id=packet.session_id, revision=5, unseen_event_ids=["event-a"]))


def test_retained_tampered_pair_is_rejected_without_commit():
    packet = SimpleNamespace(session_id="2026-09-08", revision=4)
    unbound = EvidenceGate(None).validate_and_commit({"state": "WAIT"}, packet, "gpt-5.6-luna", "test")
    assert unbound.status == "INPUT_RECEIPT_MISMATCH"
    result = EvidenceGate.revalidate_retained({
        "model": "gpt-5.6-luna", "session_id": "2026-09-08", "input_revision": 4,
        "semantic_validation": {"response": {"state": "WAIT"}, "context": {},
                                "input_receipt": {"request_body": "{}"}},
    })
    assert not result.is_valid
    assert result.error_details == "INPUT_RECEIPT_MISMATCH"


def test_current_context_respects_cutoff_and_withholds_unapproved_memory():
    packet = SimpleNamespace(session_id="2026-09-08", revision=4, compiled_at="2026-09-09T00:00:00Z",
        unseen_event_ids=["synthetic-event"], unseen_events_summary=[{
            "event_id": "synthetic-event", "timestamp_utc": "2026-09-08T09:00:00Z",
            "timestamp_ist": "14:30:00", "supporting_values": {"after_spot": 100}}],
        canonical_state={"spot_price": 100, "futures_price": 105, "ce_atm_security_id": "41"},
        evidence_registry={"metric:" + key: {"availability": "RECORDED", "timestamp": ts}
            for key, ts in (("spot_price", "2026-09-08T08:59:00Z"),
                            ("futures_price", "2026-09-08T09:01:00Z"),
                            ("ce_atm_security_id", "2026-09-08T08:59:00Z"))},
        previous_thesis={"state": "CALL", "market_story": "private previous conclusion"})
    payload = sanitize_brain_packet(packet)
    assert payload["current_facts"]["spot_price"]["value"] == 100
    assert payload["current_facts"]["spot_price"]["source_age_seconds_at_cutoff"] == 60
    assert payload["current_facts"]["futures_price"]["value"] is None
    assert payload["current_facts"]["ce_atm_security_id"]["value"] == "41"
    assert payload["previous_model_view"] is None
    assert "private previous conclusion" not in json.dumps(payload)
