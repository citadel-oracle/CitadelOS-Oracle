"""The 9-Pass Sol Market Brain Reasoning Protocol & Orchestrator (P0.2 Hardened).

Enforces structured causal reasoning with neutral framing, canonical cycle identity,
fail-closed evidence citation validation, and honest separation of model failure from NO_TRADE.
"""

from __future__ import annotations

import json
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Callable, ContextManager, Dict, List, Optional, Set, Tuple

from src.oracle_sol.contracts import (
    ActiveMarketStory,
    DevelopingState,
    ExpectationEvaluationRecord,
    ExpectationRecord,
    ExpectationResult,
    MarketEvent,
    MarketThesisVerdict,
    ReasoningStatus,
    SolBeaconOutput,
    SolEvidenceSnapshot,
    SolModelRequestEnvelope,
    SystemStatus,
    ThesisState,
    resolve_canonical_market_state,
)
from src.oracle_sol.event_sourced_memory import EventSourcedMarketMemory
from src.oracle_sol.model_adapter import SolModelAdapter
from src.oracle_sol.provenance_guard import (
    EvidenceReferenceValidator,
    ProvenanceGuard,
)
from src.oracle_sol.thesis_memory import ThesisMemory


SYSTEM_PROMPT = """You are CITADEL ORACLE SOL — a derivatives quantitative reasoning module.
You do NOT calculate math or invent numbers. CITADEL calculates all mathematical metrics; you interpret them.

ABSOLUTE OPERATIONAL MANDATES:
1. Ground every claim strictly in the provided canonical evidence snapshot and factual event timeline.
2. If a metric is null/missing (UNAVAILABLE), never guess or assume 0.0. Acknowledge missing metrics in data_gaps.
3. VOB is strictly quarantined and has zero influence. Never mention or search for VOB.
4. Separate underlying NIFTY direction from option expression viability.
5. Do NOT invent arbitrary confidence percentages or arbitrary linear score sums.
6. If the evidence shows clean structural alignment without contradiction, output strongest_contradiction as "NONE_OBSERVED". Never invent artificial contradictions.
7. You may evaluate ONLY expectation IDs that are explicitly provided in previous_thesis.active_expectations.
8. Every event reference in actual_event_refs and evidence_references must match an actual event_id from the supplied timeline.

EXTERNAL CONTEXT & GLOBAL SHOCK RADAR PROTOCOL:
9. External context (macro events, global equity futures, Asian bourses, India VIX / CBOE VIX, US 10Y yields, crude oil, geopolitical developments) is strictly supplementary background.
10. Underlying canonical market evidence (spot, futures, OI structure, order flow) is PRIMARY.
11. Never allow external news/events or global moves alone to generate a CALL or PUT verdict (e.g. Nasdaq futures dropping does not automatically mean PUT; rising VIX does not automatically mean bearish).
12. Compare external radar movements against actual domestic Indian market transmission:
    - If external futures drop sharply but NIFTY futures remain firm and Indian order flow stays supportive: note that external weakness is not currently transmitting into domestic market structure.
    - If external weakness coincides with domestic selling aggression and PE response strengthening: note the cross-market coherence.
13. If external context conflicts with live market structure, explicitly state the contradiction in strongest_contradiction.
14. Distinguish verification streams:
    - verified_external_context: independently validated against official primary registries.
    - unverified_external_context: tentative background; NEVER treat as established facts.
    - conflicted_external_context: explicit discrepancies between external claims and authoritative primary sources; state the conflict in strongest_contradiction or data_gaps and rely on the authoritative value.
15. If external context is stale, unverified, conflicted, or unavailable, state it in data_gaps and rely solely on canonical market evidence.

Execute your analysis strictly across the following 9 internal passes:
PASS 1 (OBSERVE): What objectively changed in canonical market facts?
PASS 2 (SEQUENCE): Reconstruct chronological order from timestamps. What actually occurred first in the evidence timeline?
PASS 3 (POSITIONING): What strike-wise positioning is forming or unwinding based on closed OI deltas?
PASS 4 (CALL CASE): Construct the strongest factual Bull thesis supported by evidence.
PASS 5 (PUT CASE): Construct the strongest factual Bear thesis supported by evidence.
PASS 6 (NO-TRADE CASE): Construct the strongest evidence-backed NO-TRADE interpretation: why neither CALL nor PUT currently forms a sufficiently coherent market thesis from the supplied evidence.
PASS 7 (SELF-ATTACK): Actively challenge your favored interpretation against counter-evidence and external context contradictions.
PASS 8 (EXPECTATION EVALUATION): Evaluate previous pre-registered expectations (SUPPORTED, PARTIALLY_SUPPORTED, CONTRADICTED, UNRESOLVED) referencing actual event IDs.
PASS 9 (PRE-REGISTER & EMIT): Update thesis state and pre-register testable forward expectations with explicit invalidation conditions.
"""


class SolReasoningOrchestrator:
    """Orchestrates the 9-Pass reasoning cycle for GPT-5.6 Sol."""

    def __init__(
        self,
        model_adapter: Optional[SolModelAdapter] = None,
        thesis_memory: Optional[ThesisMemory] = None,
        memory: Optional[EventSourcedMarketMemory] = None,
    ) -> None:
        self.adapter = model_adapter or SolModelAdapter()
        self.thesis_memory = thesis_memory or ThesisMemory()
        self.memory = memory or EventSourcedMarketMemory()

    def execute_reasoning_cycle(
        self,
        snapshot: SolEvidenceSnapshot,
        recent_events: Optional[List[MarketEvent]] = None,
        cycle_id: Optional[str] = None,
        external_context: Optional[Any] = None,
        commit_context: Optional[Callable[[], ContextManager[bool]]] = None,
    ) -> Tuple[ThesisState, SolBeaconOutput, Dict[str, Any], SolModelRequestEnvelope]:
        """Execute one complete reasoning pass across canonical data with single canonical cycle_id."""
        # 1. Enforce Fail-Closed Field Allowlist Verification
        ProvenanceGuard.verify_field_level_allowlist(snapshot.to_dict(), strict=True)

        # 2. Establish Canonical Cycle ID before any invocation
        canonical_cycle_id = cycle_id or f"cyc_{uuid.uuid4().hex[:12]}"

        # 3. Check Upstream System Health (Fail-Closed on unavailable or off-market)
        if snapshot.system_status in {SystemStatus.UNAVAILABLE, SystemStatus.OFF_MARKET}:
            return self._build_system_unavailable_state(snapshot, canonical_cycle_id)

        # 4. Retrieve context from memory
        prev_thesis = self.thesis_memory.get_active_thesis()
        events = recent_events or self.memory.get_recent_raw_events(limit=25)
        active_story = self.memory.get_active_story()

        known_event_ids: Set[str] = {e.event_id for e in self.memory.get_all_session_events()}
        known_expectation_ids: Set[str] = {e.expectation_id for e in prev_thesis.active_expectations}

        # 5. Prepare structured user payload
        snapshot_dict = snapshot.to_dict()
        for key in ("source_hashes", "vob_free_verified", "schema_version", "canonical_snapshot_id", "identity_quality", "replay_stable"):
            snapshot_dict.pop(key, None)

        user_payload: Dict[str, Any] = {
            "cycle_id": canonical_cycle_id,
            "snapshot": snapshot_dict,
            "active_market_story": active_story.to_dict(),
            "recent_event_timeline": [e.to_dict() for e in events],
            "previous_thesis": {
                "thesis_id": prev_thesis.thesis_id,
                "market_verdict": prev_thesis.market_verdict.value if prev_thesis.market_verdict else None,
                "developing_state": prev_thesis.developing_state.value,
                "core_narrative": prev_thesis.core_narrative,
                "active_expectations": [
                    e.to_dict() for e in prev_thesis.active_expectations
                ],
            },
            "external_context": external_context.to_projection_dict() if external_context and hasattr(external_context, "to_projection_dict") else None,
        }

        # 6. Invoke Sol Model Adapter with Request Envelope
        parsed_output, telemetry, envelope = self.adapter.invoke_reasoning(
            cycle_id=canonical_cycle_id,
            system_prompt=SYSTEM_PROMPT,
            user_payload=user_payload,
        )

        now_utc = datetime.now(timezone.utc).isoformat()
        now_ist = snapshot.timestamp_ist

        if parsed_output is None:
            # Degraded Advisory Mode (System is alive, but Sol AI Reasoning is unconfigured/offline)
            beacon_out = SolBeaconOutput(
                system_status=snapshot.system_status.value,
                reasoning_status=ReasoningStatus.DEGRADED_ADVISORY.value,
                market_verdict=None,  # Do NOT output fake NO_TRADE
                developing_state=DevelopingState.UNRESOLVED.value,
                why_bullets=[
                    "Sol AI Reasoning provider offline or unconfigured",
                    f"Canonical Sensorium active: Spot {snapshot.spot_ltp or 'N/A'}",
                    "Market thesis suspended to prevent ungrounded signals",
                ],
                main_contradiction="SOL_MODEL_NOT_INVOKED",
                what_changed="Advisory reasoning unconfigured.",
                thesis_timestamp_ist=now_ist,
                feed_age_ms=snapshot.dhan_quote_age_ms,
                configured_model=self.adapter.configured_model,
                actually_invoked_model="NONE",
            )
            return prev_thesis, beacon_out, telemetry, envelope

        # 7. Validate Evidence References and Expectation IDs
        is_valid_refs, ref_errors = EvidenceReferenceValidator.validate_references(
            model_output=parsed_output,
            known_event_ids=known_event_ids,
            known_expectation_ids=known_expectation_ids,
            current_snapshot_id=snapshot.snapshot_id,
        )

        if not is_valid_refs:
            # Invalid model output must NOT become a valid market thesis or fake NO_TRADE
            telemetry["status"] = "INVALID_EVIDENCE_REFERENCES"
            telemetry["validation_errors"] = ref_errors
            beacon_out = SolBeaconOutput(
                system_status=snapshot.system_status.value,
                reasoning_status=ReasoningStatus.OUTPUT_INVALID.value,
                market_verdict=None,  # Explicitly None
                developing_state=DevelopingState.UNRESOLVED.value,
                why_bullets=[
                    "Model output cited invalid or non-existent evidence references",
                    f"Validation errors: {ref_errors[:1]}",
                    "Market thesis rejected to preserve evidence grounding",
                ],
                main_contradiction="INVALID_EVIDENCE_CITATION",
                what_changed="Model output failed reference validation.",
                thesis_timestamp_ist=now_ist,
                feed_age_ms=snapshot.dhan_quote_age_ms,
                configured_model=self.adapter.configured_model,
                actually_invoked_model=telemetry.get("successful_reasoning_model", "NONE"),
            )
            return prev_thesis, beacon_out, telemetry, envelope

        # 8. Parse and Validate Model Output Types
        try:
            verdict_str = str(parsed_output.get("market_verdict", "")).upper()
            verdict = MarketThesisVerdict[verdict_str] if verdict_str in MarketThesisVerdict.__members__ else None
        except Exception:
            verdict = None

        if verdict is None:
            # Invalid verdict format fails closed
            telemetry["status"] = "INVALID_VERDICT_ENUM"
            beacon_out = SolBeaconOutput(
                system_status=snapshot.system_status.value,
                reasoning_status=ReasoningStatus.OUTPUT_INVALID.value,
                market_verdict=None,
                developing_state=DevelopingState.UNRESOLVED.value,
                why_bullets=["Model returned unrecognized market verdict enum"],
                main_contradiction="OUTPUT_SCHEMA_VIOLATION",
                what_changed="Invalid verdict format.",
                thesis_timestamp_ist=now_ist,
                feed_age_ms=snapshot.dhan_quote_age_ms,
                configured_model=self.adapter.configured_model,
                actually_invoked_model=telemetry.get("successful_reasoning_model", "NONE"),
            )
            return prev_thesis, beacon_out, telemetry, envelope

        try:
            dev_str = str(parsed_output.get("developing_state", "")).upper()
            dev_state = DevelopingState[dev_str] if dev_str in DevelopingState.__members__ else None
        except Exception:
            dev_state = None

        canonical_market_state = (
            resolve_canonical_market_state(verdict, dev_state)
            if dev_state is not None
            else None
        )
        if dev_state is None or canonical_market_state is None:
            telemetry["status"] = "INVALID_FIVE_STATE_CONTRACT"
            beacon_out = SolBeaconOutput(
                system_status=snapshot.system_status.value,
                reasoning_status=ReasoningStatus.OUTPUT_INVALID.value,
                market_verdict=None,
                developing_state=DevelopingState.UNRESOLVED.value,
                why_bullets=["Gemini returned conflicting market states"],
                main_contradiction="OUTPUT_SCHEMA_VIOLATION",
                what_changed="Invalid market-state combination.",
                thesis_timestamp_ist=now_ist,
                feed_age_ms=snapshot.dhan_quote_age_ms,
                configured_model=self.adapter.configured_model,
                actually_invoked_model=telemetry.get("successful_reasoning_model", "NONE"),
            )
            return prev_thesis, beacon_out, telemetry, envelope

        commit_scope = commit_context() if commit_context else nullcontext(True)
        with commit_scope as session_is_current:
            if not session_is_current:
                telemetry["status"] = "OBSOLETE_SESSION_RESULT"
                telemetry["discarded"] = True
                obsolete_beacon = SolBeaconOutput(
                    system_status=SystemStatus.UNAVAILABLE.value,
                    reasoning_status=ReasoningStatus.NOT_INVOKED.value,
                    market_verdict=None,
                    developing_state=DevelopingState.UNRESOLVED.value,
                    why_bullets=["Obsolete provider response discarded at session boundary"],
                    main_contradiction="OBSOLETE_SESSION_RESULT",
                    what_changed="No current-session state was changed.",
                    thesis_timestamp_ist=now_ist,
                    feed_age_ms=snapshot.dhan_quote_age_ms,
                    configured_model=self.adapter.configured_model,
                    actually_invoked_model=telemetry.get("successful_reasoning_model", "NONE"),
                )
                return prev_thesis, obsolete_beacon, telemetry, envelope

            # 9. Record Verified Evaluations of Previous Expectations
            evaluations: List[ExpectationEvaluationRecord] = []
            raw_evals = parsed_output.get("expectation_evaluations", [])
            if isinstance(raw_evals, list):
                for e_dict in raw_evals:
                    if isinstance(e_dict, dict) and "expectation_id" in e_dict:
                        exp_id = str(e_dict["expectation_id"])
                        if exp_id in known_expectation_ids:
                            res_str = str(e_dict.get("result", "UNRESOLVED")).upper()
                            res_enum = ExpectationResult[res_str] if res_str in ExpectationResult.__members__ else ExpectationResult.UNRESOLVED
                            event_refs = [str(r) for r in e_dict.get("actual_event_refs", []) if str(r) in known_event_ids]
                            eval_rec = self.thesis_memory.record_evaluation(
                                expectation_id=exp_id,
                                result=res_enum,
                                actual_event_refs=event_refs,
                                evaluation_notes=str(e_dict.get("notes", "")),
                            )
                            evaluations.append(eval_rec)

            # 10. Pre-Register New Immutable Forward Expectations
            new_expectations: List[ExpectationRecord] = []
            raw_expectations = parsed_output.get("pre_registered_expectations", [])
            if isinstance(raw_expectations, list):
                for exp_dict in raw_expectations:
                    if isinstance(exp_dict, dict) and "expected_condition" in exp_dict:
                        exp_rec = self.thesis_memory.record_expectation(
                            cycle_id=canonical_cycle_id,
                            evidence_snapshot_id=snapshot.snapshot_id,
                            condition=str(exp_dict.get("expected_condition", "")),
                            invalidation_if=str(exp_dict.get("invalidation_condition", "")),
                            model_identifier=self.adapter.configured_model,
                        )
                        new_expectations.append(exp_rec)

            # 11. Construct Updated Thesis State with Distinct Lineage
            new_thesis_id = f"ths_{uuid.uuid4().hex[:8]}"
            contradiction = str(parsed_output.get("strongest_contradiction", "NONE_OBSERVED"))
            if not contradiction or contradiction.strip().lower() in {"none", "null", ""}:
                contradiction = "NONE_OBSERVED"

            new_thesis = ThesisState(
                thesis_id=new_thesis_id,
                created_at_utc=prev_thesis.created_at_utc,
                updated_at_utc=now_utc,
                market_verdict=verdict,
                developing_state=dev_state,
                core_narrative=str(parsed_output.get("core_narrative", "")),
                what_changed=str(parsed_output.get("what_changed", "")),
                positioning_story=str(parsed_output.get("positioning_story", "")),
                oi_story=str(parsed_output.get("oi_story", "")),
                flow_story=str(parsed_output.get("flow_story", "")),
                option_response_story=str(parsed_output.get("option_response_story", "")),
                call_case=str(parsed_output.get("call_case", "")),
                put_case=str(parsed_output.get("put_case", "")),
                no_trade_case=str(parsed_output.get("no_trade_case", "")),
                strongest_contradiction=contradiction,
                active_expectations=new_expectations,
                evaluation_history=evaluations,
                data_gaps=list(parsed_output.get("data_gaps", [])),
                evidence_references=list(parsed_output.get("evidence_references", [])),
                configured_model=self.adapter.configured_model,
                actually_invoked_model=telemetry.get("successful_reasoning_model", "NONE"),
            )

            self.thesis_memory.update_thesis(new_thesis)

            # 12. Construct Minimal Beacon Output
            why_bullets = parsed_output.get("why_bullets", [])
            if not isinstance(why_bullets, list) or not why_bullets:
                why_bullets = [
                    new_thesis.flow_story[:80],
                    new_thesis.oi_story[:80],
                    new_thesis.option_response_story[:80],
                ]

            beacon_out = SolBeaconOutput(
                system_status=snapshot.system_status.value,
                reasoning_status=ReasoningStatus.ACTIVE_REASONING.value,
                market_verdict=verdict.value,
                developing_state=dev_state.value,
                why_bullets=[str(b) for b in why_bullets[:3]],
                main_contradiction=new_thesis.strongest_contradiction,
                what_changed=new_thesis.what_changed,
                thesis_timestamp_ist=now_ist,
                feed_age_ms=snapshot.dhan_quote_age_ms,
                configured_model=self.adapter.configured_model,
                actually_invoked_model=telemetry.get("successful_reasoning_model", "NONE"),
            )

            return new_thesis, beacon_out, telemetry, envelope

    def _build_system_unavailable_state(
        self, snapshot: SolEvidenceSnapshot, cycle_id: str
    ) -> Tuple[ThesisState, SolBeaconOutput, Dict[str, Any], SolModelRequestEnvelope]:
        """Construct fail-closed state when system/data is unavailable or off-market."""
        prev_thesis = self.thesis_memory.get_active_thesis()

        beacon_out = SolBeaconOutput(
            system_status=snapshot.system_status.value,
            reasoning_status=ReasoningStatus.NOT_INVOKED.value,
            market_verdict=None,  # Explicitly None, NOT NO_TRADE
            developing_state=DevelopingState.UNRESOLVED.value,
            why_bullets=[
                f"System State: {snapshot.system_status.value}",
                "Feed disconnected or market session closed",
                "Market thesis suspended",
            ],
            main_contradiction=f"SYSTEM_{snapshot.system_status.value}",
            what_changed="System data availability state change.",
            thesis_timestamp_ist=snapshot.timestamp_ist,
            feed_age_ms=snapshot.dhan_quote_age_ms,
            configured_model=self.adapter.configured_model,
            actually_invoked_model="NONE",
        )
        telemetry = {
            "cycle_id": cycle_id,
            "status": "FAIL_CLOSED_SYSTEM_STATUS",
            "system_status": snapshot.system_status.value,
            "actually_invoked_model": "NONE",
            "api_latency": "NOT MEASURED",
        }
        envelope = SolModelRequestEnvelope(
            cycle_id=cycle_id,
            prompt_version="2.0.0-p0.2",
            prompt_hash="",
            input_hash="",
            system_prompt="",
            user_payload={},
            configured_model=self.adapter.configured_model,
            requested_model=self.adapter.configured_model,
            reasoning_effort="none",
        )
        return prev_thesis, beacon_out, telemetry, envelope
