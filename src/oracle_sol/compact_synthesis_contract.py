"""Offline candidate contract. Not wired to providers or production orchestration.

Claim references remove repeated prose, not evidence. No state is calculated here.
"""
from copy import deepcopy
import re

from src.oracle_sol.cognitive_output_validation import cognitive_output_error
from src.oracle_sol.desk_protocol import validate_desk_memo, compact_desk_input
from src.oracle_sol.temporal_observer_protocol import validate_observation

SECTIONS = ("why_now", "call_case", "put_case", "missing_confirmation", "contradiction",
            "option_confirmation_or_divergence", "internal_tension", "what_changed", "what_to_watch_next")
INSTRUCTIONS = (
    "Synthesize the validated but fallible memos; do not write another market report. "
    "Verify claims against the evidence lookup. Model opinions are not canonical evidence. "
    "Write each distinct claim once; sections reference claim indexes. Every claim includes original "
    "canonical evidence IDs inline in square brackets and matching evidence_ids. "
    "Missing confirmation is not contradiction. Early partial temporal evidence may support a developing "
    "view without broad agreement; developing is not READY. More confirmation can arrive late. "
    "Do not count indicators. No confidence, invented levels, buyer identity from OI, PCR/GEX direction, "
    "positive-basis bullish shortcut, premium-level demand, or VOB evidence. "
    "Preserve missing inputs, source times and exact security identity. Empty sections are allowed. "
    "Reject both cases if needed; never fabricate a prior thesis."
)

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "state": {"type": "string", "enum": ["CALL", "PUT", "CALL_DEVELOPING", "PUT_DEVELOPING", "REVERSAL", "WAIT", "NO_TRADE", "UNAVAILABLE"]},
        "temporal_stage": {"type": "string", "enum": ["EARLY_POSSIBILITY", "DEVELOPING", "READY", "STRENGTHENING", "WEAKENING", "REVERSAL_WATCH", "UNRESOLVED"]},
        "claims": {"type": "array", "maxItems": 10, "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"claim": {"type": "string", "minLength": 1},
                           "evidence_ids": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"type": "string"}}},
            "required": ["claim", "evidence_ids"]}},
        **{name: {"type": "array", "maxItems": 3 if name == "why_now" else 2,
                  "uniqueItems": True, "items": {"type": "integer", "minimum": 0}}
           for name in SECTIONS},
    },
    "required": ["state", "temporal_stage", "claims", *SECTIONS],
}


def build_input(packet, observer, desks):
    """Validate before compacting; keep every original claim and its section role."""
    if observer is None:
        raise ValueError("VALIDATED_OBSERVER_MISSING")
    error = validate_observation(observer, packet)
    if error:
        raise ValueError(error)
    if {side for side, role, memo in desks} != {"CALL", "PUT"}:
        raise ValueError("MIRRORED_DESKS_REQUIRED")
    roles = {side: sorted(role for s, role, _ in desks if s == side) for side in ("CALL", "PUT")}
    if roles["CALL"] != roles["PUT"]:
        raise ValueError("ASYMMETRIC_DESKS")
    claims, identities = [], {}

    def encode(value):
        if isinstance(value, dict) and set(value) == {"claim", "evidence_ids"}:
            key = (value["claim"], tuple(value["evidence_ids"]))
            if key not in identities:
                identities[key] = len(claims)
                claims.append(deepcopy(value))
            return {"claim_ref": identities[key]}
        if isinstance(value, dict):
            return {k: encode(v) for k, v in value.items()}
        if isinstance(value, list):
            return [encode(v) for v in value]
        return value

    memos = []
    for side, role, memo in desks:
        error = validate_desk_memo(memo, packet, side)
        if error:
            raise ValueError(error)
        memos.append({"side": side, "role": role, "memo": encode(memo)})
    encoded_observer = encode(observer)
    ids = set(packet.unseen_event_ids) | {"coverage:input"}
    ids.update(eid for claim in claims for eid in claim["evidence_ids"])
    evidence = {eid: deepcopy(packet.resolve_evidence(eid)) for eid in sorted(ids)}
    if any(row is None for row in evidence.values()):
        raise ValueError("UNRESOLVED_EVIDENCE")
    citation_ids = sorted(ids)
    for claim in claims:
        claim["citation_codes"] = [citation_ids.index(eid) for eid in claim.pop("evidence_ids")]
    encoded = compact_desk_input({"evidence": evidence})
    return {"session_id": packet.session_id, "revision": packet.revision,
            "packet_hash": packet.packet_hash, "previous_accepted_thesis": packet.previous_thesis,
            "observer": encoded_observer, "desks": memos if packet.revision % 2 == 0 else list(reversed(memos)),
            "memo_claims": claims, "citation_ids": citation_ids,
            "citation_encoding": "Memo citation_codes index citation_ids. Output uses original IDs, never codes.",
            "evidence_lookup": encoded["evidence"], "evidence_metadata": encoded["evidence_metadata"],
            "evidence_encoding": encoded["evidence_encoding"],
            "memo_status": "VALIDATED_STRUCTURE_AND_CURRENT_GATES_NOT_CANONICAL_FACTS"}


def validate_output(raw, packet):
    error = cognitive_output_error(raw, SCHEMA, packet)
    if error:
        return error
    used = set()
    for section in SECTIONS:
        for index in raw[section]:
            if index >= len(raw["claims"]):
                return "ORPHAN_CLAIM_REFERENCE"
            used.add(index)
    if used != set(range(len(raw["claims"]))):
        return "UNUSED_CLAIM"
    if set(raw["missing_confirmation"]) & set(raw["contradiction"]):
        return "MISSING_IS_NOT_CONTRADICTION"
    for claim in raw["claims"]:
        inline = {eid.strip() for group in re.findall(r"\[([^\]]+)\]", claim["claim"]) for eid in group.split(",")}
        if inline != set(claim["evidence_ids"]):
            return "INLINE_EVIDENCE_MISMATCH"
        memo = {"side": "CALL", "state": "UNRESOLVED", "claim": claim,
                "support": [], "contradiction": [], "missing_confirmation": [],
                "temporal_change": [], "internal_tension": []}
        error = validate_desk_memo(memo, packet, "CALL")
        if error:
            return error
    for name in ("call_case", "put_case", "contradiction", "what_changed"):
        if any(set(raw["claims"][i]["evidence_ids"]) == {"coverage:input"} for i in raw[name]):
            return "MISSING_INPUT_IS_NOT_MARKET_EVIDENCE"
    if raw["state"] not in {"UNAVAILABLE", "WAIT"} and not raw["why_now"]:
        return "STATE_WITHOUT_GROUNDED_REASON"
    return None
