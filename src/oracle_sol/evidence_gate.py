"""Evidence Gate: Zero-Trust Validation Pipeline for Model Cognition.

Validates all Qwen 3.5 9B reasoning outputs before committing to durable memory:
1. JSON Schema & Structure Validation
2. Grounding & Evidence-Reference Verification:
   Ensures EVERY cited evidence ID exists in the input BrainPacket's `valid_evidence_ids`.
   If the model cites hallucinated or unverified IDs: REJECT with MODEL_CLAIM_UNSUPPORTED.
3. Prohibited Broker/Execution Terminology Check
4. Session & Revision Monotonicity Check
5. Durable Thesis Commit:
   Advances the LocalBrain cursor ONLY upon full verification.
   If validation fails, the cursor DOES NOT ADVANCE.
"""

from __future__ import annotations

import hashlib
import json
import logging
from copy import deepcopy
from types import SimpleNamespace
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from src.oracle_sol.brain_packet_compiler import BrainPacket
from src.oracle_sol.thesis_graph import (
    ThesisGraph,
    ThesisMarketState,
    ThesisNode,
    ThesisStatus,
)

logger = logging.getLogger(__name__)

PROHIBITED_BROKER_INSTRUCTIONS = {
    "place_order",
    "buy_order",
    "sell_order",
    "dhan_token",
    "execute_trade",
    "modify_order",
    "cancel_order",
    "broker_submission",
}


@dataclass(frozen=True)
class GateValidationResult:
    """The outcome of the Evidence Gate verification."""

    is_valid: bool
    status: str                         # COMMITTED | MODEL_CLAIM_UNSUPPORTED | SCHEMA_INVALID | PROVENANCE_MISMATCH
    error_details: Optional[str] = None
    unsupported_evidence_ids: List[str] = None
    committed_thesis: Optional[ThesisNode] = None


class EvidenceGate:
    """Zero-trust gatekeeper guarding the Citadel Thesis Graph."""

    def __init__(self, thesis_graph: ThesisGraph) -> None:
        self.thesis_graph = thesis_graph

    @classmethod
    def revalidate_retained(cls, node: Dict[str, Any]) -> GateValidationResult:
        try:
            return cls._revalidate_retained(node)
        except (TypeError, ValueError, AttributeError, KeyError):
            return GateValidationResult(False, "REJECTED", "RETAINED_VALIDATION_MALFORMED")

    @classmethod
    def _revalidate_retained(cls, node: Dict[str, Any]) -> GateValidationResult:
        """Read-only semantic revalidation, never a commit or cursor update.

        Old flattened nodes lost claim-level refs and packet context. They cannot
        be called LAST VALID using today's snapshot as a substitute.
        """
        retained = node.get("semantic_validation") or {}
        raw = retained.get("response")
        context = retained.get("context")
        if retained.get("input_receipt") is not None:
            from src.oracle_sol.luna_input_receipt import valid_binding
            if not valid_binding(retained["input_receipt"], raw, node.get("session_id"),
                                 node.get("input_revision"), node.get("model")):
                return GateValidationResult(False, "REJECTED", "INPUT_RECEIPT_MISMATCH")
        gate = cls(None)
        if not isinstance(raw, dict) or not isinstance(context, dict):
            # Run text rules even when the original evidence was not retained.
            raw = {key: node.get(key, "") for key in (
                "market_story", "call_case", "put_case", "reversal_analysis", "counterfactual")}
            raw.update(synthesis={"state": node.get("state")}, why_now=node.get("why_now") or [])
            error = gate._validate_semantic_claims(raw, SimpleNamespace(canonical_state={}, canonical_levels=[]), set())
            return GateValidationResult(False, "REJECTED", error or "LEGACY_VALIDATION_CONTEXT_MISSING")
        if retained.get("input_hash") != node.get("input_hash") or retained.get("revision") != node.get("input_revision"):
            return GateValidationResult(False, "REJECTED", "RETAINED_VALIDATION_IDENTITY_MISMATCH")
        packet = SimpleNamespace(canonical_state=context.get("canonical_state", {}),
                                 canonical_levels=context.get("canonical_levels", []))
        raw = deepcopy(raw)
        for section, field in (("market_story", "narrative"), ("call_case", "argument"),
                               ("put_case", "argument"), ("reversal_analysis", "absorption_or_exhaustion")):
            if section in node:
                original = raw.get(section)
                raw[section] = {**original, field: node[section]} if isinstance(original, dict) else node[section]
        raw["why_now"] = node.get("why_now", raw.get("why_now", []))
        error = gate._validate_semantic_claims(raw, packet, set(context.get("cited_ids", [])))
        return GateValidationResult(not bool(error), "VALID" if not error else "REJECTED", error)

    def validate_and_commit(
        self,
        raw_response: Optional[Dict[str, Any]],
        packet: BrainPacket,
        model_name: str,
        system_prompt: str,
        commit_guard: Optional[Callable[[BrainPacket], bool]] = None,
        input_receipt: Optional[Dict[str, Any]] = None,
    ) -> GateValidationResult:
        # 1. Null / Empty Check
        if not raw_response or not isinstance(raw_response, dict):
            logger.warning("EvidenceGate: Model output is empty or not a dict")
            return GateValidationResult(
                is_valid=False,
                status="SCHEMA_INVALID",
                error_details="Model response is empty or unparseable JSON",
            )

        if model_name == "gpt-5.6-luna":
            from src.oracle_sol.luna_input_receipt import valid_binding
            if not valid_binding(input_receipt, raw_response, packet.session_id, packet.revision, model_name):
                return GateValidationResult(False, "INPUT_RECEIPT_MISMATCH", "Exact request/output binding missing or invalid.")
            if "hypotheses" not in raw_response or "conclusions" not in raw_response:
                return GateValidationResult(False, "SCHEMA_INVALID", "Luna competing-hypotheses contract required.")

        # Route qualified competing hypotheses contract (Luna Production)
        if "hypotheses" in raw_response and "conclusions" in raw_response:
            return self._validate_and_commit_competing_hypotheses(
                raw_response=raw_response,
                packet=packet,
                model_name=model_name,
                system_prompt=system_prompt,
                commit_guard=commit_guard,
                input_receipt=input_receipt,
            )

        # 2. Schema Structure Verification
        logger.info("EvidenceGate received keys: %s", list(raw_response.keys()))
        section_aliases = {
            "observer": ["observer", "what_changed", "observation", "market_observer"],
            "market_story": ["market_story", "narrative", "story"],
            "call_case": ["call_case"],
            "put_case": ["put_case"],
            "no_trade_case": ["no_trade_case"],
            "reversal_analysis": ["reversal_analysis", "reversal", "failed_move_analysis"],
            "reversal_watch": ["reversal_watch", "reversal_monitoring", "reversal_signals"],
            "option_buyer_analysis": ["option_buyer_analysis", "option_buyer_analyst", "option_buyer_view"],
            "contradictions": ["contradictions", "skeptic", "counter_evidence"],
            "temporal_analysis": ["temporal_analysis", "temporal_analyst"],
            "external_context": ["external_context", "external_context_analyst"],
            "counterfactual": ["counterfactual", "counterfactual_reasoning"],
            "human_miss_candidate": ["human_miss_candidate", "human_miss", "subtle_relationship"],
            "synthesis": ["synthesis"],
        }
        for canon_sec, aliases in section_aliases.items():
            found = False
            for a in aliases:
                if a in raw_response:
                    found = True
                    if a != canon_sec and canon_sec not in raw_response:
                        raw_response[canon_sec] = raw_response[a]
                    break
            if not found:
                logger.warning("EvidenceGate: Missing required section '%s'", canon_sec)
                return GateValidationResult(
                    is_valid=False,
                    status="SCHEMA_INVALID",
                    error_details=f"Missing required section: {canon_sec}",
                )

        synth = raw_response.get("synthesis", {})
        if isinstance(synth, str):
            synth = {"state": synth, "supporting_evidence_ids": [], "contradicting_evidence_ids": []}
            raw_response["synthesis"] = synth
        elif not isinstance(synth, dict):
            logger.warning("EvidenceGate: Section 'synthesis' is not a dictionary or string")
            return GateValidationResult(
                is_valid=False,
                status="SCHEMA_INVALID",
                error_details="Section 'synthesis' must be a dictionary containing 'state'",
            )
        state_str = synth.get("state", "").upper()
        valid_states = {s.value for s in ThesisMarketState}
        if state_str not in valid_states:
            logger.warning("EvidenceGate: Invalid synthesis state '%s'", state_str)
            return GateValidationResult(
                is_valid=False,
                status="SCHEMA_INVALID",
                error_details=f"Invalid market state '{state_str}'. Must be one of: {sorted(list(valid_states))}",
            )

        # 3. Prohibited Instruction Check
        raw_text_repr = json.dumps(raw_response).lower()
        for forbidden in PROHIBITED_BROKER_INSTRUCTIONS:
            if forbidden in raw_text_repr:
                logger.error("EvidenceGate: Prohibited broker instruction detected: %s", forbidden)
                return GateValidationResult(
                    is_valid=False,
                    status="PROHIBITED_INSTRUCTION_DETECTED",
                    error_details=f"Model attempted to reference forbidden instruction '{forbidden}'",
                )

        # 4. Evidence-Reference Verification
        valid_ids: Set[str] = set(packet.valid_evidence_ids)
        all_cited_ids: Set[str] = set()

        def collect_ids(obj: Any) -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if "evidence_id" in k and isinstance(v, list):
                        for item in v:
                            if isinstance(item, str):
                                all_cited_ids.add(item.strip())
                    else:
                        collect_ids(v)
            elif isinstance(obj, list):
                for item in obj:
                    collect_ids(item)

        collect_ids(raw_response)

        # 4. Model-Hypothesis Firewall (Section E)
        peer_model_eids = [eid for eid in all_cited_ids if eid.startswith(("qwen:", "gemini:", "model:", "peer:"))]
        if peer_model_eids:
            logger.warning("EvidenceGate: Model cited peer model hypothesis as evidence: %s", peer_model_eids)
            return GateValidationResult(
                is_valid=False,
                status="MODEL_HYPOTHESIS_AS_EVIDENCE_REJECTED",
                error_details=f"GPT cannot cite peer model hypotheses as canonical market evidence: {peer_model_eids}",
                unsupported_evidence_ids=peer_model_eids,
            )

        unsupported = [
            eid for eid in all_cited_ids
            if eid not in valid_ids or (hasattr(packet, "resolve_evidence") and packet.resolve_evidence(eid) is None)
        ]
        if unsupported:
            logger.warning(
                "EvidenceGate: Unsupported claims! Cited IDs not in packet or unresolvable: %s", unsupported
            )
            # FAILED OUTPUT: Cursor MUST NOT advance
            return GateValidationResult(
                is_valid=False,
                status="MODEL_CLAIM_UNSUPPORTED",
                error_details=f"Model cited ungrounded/hallucinated or orphan evidence IDs: {unsupported}",
                unsupported_evidence_ids=unsupported,
            )

        # 5. Semantic Validation V2 (Sections 5, 6, 7)
        semantic_err = self._validate_semantic_claims(raw_response, packet, all_cited_ids)
        if semantic_err:
            logger.warning("EvidenceGate Semantic V2 Rejection: %s", semantic_err)
            return GateValidationResult(
                is_valid=False,
                status="SEMANTIC_CLAIM_REJECTED",
                error_details=semantic_err,
            )

        # 6. Session & Revision Monotonicity Check
        active_thesis = self.thesis_graph.get_active_thesis()
        if active_thesis and packet.revision < active_thesis.input_revision:
            logger.warning(
                "EvidenceGate: Stale revision (%d < %d)",
                packet.revision,
                active_thesis.input_revision,
            )
            return GateValidationResult(
                is_valid=False,
                status="PROVENANCE_MISMATCH",
                error_details=f"Packet revision {packet.revision} is older than active thesis {active_thesis.input_revision}",
            )

        # 7. Construct and Commit Durable ThesisNode
        now_utc = datetime.now(timezone.utc).isoformat()
        prompt_hash = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
        input_hash = packet.packet_hash

        thesis_id = f"thesis_{packet.session_id}_{packet.revision}_{hashlib.sha256(now_utc.encode()).hexdigest()[:8]}"
        cursor_after = packet.unseen_event_ids[-1] if packet.unseen_event_ids else self.thesis_graph.get_cursor()

        def safe_val(parent_key: str, sub_key: str) -> str:
            parent = raw_response.get(parent_key, {})
            if isinstance(parent, str):
                return parent
            elif isinstance(parent, dict):
                return str(parent.get(sub_key, "") or parent.get("argument", "") or parent.get("thesis", "") or parent.get("narrative", "") or parent.get("critique", "") or parent.get("absorption_or_exhaustion", "") or "")
            return ""

        # Extract structured states (Section 7 & 8)
        rev_obj = raw_response.get("reversal_analysis", {})
        rev_watch_obj = raw_response.get("reversal_watch", {})
        syn_obj = raw_response.get("synthesis", {})
        ob_obj = raw_response.get("option_buyer_analysis", {})
        rev_text = safe_val("reversal_analysis", "absorption_or_exhaustion").lower()
        
        if "no absorption" in rev_text or "not detected" in rev_text or "none" in rev_text:
            absorption_state = "ABSENT"
        elif "absorbed" in rev_text or "absorption" in rev_text:
            absorption_state = "PRESENT"
        else:
            absorption_state = "UNRESOLVED"

        is_rev = rev_obj.get("is_reversal_forming") or rev_obj.get("reversal_developing")
        if is_rev is True:
            reversal_state = "DEVELOPING"
        elif is_rev is False:
            reversal_state = "NOT_DETECTED"
        else:
            reversal_state = "UNRESOLVED"

        setup_family = syn_obj.get("setup_family", "UNRESOLVED") if isinstance(syn_obj, dict) else "UNRESOLVED"
        if not setup_family or setup_family not in {"CONTINUATION", "PULLBACK", "BREAKOUT", "REVERSAL", "FAILED_AGGRESSION", "UNRESOLVED", "NO_TRADE"}:
            if reversal_state == "DEVELOPING":
                setup_family = "REVERSAL"
            elif state_str == "NO_TRADE":
                setup_family = "NO_TRADE"
            elif absorption_state == "PRESENT":
                setup_family = "FAILED_AGGRESSION"
            else:
                setup_family = "CONTINUATION"

        # Mandatory Reversal Watch (Section 7)
        reversal_watch_dir = rev_watch_obj.get("direction", "NONE") if isinstance(rev_watch_obj, dict) else "NONE"
        if reversal_watch_dir in ("CALL_TO_PUT", "PUT_TO_CALL"):
            reversal_watch = reversal_watch_dir
        elif reversal_state == "DEVELOPING":
            reversal_watch = "PUT_REVERSAL" if state_str in ("CALL", "CALL_DEVELOPING") else "CALL_REVERSAL"
        else:
            reversal_watch = "NONE"

        earliest_contra_id = rev_watch_obj.get("earliest_contradiction_event_id") if isinstance(rev_watch_obj, dict) else None
        premium_conf = rev_watch_obj.get("premium_confirmation", "UNRESOLVED") if isinstance(rev_watch_obj, dict) else "UNRESOLVED"
        reason_not_conf = rev_watch_obj.get("reason_not_confirmed", "") if isinstance(rev_watch_obj, dict) else ""
        failed_move_state = rev_watch_obj.get("failed_move", "UNRESOLVED") if isinstance(rev_watch_obj, dict) else "UNRESOLVED"

        option_buyer_side = ob_obj.get("option_buyer_side", "UNRESOLVED") if isinstance(ob_obj, dict) else "UNRESOLVED"
        no_trade_reason = syn_obj.get("no_trade_reason", "DIRECTION_UNCLEAR" if state_str == "NO_TRADE" else "NOT_APPLICABLE") if isinstance(syn_obj, dict) else "NOT_APPLICABLE"

        node = ThesisNode(
            thesis_id=thesis_id,
            session_id=packet.session_id,
            created_at=now_utc,
            input_revision=packet.revision,
            event_cursor_before=self.thesis_graph.get_cursor(),
            event_cursor_after=cursor_after,
            state=state_str,
            underlying_view=safe_val("option_buyer_analysis", "underlying_view") or safe_val("option_buyer_analysis", "underlying_direction"),
            option_buyer_view=safe_val("option_buyer_analysis", "option_buying_suitability") or option_buyer_side,
            what_changed=safe_val("observer", "what_changed"),
            call_case=safe_val("call_case", "argument"),
            put_case=safe_val("put_case", "argument"),
            no_trade_case=safe_val("no_trade_case", "argument"),
            supporting_evidence_ids=synth.get("supporting_evidence_ids", []) if isinstance(synth, dict) else [],
            contradicting_evidence_ids=synth.get("contradicting_evidence_ids", []) if isinstance(synth, dict) else [],
            unresolved_evidence_ids=synth.get("unresolved_evidence_ids", []) if isinstance(synth, dict) else [],
            watch_next=synth.get("watch_next", []) if isinstance(synth, dict) else [],
            invalidation_conditions=synth.get("invalidation_conditions", []) if isinstance(synth, dict) else [],
            supersedes_thesis_id=active_thesis.thesis_id if active_thesis else None,
            status=ThesisStatus.ACTIVE.value,
            model=model_name,
            prompt_hash=prompt_hash,
            input_hash=input_hash,
            market_story=safe_val("market_story", "narrative"),
            reversal_analysis=safe_val("reversal_analysis", "absorption_or_exhaustion"),
            contradictions=safe_val("contradictions", "strongest_contradiction"),
            temporal_analysis=safe_val("temporal_analysis", "evolution_from_previous"),
            external_context=safe_val("external_context", "interpretation"),
            counterfactual=safe_val("counterfactual", "opposite_thesis_conditions"),
            human_miss_candidate=safe_val("human_miss_candidate", "subtle_relationship"),
            historical_analogs="NOT_IMPLEMENTED",
            setup_family=setup_family,
            thesis_condition="STABLE",
            reversal_watch=reversal_watch,
            absorption_state=absorption_state,
            failed_move_state=failed_move_state,
            follow_through_state="UNRESOLVED",
            reversal_state=reversal_state,
            reversal_watch_data=rev_watch_obj if isinstance(rev_watch_obj, dict) else {},
            no_trade_reason=no_trade_reason,
            option_buyer_side=option_buyer_side,
            premium_confirmation=premium_conf,
            earliest_contradiction_event_id=earliest_contra_id,
            reason_not_confirmed=reason_not_conf,
            entry_window=raw_response.get("entry_window", "WAIT"),
            why_now=raw_response.get("why_now", []) if isinstance(raw_response.get("why_now"), list) else [],
            what_would_change_my_mind=raw_response.get("what_would_change_my_mind", []) if isinstance(raw_response.get("what_would_change_my_mind"), list) else [],
            five_hypotheses=raw_response.get("five_hypotheses", {}) if isinstance(raw_response.get("five_hypotheses"), dict) else {},
            qwen_observation=raw_response.get("qwen_observation", {}) if isinstance(raw_response.get("qwen_observation"), dict) else {},
            gemini_review=raw_response.get("gemini_review", {}) if isinstance(raw_response.get("gemini_review"), dict) else {},
            semantic_validation={
                "input_hash": packet.packet_hash, "revision": packet.revision,
                "response": deepcopy(raw_response),
                "context": {"canonical_state": deepcopy(packet.canonical_state),
                            "canonical_levels": list(getattr(packet, "canonical_levels", [])),
                            "cited_ids": sorted(all_cited_ids)},
            },
        )

        # Re-check session/evidence ownership immediately before the only
        # state-changing operation. A valid slow response remains historical
        # evidence but cannot advance the current cursor after newer evidence.
        if commit_guard is not None and not commit_guard(packet):
            return GateValidationResult(
                is_valid=False,
                status="STALE_RESULT_NOT_PROMOTED",
                error_details="Session or evidence frontier changed before durable commit.",
            )

        # Durable commit advances cursor
        if not self.thesis_graph.commit_thesis(node):
            return GateValidationResult(
                is_valid=False,
                status="STALE_RESULT_NOT_PROMOTED",
                error_details="Session or evidence frontier changed at durable commit.",
            )

        return GateValidationResult(
            is_valid=True,
            status="COMMITTED",
            committed_thesis=node,
        )

    def _validate_and_commit_competing_hypotheses(
        self,
        raw_response: Dict[str, Any],
        packet: BrainPacket,
        model_name: str,
        system_prompt: str,
        commit_guard: Optional[Callable[[BrainPacket], bool]] = None,
        input_receipt: Optional[Dict[str, Any]] = None,
    ) -> GateValidationResult:
        from src.oracle_sol.competing_hypotheses_contract import validate_structure

        # 1. Structure validation
        struct_err = validate_structure(raw_response, packet)
        if struct_err:
            logger.warning("EvidenceGate: Competing hypotheses structure invalid: %s", struct_err)
            return GateValidationResult(
                is_valid=False,
                status="SCHEMA_INVALID",
                error_details=struct_err,
            )

        # 2. Prohibited instruction check
        raw_text_repr = json.dumps(raw_response).lower()
        for forbidden in PROHIBITED_BROKER_INSTRUCTIONS:
            if forbidden in raw_text_repr:
                logger.error("EvidenceGate: Prohibited instruction detected: %s", forbidden)
                return GateValidationResult(
                    is_valid=False,
                    status="PROHIBITED_INSTRUCTION_DETECTED",
                    error_details=f"Model attempted to reference forbidden instruction '{forbidden}'",
                )

        # 3. Evidence-reference verification
        valid_ids: Set[str] = set(packet.valid_evidence_ids)
        all_cited_ids: Set[str] = set()

        for c in raw_response.get("conclusions", []):
            if isinstance(c, dict):
                for eid in c.get("evidence_ids", []):
                    if isinstance(eid, str):
                        all_cited_ids.add(eid.strip())
        for h in raw_response.get("hypotheses", {}).values():
            if isinstance(h, dict):
                for eid in h.get("evidence_ids", []):
                    if isinstance(eid, str):
                        all_cited_ids.add(eid.strip())

        # Check peer model citations
        peer_model_eids = [eid for eid in all_cited_ids if eid.startswith(("qwen:", "gemini:", "model:", "peer:"))]
        if peer_model_eids:
            return GateValidationResult(
                is_valid=False,
                status="MODEL_HYPOTHESIS_AS_EVIDENCE_REJECTED",
                error_details=f"Cannot cite peer model hypotheses as canonical evidence: {peer_model_eids}",
                unsupported_evidence_ids=peer_model_eids,
            )

        # Check ungrounded / unresolvable IDs
        unsupported = [
            eid for eid in all_cited_ids
            if eid not in valid_ids or (hasattr(packet, "resolve_evidence") and packet.resolve_evidence(eid) is None)
        ]
        if unsupported:
            return GateValidationResult(
                is_valid=False,
                status="MODEL_CLAIM_UNSUPPORTED",
                error_details=f"Model cited ungrounded or orphan evidence IDs: {unsupported}",
                unsupported_evidence_ids=unsupported,
            )

        # 4. Session & revision monotonicity check
        active_thesis = self.thesis_graph.get_active_thesis() if self.thesis_graph else None
        if active_thesis and packet.revision < active_thesis.input_revision:
            return GateValidationResult(
                is_valid=False,
                status="PROVENANCE_MISMATCH",
                error_details=f"Packet revision {packet.revision} is older than active thesis {active_thesis.input_revision}",
            )

        # 5. Construct ThesisNode
        now_utc = datetime.now(timezone.utc).isoformat()
        prompt_hash = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
        input_hash = packet.packet_hash
        thesis_id = f"thesis_{packet.session_id}_{packet.revision}_{hashlib.sha256(now_utc.encode()).hexdigest()[:8]}"
        cursor_after = packet.unseen_event_ids[-1] if packet.unseen_event_ids else (self.thesis_graph.get_cursor() if self.thesis_graph else None)

        state_str = raw_response.get("state", "WAIT").upper()
        evolution_str = raw_response.get("thesis_evolution", "UNRESOLVED").upper()
        maturity_str = raw_response.get("opportunity_maturity", "UNKNOWN").upper()

        if evolution_str == "REVERSAL_WATCH":
            setup_family = "REVERSAL"
        elif state_str in ("NO_TRADE", "WAIT"):
            setup_family = "NO_TRADE"
        elif evolution_str in ("DEVELOPING", "EARLY_POSSIBILITY"):
            setup_family = "PULLBACK" if "DEVELOPING" in state_str else "CONTINUATION"
        else:
            setup_family = "CONTINUATION"

        reversal_watch = "PUT_REVERSAL" if state_str in ("CALL", "CALL_DEVELOPING") and evolution_str == "REVERSAL_WATCH" else ("CALL_REVERSAL" if state_str in ("PUT", "PUT_DEVELOPING") and evolution_str == "REVERSAL_WATCH" else ("REVERSAL_WATCH" if evolution_str == "REVERSAL_WATCH" else "NONE"))
        reversal_state = "DEVELOPING" if evolution_str == "REVERSAL_WATCH" or "REVERSAL" in state_str else "NOT_DETECTED"

        conclusions = raw_response.get("conclusions", [])
        hypotheses = raw_response.get("hypotheses", {})

        why_now_claims = []
        for c in conclusions:
            if c.get("purpose") == "why_now":
                claim = c.get("claim", "")
                eids = c.get("evidence_ids", [])
                if eids and not (any(eid in claim for eid in eids) or any(k in claim for k in (":", "metric", "rel:", "evt_"))):
                    claim = f"{claim} [{' '.join(eids)}]"
                why_now_claims.append(claim)
        if not why_now_claims and raw_response.get("promotion_reason"):
            why_now_claims = [f"{raw_response.get('promotion_reason')} [{' '.join(sorted(all_cited_ids))}]"]

        what_changed_claims = [c["claim"] for c in conclusions if c.get("purpose") == "what_changed"]
        contra_claims = [c["claim"] for c in conclusions if c.get("purpose") == "contradiction"]
        watch_next_claims = [c["claim"] for c in conclusions if c.get("purpose") == "watch_next"]
        opt_claims = [c["claim"] for c in conclusions if c.get("purpose") == "option_response"]

        supporting_ids = sorted(list(all_cited_ids))
        contradicting_ids = [eid for c in conclusions if c.get("purpose") == "contradiction" for eid in c.get("evidence_ids", [])]
        unresolved_ids = [eid for h in hypotheses.values() if h.get("plausibility") == "UNRESOLVED" for eid in h.get("evidence_ids", [])]

        entry_win = "WAIT" if state_str in ("WAIT", "NO_TRADE") else "UNAVAILABLE"
        if "DEVELOPING" in state_str:
            entry_win = "DEVELOPING"

        node = ThesisNode(
            thesis_id=thesis_id,
            session_id=packet.session_id,
            created_at=now_utc,
            input_revision=packet.revision,
            event_cursor_before=self.thesis_graph.get_cursor() if self.thesis_graph else None,
            event_cursor_after=cursor_after,
            state=state_str,
            underlying_view=hypotheses.get("CALL", {}).get("discrimination", "") if state_str == "CALL" else (hypotheses.get("PUT", {}).get("discrimination", "") if state_str == "PUT" else "NEUTRAL"),
            option_buyer_view="; ".join(opt_claims) or "UNRESOLVED",
            what_changed="; ".join(what_changed_claims),
            call_case=hypotheses.get("CALL", {}).get("discrimination", ""),
            put_case=hypotheses.get("PUT", {}).get("discrimination", ""),
            no_trade_case=hypotheses.get("NOISE", {}).get("discrimination", ""),
            supporting_evidence_ids=supporting_ids,
            contradicting_evidence_ids=contradicting_ids,
            unresolved_evidence_ids=unresolved_ids,
            watch_next=watch_next_claims,
            invalidation_conditions=contra_claims,
            supersedes_thesis_id=active_thesis.thesis_id if active_thesis else None,
            status=ThesisStatus.ACTIVE.value,
            model=model_name,
            prompt_hash=prompt_hash,
            input_hash=input_hash,
            market_story=raw_response.get("promotion_reason", ""),
            reversal_analysis=hypotheses.get("REVERSAL", {}).get("discrimination", ""),
            contradictions="; ".join(contra_claims) or "NONE",
            temporal_analysis=evolution_str,
            thesis_evolution=evolution_str,
            opportunity_maturity=maturity_str,
            setup_family=setup_family,
            thesis_condition="STABLE",
            reversal_watch=reversal_watch,
            reversal_state=reversal_state,
            entry_window=entry_win,
            why_now=why_now_claims or [raw_response.get("promotion_reason", "")],
            what_would_change_my_mind=watch_next_claims or contra_claims,
            five_hypotheses=hypotheses,
            semantic_validation={
                "input_receipt": deepcopy(input_receipt),
                "input_hash": packet.packet_hash,
                "revision": packet.revision,
                "response": deepcopy(raw_response),
                "context": {
                    "canonical_state": deepcopy(packet.canonical_state),
                    "canonical_levels": list(getattr(packet, "canonical_levels", [])),
                    "cited_ids": sorted(all_cited_ids),
                },
            },
        )

        # 6. Commit guard check
        if commit_guard is not None and not commit_guard(packet):
            return GateValidationResult(
                is_valid=False,
                status="STALE_RESULT_NOT_PROMOTED",
                error_details="Session or evidence frontier changed before durable commit.",
            )

        # 7. Durable commit
        if self.thesis_graph is not None:
            if not self.thesis_graph.commit_thesis(node):
                return GateValidationResult(
                    is_valid=False,
                    status="STALE_RESULT_NOT_PROMOTED",
                    error_details="Session or evidence frontier changed at durable commit.",
                )

        return GateValidationResult(
            is_valid=True,
            status="COMMITTED",
            committed_thesis=node,
        )

    @staticmethod
    def validate_factual_claim(text, refs, packet):
        """Read-only candidate handoff check. No market-state choice or commit.

        Scoped to observed calibration failures; not a general natural-language
        proof system. Used by the offline decision brief, not runtime activation.
        """
        import re
        plain = re.sub(r"\[[^\]]+\]", "", text).lower()
        records = [packet.resolve_evidence(ref) for ref in refs]
        if any(row is None for row in records):
            return "UNRESOLVED_FACT"
        values = [row.get("value") for row in records]
        observed_keys = set()
        for value in values:
            if isinstance(value, dict):
                observed_keys.update(value.get("supporting_values", {}))
        # Source-defined volatility slices are delta coordinates, not duration.
        # Reject only explicit misnaming of a cited slice, never select a thesis.
        for delta in (10, 25):
            if f"skew_{delta}d" in observed_keys and re.search(
                rf"\b{delta}[\s\-\u2011]*day(?:s)?\s+skew\b", plain
            ):
                return "DELTA_SLICE_IS_NOT_DAYS_TO_EXPIRY"
        # Neutral statements about limitations are not affirmative attribution.
        disclaims = any(term in plain for term in ("does not prove", "does not establish", "cannot infer", "cannot identify", "not evidence of"))
        if not disclaims and any(term in plain for term in ("demand", "buying pressure", "selling pressure")):
            # The supplied price/IV/book sequence cannot identify trade-side intent.
            if observed_keys and observed_keys <= {
                "diffs", "canonical_snapshot_id", "chronology_mode", "before_spot", "after_spot", "spot_delta", "session_vwap", "spot_to_vwap_pts",
                "before_futures", "after_futures", "futures_delta", "basis", "before_basis", "after_basis", "basis_delta",
                "before_iv", "after_iv", "iv_delta", "skew_10d", "skew_25d", "expected_move_pts", "before_straddle", "after_straddle", "straddle_delta"}:
                return "PRICE_RESPONSE_IS_NOT_DEMAND_ATTRIBUTION"
        if not disclaims and "basis" in plain and any(term in plain for term in ("bullish pressure", "bearish pressure", "carry advantage for call")):
            return "BASIS_IS_NOT_DIRECTIONAL_PRESSURE"
        if (any(term in plain for term in ("missing", "unavailable")) and any(term in plain for term in ("oi", "pcr", "gex"))
                and any(term in plain for term in ("case is weakened by missing", "directional confirmation", "confirms direction"))):
            return "MISSING_POSITIONING_IS_NOT_DIRECTIONAL_CONFIRMATION"
        for side, key in (("call", "ce_pricing"), ("put", "pe_pricing")):
            iv_move = re.search(rf"(?:{side}(?: option)? iv|both call and put ivs) (fell|decreased|rose|increased)", plain)
            if iv_move:
                iv_pairs = [v.get("supporting_values", {}).get("diffs", {}).get(key, {}) for v in values if isinstance(v, dict)]
                iv_pairs = [p for p in iv_pairs if isinstance(p.get("before"), dict) and isinstance(p.get("after"), dict)]
                if not iv_pairs:
                    return "CONTRACT_IV_WITHOUT_TEMPORAL_EVIDENCE"
                for pair in iv_pairs:
                    before,after=pair["before"],pair["after"]
                    if before.get("security_id") is None or before.get("security_id") != after.get("security_id"):
                        return "PREMIUM_CONTINUITY_ERROR"
                    a,b=before.get("iv"),after.get("iv")
                    if not isinstance(a,(int,float)) or not isinstance(b,(int,float)):
                        return "MISSING_CONTRACT_IV"
                    if ((iv_move[1] in {"fell","decreased"} and b >= a) or
                            (iv_move[1] in {"rose","increased"} and b <= a)):
                        return "CLAIM_CONTRADICTS_CONTRACT_IV"
            match = re.search(rf"\b{side}(?:\s+atm)?\s+(?:premium|ltp)\s+(rose|increased|fell|decreased)(?:\s+from\s+([0-9.,]+)\s*(?:to|→)\s*([0-9.,]+))?", plain)
            negated = re.search(rf"no\s+increase\s+in\s+{side}\s+premium", plain)
            if not match and not negated:
                continue
            pairs = [v.get("supporting_values", {}).get("diffs", {}).get(key, {}) for v in values if isinstance(v, dict)]
            pairs = [p for p in pairs if isinstance(p.get("before"), dict) and isinstance(p.get("after"), dict)]
            if not pairs:
                return "PREMIUM_CHANGE_WITHOUT_TEMPORAL_EVIDENCE"
            for pair in pairs:
                before, after = pair["before"], pair["after"]
                if before.get("security_id") is None or before.get("security_id") != after.get("security_id"):
                    return "PREMIUM_CONTINUITY_ERROR"
                a,b = before.get("ltp"), after.get("ltp")
                if not isinstance(a, (int,float)) or not isinstance(b, (int,float)):
                    return "MISSING_PREMIUM_OBSERVATION"
                if ((negated and b > a) or (match and match[1] in {"rose","increased"} and b <= a)
                        or (match and match[1] in {"fell","decreased"} and b >= a)):
                    return "CLAIM_CONTRADICTS_RECORDED_PREMIUM_CHANGE"
                if match and match[2] and (float(match[2].replace(',','')) != a or float(match[3].rstrip('.').replace(',','')) != b):
                    return "CLAIM_NUMERIC_MISMATCH"
        return None

    def _validate_semantic_claims(
        self,
        raw_response: Dict[str, Any],
        packet: BrainPacket,
        all_cited_ids: Set[str],
    ) -> Optional[str]:
        """Strict semantic claim contract and consistency verification (Sections 5, 6, 7)."""
        import re

        def safe_text(parent_key: str, sub_key: str = "") -> str:
            parent = raw_response.get(parent_key, {})
            if isinstance(parent, str):
                return parent
            elif isinstance(parent, dict):
                return str(parent.get(sub_key, "") or parent.get("argument", "") or parent.get("narrative", "") or parent.get("critique", "") or parent.get("absorption_or_exhaustion", "") or "")
            return ""

        # 1. Numeric Claim Firewall (Section 8)
        canonical_levels = getattr(packet, "canonical_levels", [])
        spot_val = packet.canonical_state.get("spot_price")
        vwap_val = packet.canonical_state.get("session_vwap")
        if canonical_levels:
            allowed_ints = {int(round(lvl)) for lvl in canonical_levels}
            def is_allowed_level(num: int) -> bool:
                return num in allowed_ints

            # Inspect watch_next, counterfactual, invalidation specifically
            synth = raw_response.get("synthesis", {})
            watch_items = synth.get("watch_next", []) if isinstance(synth, dict) else []
            inval_items = synth.get("invalidation_conditions", []) if isinstance(synth, dict) else []
            cf_text = safe_text("counterfactual")
            firewall_text = " ".join(watch_items + inval_items + [cf_text])

            for m in re.finditer(r"\b(2[0-9]{4})\b", firewall_text):
                num = int(m.group(1))
                if not is_allowed_level(num):
                    return f"UNSUPPORTED_NUMERIC_LEVEL: Level {num} cited in watch_next/counterfactual/invalidation does not exist in canonical evidence/ladder: {sorted(list(allowed_ints))}"

        # 2. Strict Open Interest (OI) Semantics Verification (Section 6)
        put_case = safe_text("put_case").lower()
        call_case = safe_text("call_case").lower()
        market_story = safe_text("market_story").lower()
        synth = raw_response.get("synthesis", {})

        # OI and futures flow cannot reveal hidden option-side buyer intent.
        for text in (market_story, call_case, put_case, " ".join(raw_response.get("why_now", []))):
            if ("call oi" in text or "put oi" in text) and any(
                phrase in text for phrase in ("hidden bullish pressure", "hidden bearish pressure", "concealed bullish pressure", "concealed bearish pressure")
            ):
                return "OI_DIRECTIONAL_INFERENCE_UNSUPPORTED: OI activity cannot reveal hidden directional buyer/writer intent."

        directional_terms = ["buying", "writing", "bullish positioning", "bearish positioning", "bullish conviction", "bearish conviction", "bullish intent", "bearish intent"]
        
        has_put_dir = any(t in put_case for t in ["put buying", "put writing", "bearish put", "bearish positioning"])
        if has_put_dir and "unresolved" not in put_case:
            put_eids = raw_response.get("put_case", {}).get("evidence_ids", []) if isinstance(raw_response.get("put_case"), dict) else []
            corroborating = [eid for eid in put_eids if eid in {
                "metric:spot_price", "metric:futures_price", "metric:basis", 
                "metric:flow_net_delta", "metric:flow_aggression", "metric:pe_atm_premium", "metric:atm_iv"
            } or eid.startswith("evt_") or eid.startswith("rel:")]
            if not corroborating and "metric:put_oi_build" in put_eids:
                return "OI_DIRECTIONAL_INFERENCE_UNSUPPORTED: Directional put positioning claimed from OI build alone without price, flow, premium, or basis corroboration. Symmetrical OI cannot distinguish buyer vs writer."

        has_call_dir = any(t in call_case for t in ["call buying", "call writing", "bullish call", "bullish positioning"])
        if has_call_dir and "unresolved" not in call_case:
            call_eids = raw_response.get("call_case", {}).get("evidence_ids", []) if isinstance(raw_response.get("call_case"), dict) else []
            corroborating = [eid for eid in call_eids if eid in {
                "metric:spot_price", "metric:futures_price", "metric:basis", 
                "metric:flow_net_delta", "metric:flow_aggression", "metric:ce_atm_premium", "metric:atm_iv"
            } or eid.startswith("evt_") or eid.startswith("rel:")]
            if not corroborating and "metric:call_oi_build" in call_eids:
                return "OI_DIRECTIONAL_INFERENCE_UNSUPPORTED: Directional call positioning claimed from OI build alone without price, flow, premium, or basis corroboration. Symmetrical OI cannot distinguish buyer vs writer."

        # Check market story asserting directional OI without corroboration
        if ("call oi" in market_story or "put oi" in market_story) and any(t in market_story for t in ["bullish positioning", "bearish positioning", "bullish intent"]):
            if "unresolved" not in market_story:
                has_corrob = any(eid in all_cited_ids for eid in {"metric:spot_price", "metric:futures_price", "metric:basis", "metric:flow_net_delta", "metric:ce_atm_premium", "metric:pe_atm_premium"})
                if not has_corrob:
                    return "OI_DIRECTIONAL_INFERENCE_UNSUPPORTED: Market story asserted directional intent from OI build without citing corroborating price, flow, or premium evidence."

        # 3. Cross-Section Consistency Check (Section 10)
        reversal_text = safe_text("reversal_analysis").lower()
        rev_watch_obj = raw_response.get("reversal_watch", {})
        failed_move = rev_watch_obj.get("failed_move", "UNRESOLVED") if isinstance(rev_watch_obj, dict) else "UNRESOLVED"
        
        if ("absorbed" in market_story or "absorption" in market_story):
            if ("no absorption" in reversal_text or "not detected" in reversal_text or "none" in reversal_text) or failed_move == "NOT_SUPPORTED":
                return "SEMANTIC_INTERNAL_CONTRADICTION: Market story claims absorption occurred, but reversal analysis / reversal_watch states absorption was not detected / NOT_SUPPORTED."

        ob_obj = raw_response.get("option_buyer_analysis", {})
        ob_side = ob_obj.get("option_buyer_side", "") if isinstance(ob_obj, dict) else ""
        no_trade_text = safe_text("no_trade_case").lower()

        if ob_side == "PUT_FAVOURABLE" and ("puts are unbuyable" in no_trade_text or "unfavourable for puts" in no_trade_text):
            return "SEMANTIC_INTERNAL_CONTRADICTION: Option buyer analysis indicates PUT_FAVOURABLE but no_trade_case asserts puts are unbuyable."
        if ob_side == "CALL_FAVOURABLE" and ("calls are unbuyable" in no_trade_text or "unfavourable for calls" in no_trade_text):
            return "SEMANTIC_INTERNAL_CONTRADICTION: Option buyer analysis indicates CALL_FAVOURABLE but no_trade_case asserts calls are unbuyable."

        state_str = synth.get("state", "").upper() if isinstance(synth, dict) else str(synth).upper()
        if state_str in ("CALL", "CALL_DEVELOPING") and ("lacks support" in call_case or "unsupported" in call_case):
            return f"SEMANTIC_INTERNAL_CONTRADICTION: State is {state_str} but call_case states call buying lacks support or is unsupported."
        if state_str in ("PUT", "PUT_DEVELOPING") and ("lacks support" in put_case or "unsupported" in put_case):
            return f"SEMANTIC_INTERNAL_CONTRADICTION: State is {state_str} but put_case states put buying lacks support or is unsupported."

        # 4. Absorption Claim Verification
        claims_absorption_story = ("absorbed" in market_story or "absorption" in market_story) and not ("no absorption" in market_story or "none detected" in market_story or "without absorption" in market_story)
        claims_absorption_reversal = ("absorbed" in reversal_text or "absorption" in reversal_text) and not ("no absorption" in reversal_text or "not detected" in reversal_text or "none" in reversal_text)
        if claims_absorption_story or claims_absorption_reversal:
            has_aggression = any(eid in all_cited_ids for eid in {"metric:flow_net_delta", "metric:flow_aggression"}) or any("DELTA" in eid or "FLOW" in eid for eid in all_cited_ids)
            has_price_response = any(eid in all_cited_ids for eid in {"metric:spot_price", "metric:futures_price", "metric:basis"})
            if not (has_aggression and has_price_response):
                return "ABSORPTION_CLAIM_UNSUPPORTED: Absorption claim requires citing both aggression evidence (flow/delta) and price response evidence (spot/basis)."

        # 5. Institutional Claim Firewall (Section E)
        banned_institutional = [
            "institutional absorption",
            "institutions are buying",
            "institutions are selling",
            "smart money buying",
            "smart money selling",
            "smart money accumulating",
            "large traders accumulating",
            "institutional accumulation",
            "institutional distribution",
        ]
        combined_text = f"{market_story} {call_case} {put_case} {reversal_text} {' '.join(raw_response.get('why_now', []))}".lower()
        for phrase in banned_institutional:
            if phrase in combined_text:
                return f"INSTITUTIONAL_CLAIM_UNSUPPORTED: Unsupported attribution '{phrase}'. Claims must be grounded in factual market dynamics (e.g. aggressive buying absorbed)."

        # 6. Failed Aggression Direction Check (Section E)
        rev_dir = rev_watch_obj.get("direction", "NONE") if isinstance(rev_watch_obj, dict) else "NONE"
        if rev_dir in ("PUT_TO_CALL", "CALL_TO_PUT"):
            has_directional_flow = any(
                eid in all_cited_ids
                for eid in {"metric:flow_net_delta", "metric:flow_aggression"}
            ) or any("DELTA" in eid or "FLOW" in eid for eid in all_cited_ids)
            if not has_directional_flow:
                return f"FAILED_AGGRESSION_DIRECTION_UNSUPPORTED: Reversal direction '{rev_dir}' claimed without citing directional aggression or order flow evidence sequence."

        # ── Phase 1.3 Semantic Truth Firewalls ──
        all_narrative_text = f"{market_story} {call_case} {put_case} {reversal_text} {' '.join(raw_response.get('why_now', []))}".lower()

        # 7. Underlying Order Flow Misattribution to Option Side Firewall
        banned_flow_misattributions = [
            "absorption on the call side",
            "absorption on the put side",
            "call absorption",
            "put absorption",
            "call-side absorption",
            "put-side absorption",
            "sellers taking aggression on the call side",
            "buyers taking aggression on the put side",
            "call side aggression",
            "put side aggression",
        ]
        for phrase in banned_flow_misattributions:
            if phrase in all_narrative_text:
                return f"UNDERLYING_FLOW_MISATTRIBUTED_TO_OPTION_SIDE: Order flow metrics (absorption, delta, aggression) derive from NIFTY futures and must not be misattributed as option-side flow or absorption: '{phrase}'."

        # 8. GEX Net Call Gamma Mislabel & Directional Inference Firewall
        banned_gex_mislabels = [
            "net call gamma",
            "call gamma dominates",
            "bullish gamma",
            "bearish gamma",
            "put gamma dominates",
        ]
        for phrase in banned_gex_mislabels:
            if phrase in all_narrative_text:
                return f"GEX_CALL_GAMMA_MISLABEL: Total net GEX provides aggregate dealer gamma exposure and pinning context. It must NOT be translated into '{phrase}' without canonical strike decomposition."

        if state_str in ("CALL", "CALL_DEVELOPING"):
            call_eids = raw_response.get("call_case", {}).get("evidence_ids", []) if isinstance(raw_response.get("call_case"), dict) else []
            if "metric:total_net_gex_inr_cr" in call_eids or "metric:dealer_regime" in call_eids:
                has_dir_evidence = any(eid in call_eids for eid in {
                    "metric:spot_price", "metric:futures_price", "metric:flow_net_delta", 
                    "metric:ce_atm_premium", "metric:price_response_efficiency", "rel:ce_contract_premium"
                })
                if not has_dir_evidence:
                    return "GEX_DIRECTIONAL_INFERENCE_UNSUPPORTED: Positive GEX supplies volatility pinning context and cannot serve as standalone directional evidence for CALL without independent price/flow/premium support."

        if state_str in ("PUT", "PUT_DEVELOPING"):
            put_eids = raw_response.get("put_case", {}).get("evidence_ids", []) if isinstance(raw_response.get("put_case"), dict) else []
            if "metric:total_net_gex_inr_cr" in put_eids or "metric:dealer_regime" in put_eids:
                has_dir_evidence = any(eid in put_eids for eid in {
                    "metric:spot_price", "metric:futures_price", "metric:flow_net_delta", 
                    "metric:pe_atm_premium", "metric:price_response_efficiency", "rel:pe_contract_premium"
                })
                if not has_dir_evidence:
                    return "GEX_DIRECTIONAL_INFERENCE_UNSUPPORTED: Negative GEX supplies volatility acceleration context and cannot serve as standalone directional evidence for PUT without independent price/flow/premium support."

        # 9. Absorption Qualitative Adjective Invention Firewall
        # Numeric values like 0.3028 cannot be labeled HIGH/LOW/STRONG unless producer emits that state (e.g. SELLERS_ABSORBED requires >= 0.45)
        canonical_of_state = packet.canonical_state.get("order_flow_response_state", "MIXED")
        if canonical_of_state not in ("SELLERS_ABSORBED", "BUYERS_ABSORBED"):
            banned_qualitative_absorption = [
                "seller absorption is high",
                "seller absorption is strong",
                "buyer absorption is high",
                "buyer absorption is strong",
                "high seller absorption",
                "strong seller absorption",
                "high buyer absorption",
                "strong buyer absorption",
            ]
            for phrase in banned_qualitative_absorption:
                if phrase in all_narrative_text:
                    return f"ABSORPTION_QUALITATIVE_INVENTION: Numeric absorption value cannot be qualitatively labeled HIGH/STRONG unless canonical producer outputs SELLERS_ABSORBED or BUYERS_ABSORBED (current canonical state is '{canonical_of_state}'): '{phrase}'."

        # 10. WHY_NOW Multi-Factor Relationship & Evidence Grounding Check
        why_now_list = raw_response.get("why_now", [])
        if isinstance(why_now_list, list) and why_now_list:
            for idx, bullet in enumerate(why_now_list):
                bullet_lower = bullet.lower()
                # Must cite at least one evidence ID
                has_cited_id = any(eid in bullet for eid in all_cited_ids) or ":" in bullet or "metric" in bullet or "rel:" in bullet or "evt_" in bullet
                if not has_cited_id:
                    return f"WHY_NOW_EVIDENCE_UNRESOLVED: WHY_NOW bullet {idx+1} does not cite any valid evidence ID: '{bullet}'"

                # Reject isolated indicator readings claiming standalone direction
                if "call oi" in bullet_lower and ("supports call" in bullet_lower or "is bullish" in bullet_lower or "confirms call" in bullet_lower):
                    return f"OI_DIRECTIONAL_INFERENCE_UNSUPPORTED: WHY_NOW bullet {idx+1} asserts directional CALL confirmation from Call OI build alone: '{bullet}'"
                if "put oi" in bullet_lower and ("supports put" in bullet_lower or "is bearish" in bullet_lower or "confirms put" in bullet_lower):
                    return f"OI_DIRECTIONAL_INFERENCE_UNSUPPORTED: WHY_NOW bullet {idx+1} asserts directional PUT confirmation from Put OI build alone: '{bullet}'"

        # 11. ENTRY_WINDOW=READY Grounding Check
        entry_window = raw_response.get("entry_window", "")
        if entry_window == "READY":
            inval = raw_response.get("what_would_change_my_mind", []) or raw_response.get("synthesis", {}).get("invalidation_conditions", [])
            if not inval or len(inval) == 0:
                return "ENTRY_WINDOW_UNGROUNDED: ENTRY_WINDOW=READY requires explicit invalidation conditions defining what would change the thesis."
            if not why_now_list or len(why_now_list) == 0:
                return "ENTRY_WINDOW_UNGROUNDED: ENTRY_WINDOW=READY requires actionable WHY_NOW relationship evidence."

        return None
