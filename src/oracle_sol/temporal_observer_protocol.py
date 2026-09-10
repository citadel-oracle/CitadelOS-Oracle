"""Small observer view of the existing evidence universe, not a coordinator."""
from copy import deepcopy

from src.oracle_sol.ayush_analysis_protocol import protocol_for
from src.oracle_sol.cognitive_output_validation import cognitive_output_error
from src.oracle_sol.desk_protocol import CLAIM_SCHEMA, validate_desk_memo


OBSERVER_SCHEMA = {
    "type": "object",
    "properties": {
        "developing_view": {"type": "string", "enum": ["CALL_DEVELOPING", "PUT_DEVELOPING", "UNRESOLVED"]},
        "observation": CLAIM_SCHEMA,
        **{key: {"type": "array", "items": CLAIM_SCHEMA, "maxItems": 2}
           for key in ("strengthening", "weakening", "contradiction", "missing_confirmation")},
    },
    "required": ["developing_view", "observation", "strengthening", "weakening", "contradiction", "missing_confirmation"],
    "additionalProperties": False,
}


def observer_input(packet):
    protocol = protocol_for("temporal_observer")
    ids = list(dict.fromkeys([*packet.unseen_event_ids, "coverage:input"]))
    evidence = {eid: packet.resolve_evidence(eid) for eid in ids}
    if any(value is None for value in evidence.values()):
        raise ValueError("OBSERVER_UNRESOLVED_EVIDENCE_FRONTIER")
    return deepcopy({
        "role": protocol["role"], "session_id": packet.session_id, "revision": packet.revision,
        "rules": [*protocol["rules"],
                  "Missing confirmation is not contradictory evidence. Early developing evidence does not mean READY.",
                  "Report actual strengthening or weakening without waiting for every indicator. Do not count indicators.",
                  "A missing history or accepted thesis remains missing; never invent the preceding view.",
                  "Every claim cites the evidence map keys. coverage:input supports missing input statements only.",
                  "Use at most one short sentence per claim. Empty sections are allowed."],
        "semantic_limits": [item["cannot_support"] for item in protocol["inspection"]],
        "previous_accepted_thesis": packet.previous_thesis,
        "evidence": evidence,
    })


def validate_observation(raw, packet):
    error = cognitive_output_error(raw, OBSERVER_SCHEMA, packet)
    if error:
        return error
    return validate_desk_memo({
        "side": "PUT" if raw["developing_view"] == "PUT_DEVELOPING" else "CALL",
        "state": "UNRESOLVED", "claim": raw["observation"],
        "support": raw["strengthening"], "contradiction": raw["contradiction"],
        "missing_confirmation": raw["missing_confirmation"],
        "temporal_change": raw["weakening"], "internal_tension": [],
    }, packet, "PUT" if raw["developing_view"] == "PUT_DEVELOPING" else "CALL")


def event_desk_input(packet, side, role):
    """Desk view of the same event universe, retaining current neutral context.

    Exact original temporal records replace duplicated metric representations.
    No event identity, value or event provenance is removed.
    """
    if side not in {"CALL", "PUT"} or role not in {"side_specialist", "side_falsifier"}:
        raise ValueError("Explicit side and desk role required")
    payload = observer_input(packet)
    payload["role"] = protocol_for(role)["role"]
    payload["side"] = side
    payload["neutral_context"] = {k: deepcopy(v) for k, v in packet.canonical_state.items() if not k.startswith("ose_")}
    payload["rules"].extend([
        "Support supports the assigned side. Contradiction requires observed opposing evidence, not missing confirmation.",
        "Do not assert absence of premium change without checking the supplied before/after record.",
        "Neutral context is the compiler's current projection; factual claims must cite supplied original event records.",
    ])
    return payload
