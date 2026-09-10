"""Offline fact-first projection; no provider, ranking, scheduler or commit path.

The full audit object stays outside model context. This module does not certify
historical desk quality or select market states.
"""
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import re

from src.oracle_sol.cognitive_output_validation import cognitive_output_error
from src.oracle_sol.desk_protocol import validate_desk_memo
from src.oracle_sol.temporal_observer_protocol import validate_observation
from src.oracle_sol.evidence_gate import EvidenceGate
from src.oracle_sol.provenance_guard import ProvenanceGuard


INSTRUCTIONS = """Return a decision, not an inventory or merged market report.
FACTS are recorded Oracle observations; ASSERTIONS are fallible model views, not facts.
Audit their meaning against FACTS. COVERAGE describes missing projection inputs, not opposing evidence.
Select only conclusions that change the present interpretation. Do not enumerate or rephrase every memo.
Preserve the strongest opposing case and distinguish absent confirmation from observed contradiction.
One meaningful early relationship may justify DEVELOPING; do not count agreeing indicators.
Thesis support is not opportunity maturity: later agreement may accompany a mature move.
Premium movement does not identify buyers/demand. Basis, OI, PCR and GEX do not establish direction alone.
No invented levels, confidence, thresholds or institutional attribution. Keep exact security continuity.
Same-time observations do not establish a causal order. Unknown maturity stays UNKNOWN.
Every claim cites original IDs inline [id] and in evidence_ids. No peer/model citations or code decoding.
Empty sections are allowed. Missing data is not itself WAIT or NO_TRADE; provider failure is UNAVAILABLE.
Give concise final conclusions only; never output an inventory of the input assertions."""


def _enum(values):
    return {"type": "string", "enum": values.split()}


CLAIM = {"type": "object", "properties": {"claim": {"type": "string", "description": "One concise conclusion. Include its original canonical evidence IDs inline in square brackets, matching evidence_ids. Never infer demand from quotes, direction from basis, or contradiction from missing data."},
         "evidence_ids": {"type": "array", "items": {"type": "string"}}},
         "required": ["claim", "evidence_ids"], "additionalProperties": False}
SECTIONS = ("why_now", "call_case", "put_case", "missing_confirmation", "contradiction",
            "option_response", "internal_tension", "what_changed", "watch_next", "maturity_reason")
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "state": _enum("CALL PUT CALL_DEVELOPING PUT_DEVELOPING REVERSAL WAIT NO_TRADE UNAVAILABLE"),
        "thesis_evolution": _enum("EARLY_POSSIBILITY DEVELOPING STRENGTHENING WEAKENING REVERSAL_WATCH UNRESOLVED"),
        "opportunity_maturity": _enum("EMERGING ESTABLISHED MATURE UNKNOWN"),
        **{name: {"type": "array", "items": {"$ref": "#/$defs/claim"}} for name in SECTIONS},
    },
    "required": ["state", "thesis_evolution", "opportunity_maturity", *SECTIONS],
    "$defs": {"claim": CLAIM},
}
# Portable wire schema; local cardinality remains enforced even if a provider's
# constrained subset does not support maxItems. No confidence or market weights.


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _time(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return result


def _claims(value):
    if isinstance(value, dict):
        if set(value) == {"claim", "evidence_ids"}:
            yield value
        else:
            for child in value.values():
                yield from _claims(child)
    elif isinstance(value, list):
        for child in value:
            yield from _claims(child)


def build_brief(packet, receipts, *, as_of, fact_only=False):
    """One observer plus symmetric desk receipts, bound by real session/revision.

    Explicit as_of comes from the frozen source, never wall-clock compile time.
    Records are not silently upgraded to quality-accepted. Their raw inputs remain
    verbatim in audit, including elaborations omitted from the active prompt.
    """
    cutoff = _time(as_of)
    if fact_only and receipts:
        raise ValueError("FACT_ONLY_CANNOT_IMPORT_MODEL_ASSERTIONS")
    if cutoff.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat() != packet.session_id:
        raise ValueError("AS_OF_SESSION_MISMATCH")
    if packet.previous_thesis is not None:
        previous = packet.previous_thesis
        if (not isinstance(previous, dict) or previous.get("session_id") != packet.session_id
                or not EvidenceGate.revalidate_retained(previous).is_valid):
            raise ValueError("PREVIOUS_THESIS_NOT_REVALIDATED")
    keyed = {}
    all_ids = set(packet.unseen_event_ids) | {"coverage:input"}
    for receipt in receipts:
        key = (receipt["role"], receipt.get("side"))
        if key in keyed:
            raise ValueError("DUPLICATE_ROLE_RECEIPT")
        if receipt["session_id"] != packet.session_id or receipt["revision"] != packet.revision:
            raise ValueError("MEMO_SESSION_REVISION_MISMATCH")
        raw = receipt["output"]
        error = (validate_observation(raw, packet) if key == ("observer", None)
                 else validate_desk_memo(raw, packet, receipt.get("side")))
        if error:
            raise ValueError(error)
        for claim in _claims(raw):
            all_ids.update(claim["evidence_ids"])
        keyed[key] = receipt
    expected = {("observer", None), *( (r,s) for r in ("specialist","falsifier") for s in ("CALL","PUT") )}
    if not fact_only and set(keyed) != expected:
        raise ValueError("MIRRORED_ROLES_REQUIRED")

    facts, coverage, original = [], None, {}
    for eid in all_ids:
        if eid not in packet.valid_evidence_ids:
            raise ValueError("ORPHAN_EVIDENCE")
        row = packet.resolve_evidence(eid)
        if row is None:
            raise ValueError("ORPHAN_EVIDENCE")
        ProvenanceGuard.assert_vob_free_fail_closed(row)
        if row.get("field") in {"external_event", "external_quote"}:
            # Registry summaries alone do not carry verification evidence.
            # Do not manufacture a verified label from RECORDED availability.
            raise ValueError("EXTERNAL_VERIFICATION_PROOF_REQUIRED")
        original[eid] = deepcopy(row)
        value = row.get("value")
        if eid == "coverage:input":
            if _time(row["timestamp"]) > cutoff:
                raise ValueError("FUTURE_EVIDENCE")
            coverage = {"evidence_id": eid, "scope": "PROJECTED_FIELDS_ONLY_NOT_ABSENCE_FROM_EVENTS", "value": deepcopy(value)}
        elif isinstance(value, dict) and "event_id" in value:
            if value["event_id"] != eid or value["session_date"] != packet.session_id:
                raise ValueError("EVENT_ID_SESSION_MISMATCH")
            at = _time(value["timestamp_utc"])
            if at > cutoff:
                raise ValueError("FUTURE_EVIDENCE")
            if not value.get("provenance_hash"):
                raise ValueError("MISSING_PROVENANCE")
            # Preserve before/after identities and times; do not stitch rotated
            # quotes. Rotation stays visible, but is not continuous price change.
            support = deepcopy(value["supporting_values"])
            for pair in support.get("diffs", {}).values():
                if isinstance(pair, dict):
                    before, after = pair.get("before"), pair.get("after")
                    if isinstance(before, dict) and isinstance(after, dict) and "source_timestamp" in before:
                        if not (_time(before["source_timestamp"]) <= _time(after["source_timestamp"]) <= at):
                            raise ValueError("INVALID_CONTRACT_CHRONOLOGY")
            facts.append({"evidence_id": eid, "at": value["timestamp_utc"],
                          "kind": value["event_type"], "security_id": value["security_id"],
                          "expiry": value["expiry"], "strike": value["strike"], "values": support})
            # Local meaning, not a directional filter. Keep every value and ID.
            limits = {
                "SENSORIUM_DELTA": "CE and PE fields are quotes and IV, not aggressor trades or buyer demand. Each contract IV is separate from aggregate ATM IV. Compare only equal security_id values.",
                "BASIS_SHIFT": "Observed futures-minus-spot spread change only. No bullish/bearish pressure or option carry-advantage category is supplied.",
                "VOLATILITY_SURFACE_SHIFT": "Aggregate ATM IV and straddle context are not the individual CE/PE contract IVs. No expected-move calculation is supplied when null.",
                "STATE_TRANSITION": "Historical data-state record, not proof of current exchange trading hours.",
            }
            if value["event_type"] in limits:
                facts[-1]["limitations"] = limits[value["event_type"]]
        else:
            # No generic flattening of unrecognized/external evidence. Keep its
            # meaning and reject unknown/full-date timestamps, not fake freshness.
            if not row.get("timestamp") or _time(row["timestamp"]) > cutoff:
                raise ValueError("UNKNOWN_OR_FUTURE_EVIDENCE_TIME")
            facts.append({"evidence_id": eid, "at": row["timestamp"], "record": deepcopy(row)})
    facts.sort(key=lambda r: (_time(r["at"]), r["evidence_id"]))
    assertions = []
    for key in ([] if fact_only else [("observer",None), ("specialist","CALL"), ("falsifier","CALL"), ("specialist","PUT"), ("falsifier","PUT")]):
        raw = keyed[key]["output"]
        names = ("observation","strengthening","weakening","contradiction","missing_confirmation") if key[0] == "observer" else ("claim","contradiction","missing_confirmation","internal_tension")
        assertions.append({"role": key[0], "side": key[1], "type": "MODEL_ASSERTION_NOT_FACT",
                           **{name: deepcopy(raw[name]) for name in names}})
    brief = {"session": packet.session_id, "revision": packet.revision, "as_of": as_of,
             "evidence_identity": digest(original),
             "previous_accepted_thesis": deepcopy(packet.previous_thesis),
             "facts": facts, "coverage": coverage, "assertions": assertions,
             "temporal_note": "Event times are source times. Same-time rows have no causal ordering. Earlier data health is not current exchange-session status."}
    receipt_issues = []
    for key, receipt in keyed.items():
        errors = sorted({error for claim in _claims(receipt["output"])
                         if (error := EvidenceGate.validate_factual_claim(claim["claim"], set(claim["evidence_ids"]), packet))})
        if errors:
            receipt_issues.append({"role": key[0], "side": key[1], "errors": errors})
    audit = {"packet_hash": packet.packet_hash, "brief_hash": digest(brief),
             "original_evidence": original, "original_receipts": deepcopy(receipts),
             "receipt_validation_issues": receipt_issues,
             "omission_policy": "Desk support/temporal elaborations remain here; ALL their evidence remains in facts. No directional selection.",
             "production_activation": False}
    return brief, audit


def build_temporal_analyst_input(packet, *, as_of):
    """Single symmetric analyst experiment: no inherited peer interpretation.

    Same canonical projection, same output validator, no new scheduler or provider.
    CALL/PUT sections and budgets remain symmetric. Facts are not side-filtered.
    """
    return build_brief(packet, [], as_of=as_of, fact_only=True)


def require_retest_eligible(brief, audit):
    """No network here. Diagnostic projections with rejected input stay offline."""
    if digest(brief) != audit["brief_hash"]:
        raise ValueError("BRIEF_IDENTITY_MISMATCH")
    if audit["receipt_validation_issues"]:
        raise ValueError("UPSTREAM_ASSERTIONS_UNQUALIFIED")
    # This permits subsequent explicit review/authorization, not model acceptance.
    return True


def validate_brief_output(raw, packet, brief):
    error = cognitive_output_error(raw, SCHEMA, packet)
    if error:
        return error
    if brief["session"] != packet.session_id or brief["revision"] != packet.revision:
        return "OUTPUT_CONTEXT_MISMATCH"
    supplied = {r["evidence_id"] for r in brief["facts"]} | {"coverage:input"}
    if digest({eid: packet.resolve_evidence(eid) for eid in supplied}) != brief["evidence_identity"]:
        return "FROZEN_EVIDENCE_CHANGED"
    gate = EvidenceGate(None)
    for section in SECTIONS:
        if len(raw[section]) > (3 if section == "why_now" else 2):
            return "EXCESSIVE_SECTION_ITEMS"
        for claim in raw[section]:
            refs = set(claim["evidence_ids"])
            inline = {eid.strip() for group in re.findall(r"\[([^\]]+)\]",claim["claim"]) for eid in group.split(",")}
            if not refs or refs != inline or not refs <= supplied:
                return "CLAIM_CITATION_MISMATCH"
            if refs == {"coverage:input"} and section not in {"missing_confirmation", "watch_next"}:
                return "MISSING_IS_NOT_MARKET_EVIDENCE"
            memo = {"side": "PUT" if section == "put_case" else "CALL", "state": "UNRESOLVED", "claim": claim,
                    **{k: [] for k in ("support","contradiction","missing_confirmation","temporal_change","internal_tension")}}
            error = validate_desk_memo(memo, packet, memo["side"])
            if error:
                return error
            error = gate.validate_factual_claim(claim["claim"], refs, packet)
            if error:
                return error
    missing = {c["claim"] for c in raw["missing_confirmation"]}
    if missing & {c["claim"] for c in raw["contradiction"]}:
        return "MISSING_IS_NOT_CONTRADICTION"
    if raw["state"] not in {"UNAVAILABLE","WAIT"} and not raw["why_now"]:
        return "STATE_WITHOUT_GROUNDED_REASON"
    if raw["opportunity_maturity"] != "UNKNOWN" and not raw["maturity_reason"]:
        return "MATURITY_WITHOUT_EVIDENCE"
    return None
