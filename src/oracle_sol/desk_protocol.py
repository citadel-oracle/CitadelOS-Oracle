"""Provider-neutral symmetric desk inputs. No scheduler, market math or execution.

Models produce hypotheses, never additional canonical evidence. Side identity is
the only difference in the neutral inputs supplied to mirrored desks.
"""
from copy import deepcopy
import json
import re

from src.oracle_sol.ayush_analysis_protocol import protocol_for
from src.oracle_sol.cognitive_output_validation import cognitive_output_error
from src.oracle_sol.evidence_gate import EvidenceGate


CLAIM_SCHEMA = {
    "type": "object",
    "properties": {
        "claim": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["claim", "evidence_ids"], "additionalProperties": False,
}
DESK_MEMO_SCHEMA = {
    "type": "object",
    "properties": {
        "side": {"type": "string", "enum": ["CALL", "PUT"]},
        "state": {"type": "string", "enum": ["SUPPORTED", "WEAKENING", "CONTRADICTED", "UNRESOLVED"]},
        "claim": CLAIM_SCHEMA,
        **{name: {"type": "array", "items": CLAIM_SCHEMA, "maxItems": 3}
           for name in ("support", "contradiction", "missing_confirmation", "temporal_change", "internal_tension")},
    },
    "required": ["side", "state", "claim", "support", "contradiction", "missing_confirmation", "temporal_change", "internal_tension"],
    "additionalProperties": False,
}

DESK_MEMO_SCHEMA["properties"]["support"]["description"] = "Evidence FOR the assigned CALL/PUT market side. Never evidence supporting your falsifier's negative conclusion. CALL premium improving belongs here for CALL."
DESK_MEMO_SCHEMA["properties"]["contradiction"]["description"] = "Observed evidence AGAINST the assigned CALL/PUT market side, not against your memo's conclusion. Missing evidence is not contradiction."
DESK_MEMO_SCHEMA["properties"]["state"]["description"] = "Viability of the assigned market side, not correctness of your argument."
DESK_MEMO_SCHEMA["properties"]["missing_confirmation"]["description"] = "Only absent required observations, never observed evidence against the side. OI/PCR cannot establish buyer identity even if available."
FOCUSED_DESK_SCHEMA = deepcopy(DESK_MEMO_SCHEMA)
for _section in ("support", "contradiction", "missing_confirmation", "temporal_change", "internal_tension"):
    FOCUSED_DESK_SCHEMA["properties"][_section]["maxItems"] = 1


def desk_input(packet, side: str, role: str) -> dict:
    if side not in {"CALL", "PUT"} or role not in {"side_specialist", "side_falsifier"}:
        raise ValueError("Explicit side and desk role required")
    # One universe for both desks, including opposing evidence. No prefix filter
    # may accidentally hide a contradiction or split exact-security continuity.
    evidence = {eid: packet.resolve_evidence(eid) for eid in sorted(packet.valid_evidence_ids)}
    if any(value is None for value in evidence.values()):
        raise ValueError("UNRESOLVED_CANONICAL_EVIDENCE")
    for eid, item in evidence.items():
        item["evidence_id"] = eid
    return deepcopy({
        "protocol": protocol_for(role), "side": side,
        "session_id": packet.session_id, "input_revision": packet.revision,
        "packet_hash": packet.packet_hash,
        "neutral_context": packet.canonical_state,
        "evidence": evidence,
        "valid_evidence_ids": sorted(packet.valid_evidence_ids),
        "citation_rule": "Cite evidence_id / valid_evidence_ids only. source_id identifies the upstream frame and is NOT a valid claim citation.",
        "claim_rules": [
            "Every nonempty claim, including missing confirmation, needs resolving evidence_ids. An absent field is not a new evidence ID.",
            "Leave a section empty when this packet cannot substantiate it. Do not invent a missing-confirmation claim to fill the schema.",
            "One level observation does not establish strengthening, weakening, demand or follow-through. Cite supplied temporal evidence for change claims.",
            "Continuity and response records are context, not additional citation IDs. Cite only valid_evidence_ids and preserve security identity.",
            "Use coverage:input for known missing inputs only. Missing confirmation is not contradiction. Support must support the ASSIGNED side, not its opponent.",
            "Describe early strengthening or weakening when actual temporal evidence supports it; do not demand broad confirmation to notice a developing case. Developing is not READY.",
            "Do not equate premium change with buyer identity or absence of demand. Explain the observed response, its alternative explanations, and its limits.",
        ],
        "unseen_event_ids": packet.unseen_event_ids,
        "temporal_relationships": packet.temporal_relationships,
        "option_continuity": packet.option_continuity,
        "aggression_response_sequence": packet.aggression_response_sequence,
        "previous_accepted_thesis": packet.previous_thesis,
    })


def validate_desk_memo(raw: dict, packet, side: str) -> str | None:
    error = cognitive_output_error(raw, DESK_MEMO_SCHEMA, packet)
    if error:
        return error
    if raw["side"] != side:
        return "DESK_SIDE_MISMATCH"
    for section in ("support", "contradiction", "temporal_change"):
        if any(item["evidence_ids"] and set(item["evidence_ids"]) == {"coverage:input"}
               for item in raw[section]):
            return "MISSING_INPUT_IS_NOT_MARKET_EVIDENCE"
    if raw["state"] != "UNRESOLVED" and set(raw["claim"]["evidence_ids"]) == {"coverage:input"}:
        return "MISSING_INPUT_IS_NOT_MARKET_EVIDENCE"
    claims = [raw["claim"]]
    for name in ("support", "contradiction", "missing_confirmation", "temporal_change", "internal_tension"):
        claims.extend(raw[name])
    gate = EvidenceGate(None)  # Existing read-only validation path; never commits.
    for claim in claims:
        refs = set(claim["evidence_ids"])
        if claim["claim"].strip() and not refs:
            return "CLAIM_WITHOUT_EVIDENCE"
        text = claim["claim"].lower()
        if refs == {"coverage:input"}:
            # Absence of an absorption input is not an absorption assertion.
            # This bypass is only for non-directional coverage statements;
            # support/contradiction use was rejected above.
            if (any(term in text for term in ("unavailable", "missing", "not available"))
                    and not any(term in text for term in ("bullish", "bearish", "buying", "selling", "ready", "supports call", "supports put"))):
                continue
            return "INPUT_COVERAGE_CLAIM_OUT_OF_SCOPE"
        # Present premium metrics do not establish a historical change (or its
        # absence). Exact failure captured in Arena #12; require the cited
        # before/after contract evidence, never an uncited packet-wide union.
        for side_name, pricing_key in (("call", "ce_pricing"), ("put", "pe_pricing")):
            change_claim = re.search(
                rf"(?:no\s+)?increase in {side_name} premium|{side_name} premium (?:rose|fell|increased|decreased)", text)
            if change_claim:
                temporal = []
                for ref in refs:
                    record = packet.resolve_evidence(ref) or {}
                    value = record.get("value")
                    if isinstance(value, dict):
                        pair = value.get("supporting_values", {}).get("diffs", {}).get(pricing_key, {})
                        if isinstance(pair.get("before"), dict) and isinstance(pair.get("after"), dict):
                            if pair["before"].get("security_id") == pair["after"].get("security_id"):
                                temporal.append(pair)
                if not temporal:
                    return "PREMIUM_CHANGE_WITHOUT_TEMPORAL_EVIDENCE"
                pairs = [p for p in temporal if
                         isinstance(p["before"].get("ltp"), (int, float)) and
                         isinstance(p["after"].get("ltp"), (int, float))]
                if not pairs:
                    return "PREMIUM_CHANGE_WITHOUT_TEMPORAL_EVIDENCE"
                up = re.search(rf"{side_name} premium (?:rose|increased)", text)
                down = re.search(rf"{side_name} premium (?:fell|decreased)", text)
                if ((up and any(p["after"]["ltp"] <= p["before"]["ltp"] for p in pairs)) or
                        (down and any(p["after"]["ltp"] >= p["before"]["ltp"] for p in pairs))):
                    return "CLAIM_CONTRADICTS_RECORDED_PREMIUM_CHANGE"
                if f"no increase in {side_name} premium" in text and any(
                    isinstance(p["before"].get("ltp"), (int, float)) and
                    isinstance(p["after"].get("ltp"), (int, float)) and
                    p["after"]["ltp"] > p["before"]["ltp"] for p in temporal
                ):
                    return "CLAIM_CONTRADICTS_RECORDED_PREMIUM_CHANGE"
        # These are level observations, not demand or temporal price response.
        # Guard the exact failure observed in the recorded Arena response; do
        # not calculate a new signal or coerce the memo into the opposing side.
        premium_levels = {"metric:ce_atm_premium", "metric:pe_atm_premium", "metric:atm_strike",
                          "metric:ce_security_id", "metric:pe_security_id"}
        if refs and refs <= premium_levels and any(word in text for word in ("demand", "buying pressure", "selling pressure")):
            return "PREMIUM_LEVEL_IS_NOT_DEMAND"
        basis_levels = {"metric:basis", "metric:spot_price", "metric:futures_price"}
        if refs and refs <= basis_levels and "basis" in text and any(word in text for word in ("bullish", "bearish")):
            return "BASIS_LEVEL_IS_NOT_DIRECTION"
        # Validate each claim separately. Unioning all desk citations would let
        # one grounded sentence launder another unsupported directional claim.
        error = gate._validate_semantic_claims({
            "market_story": {"narrative": claim["claim"]},
            f"{side.lower()}_case": {"argument": claim["claim"], "evidence_ids": list(refs)},
            "why_now": [claim["claim"] + " [" + ", ".join(sorted(refs)) + "]"],
            "synthesis": {"state": side if raw["state"] == "SUPPORTED" else ""},
        }, packet, refs)
        if error:
            return error
    return None


def compact_desk_input(payload: dict) -> dict:
    """Lossless metadata dictionary encoding. Values and citation IDs stay exact.

    Repeated provenance/semantic metadata is stored once, never discarded.
    This is a prompt presentation format, not another evidence universe.
    """
    result = deepcopy(payload)
    metadata = {}
    identities = {}
    for eid, row in result["evidence"].items():
        common = {key: value for key, value in row.items() if key not in {"value", "field", "evidence_id"}}
        key = json.dumps(common, sort_keys=True, separators=(",", ":"))
        if key not in identities:
            identity = f"p{len(identities)}"
            identities[key] = identity
            metadata[identity] = common
        result["evidence"][eid] = {
            "field": row.get("field"), "value": row.get("value"),
            "metadata_ref": identities[key],
        }
    result["evidence_metadata"] = metadata
    result["evidence_encoding"] = "Evidence map keys are citation IDs. Merge each row with evidence_metadata[metadata_ref] for its original source, time, meaning and limitations. Metadata references are not citation IDs."
    return result


def synthesis_desks(packet, call_memo: dict, put_memo: dict) -> list[dict]:
    """Blind model identity; alternate presentation using authoritative revision."""
    for side, memo in (("CALL", call_memo), ("PUT", put_memo)):
        error = validate_desk_memo(memo, packet, side)
        if error:
            raise ValueError(error)
    ordered = [call_memo, put_memo] if packet.revision % 2 == 0 else [put_memo, call_memo]
    return [{"status": "UNTRUSTED_MODEL_HYPOTHESIS", "memo": deepcopy(memo)} for memo in ordered]
