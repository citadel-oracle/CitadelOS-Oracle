from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.oracle_sol.cognitive_projection import project_cognitive_decision
from src.oracle_sol.cognitive_output_validation import cognitive_output_error
from src.oracle_sol.synthesizer_adapter import SYNTHESIZER_OUTPUT_SCHEMA, SynthesizerAdapter
from src.oracle_sol.qwen_sentinel_adapter import QWEN_SENTINEL_OUTPUT_SCHEMA
from src.oracle_sol.gemini_reviewer_adapter import GEMINI_REVIEWER_OUTPUT_SCHEMA


NOW = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)


def node(**updates):
    data = dict(thesis_id="accepted-12", session_id="2026-09-03", input_revision=12,
                created_at="2026-09-03T07:59:50+00:00", state="CALL", entry_window="READY",
                input_hash="accepted-hash", what_changed="Recorded change", why_now=["Recorded reason metric:spot_price"],
                qwen_observation={}, gemini_review={})
    data["semantic_validation"] = {"input_hash": "accepted-hash", "revision": 12,
        "response": {"synthesis": {"state": "CALL"}},
        "context": {"canonical_state": {}, "canonical_levels": [], "cited_ids": ["metric:spot_price"]}}
    data.update(updates)
    return SimpleNamespace(to_dict=lambda: deepcopy(data), **data)


def project(active=None, attempt=None, **snapshot):
    return project_cognitive_decision(active, None, attempt or {},
        {"market_session_date": "2026-09-03", "system_status": "HEALTHY", **snapshot}, NOW)


def test_newer_attempt_cannot_mix_state_prose_or_commit_revision():
    result = project(node(), {"input_revision": 99, "decision": {"current_state": "PUT", "why_now": ["Uncommitted"]},
                    "models": {"gpt_oss": {"input_revision": 99, "status": "CURRENT"}}})
    assert result["primary_decision"]["state"] == "CALL"
    assert result["primary_decision"]["why_now"] == ["Recorded reason metric:spot_price"]
    assert result["gpt"]["status"] == "OUTPUT_UNVALIDATED"
    assert result["evidence_gate"]["last_commit_revision"] == 12
    assert result["gpt"]["output"]["input_revision"] == 12


def test_no_thesis_does_not_create_no_trade_readiness_or_consensus():
    result = project()
    assert result["primary_decision"]["state"] is None
    assert result["primary_decision"]["entry_window"] is None
    assert result["primary_decision"]["model_tension"] is None
    assert result["gpt"]["age_seconds"] is None
    assert result["gpt"]["response_id"] is None


@pytest.mark.parametrize("facts", [
    {"pcr_oi": .5, "total_net_gex_inr_cr": -20, "spot_price": 100, "zero_gamma": 110},
    {"pcr_oi": 2, "total_net_gex_inr_cr": 20, "spot_price": 120, "zero_gamma": 110},
    {"cvd": -100, "basis": -30},
])
def test_projection_never_invents_interpretation_from_market_numbers(facts):
    active = node(what_changed="Revision 12 analyzed.", entry_window="READY")
    data = active.to_dict()
    data["semantic_validation"]["context"]["canonical_state"] = facts
    result = project(SimpleNamespace(to_dict=lambda: data))["primary_decision"]
    assert result["what_changed"] is None
    assert result["option_buyer_side"] is None
    assert result["premium_confirmation"] is None
    assert result["reversal_watch"] is None
    assert result["opportunity_maturity"] is None
    assert result["watch_next"] == []


def test_real_age_and_role_output_are_not_attempt_telemetry():
    observation = {"input_revision": 12, "observed_at": "2026-09-03T07:59:45Z", "strongest_new_relationship": "Recorded observation"}
    result = project(node(qwen_observation=observation))
    assert result["qwen"]["age_seconds"] == 15
    assert result["qwen"]["output"] == observation
    assert result["gpt"]["age_seconds"] == 10


def test_inflight_keeps_current_accepted_read_without_relabelling_stale_data():
    result = project(node(), {"inference_in_flight": True})
    assert result["gpt"]["status"] == "UPDATING"
    assert result["primary_decision"]["state"] == "CALL"
    assert project(node(created_at="2026-09-03T07:50:00Z"), {"inference_in_flight": True})["gpt"]["status"] == "OUTDATED"


@pytest.mark.parametrize("timestamp, expected", [(None, "STALE"), ("2026-09-03T08:10:00Z", "STALE"),
    ("2026-09-03T07:50:00Z", "OUTDATED")])
def test_unknown_future_and_old_output_not_current(timestamp, expected):
    assert project(node(created_at=timestamp))["gpt"]["status"] == expected


def test_market_closed_and_prior_session_are_not_live():
    assert project(node(), system_status="OFF_MARKET")["gpt"]["status"] == "SESSION_LAST"
    assert project(node(session_id="2026-09-02"))["gpt"]["status"] == "STALE"


def test_failure_preserves_output_but_not_current_status_or_response_identity():
    result = project(node(), {"models": {"gpt_oss": {"input_revision": 13, "status": "RATE_LIMITED", "provider_request_id": "failed"}}})
    assert result["gpt"]["status"] == "RATE_LIMITED"
    assert result["gpt"]["response_id"] == "accepted-12"
    assert result["gpt"]["output"]["state"] == "CALL"


def schema_value(schema):
    if "enum" in schema:
        return schema["enum"][0]
    if schema.get("type") == "object":
        return {key: schema_value(schema["properties"][key]) for key in schema.get("required", [])}
    if schema.get("type") == "array":
        return []
    return "Recorded observation"


@pytest.mark.parametrize("schema", [SYNTHESIZER_OUTPUT_SCHEMA, QWEN_SENTINEL_OUTPUT_SCHEMA, GEMINI_REVIEWER_OUTPUT_SCHEMA])
def test_schema_and_nested_evidence_are_strict(schema):
    packet = SimpleNamespace(valid_evidence_ids=["metric:spot_price"], resolve_evidence=lambda value: 24000 if value == "metric:spot_price" else None)
    output = schema_value(schema)
    assert cognitive_output_error(output, schema, packet) is None
    assert cognitive_output_error({}, schema, packet) == "SCHEMA_INVALID"
    if "evidence_ids" in output:
        output["evidence_ids"] = ["peer:qwen"]
    else:
        output["earliest_contradiction"]["evidence_ids"] = ["peer:qwen"]
    assert cognitive_output_error(output, schema, packet) == "MODEL_CLAIM_UNSUPPORTED"


def test_parsed_empty_json_never_becomes_no_trade():
    class Provider:
        def invoke_reasoning(self, **kwargs):
            return {}, {"schema_status": "SCHEMA_VALID_JSON", "http_status": 200}
    packet = SimpleNamespace(revision=12, session_id="test", valid_evidence_ids=[], to_dict=lambda: {})
    adapter = SynthesizerAdapter(backend_adapter=Provider())
    adapter._build_synthesizer_prompt = lambda *args: "isolated test"
    result = adapter.synthesize(packet)
    assert result.status == "OUTPUT_INVALID"
    assert result.current_state == "AWAITING_FIRST_ANALYSIS"
    assert adapter.last_synthesis is None


@pytest.mark.parametrize("argument, ids, state, error", [
    ("Call buying follows call OI build", ["metric:call_oi_build"], "CALL", "OI_DIRECTIONAL_INFERENCE_UNSUPPORTED"),
    ("Positive GEX supports the call case", ["metric:total_net_gex_inr_cr"], "CALL", "GEX_DIRECTIONAL_INFERENCE_UNSUPPORTED"),
    ("Negative GEX supports the put case", ["metric:total_net_gex_inr_cr"], "PUT", "GEX_DIRECTIONAL_INFERENCE_UNSUPPORTED"),
    ("Institutional absorption supports the move", [], "NO_TRADE", "INSTITUTIONAL_CLAIM_UNSUPPORTED"),
    ("Seller absorption is high", [], "NO_TRADE", "ABSORPTION_QUALITATIVE_INVENTION"),
])
def test_semantic_firewall_matrix(argument, ids, state, error):
    from src.oracle_sol.evidence_gate import EvidenceGate
    from src.oracle_sol.thesis_graph import ThesisGraph
    packet = SimpleNamespace(canonical_levels=[], canonical_state={"order_flow_response_state": "MIXED"})
    raw = {"call_case": {"argument": argument, "evidence_ids": ids},
           "put_case": {"argument": argument, "evidence_ids": ids}, "synthesis": {"state": state}}
    result = EvidenceGate(ThesisGraph())._validate_semantic_claims(raw, packet, set(ids))
    assert result and error in result
