"""The 9-Pass Sol Market Brain Reasoning Protocol & Orchestrator (P0.3B Production Pacing).

Enforces structured causal reasoning with neutral framing, canonical cycle identity,
fail-closed evidence citation validation, event cursor accumulation, and honest separation of model failure from NO_TRADE.
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
    SOL_STRUCTURED_OUTPUT_JSON_SCHEMA,
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
5. Do NOT invent arbitrary confidence percentages, arbitrary weights, or linear score sums.
6. If the evidence shows clean structural alignment without contradiction, output strongest_contradiction as "NONE_OBSERVED". Never invent artificial contradictions.
7. You may evaluate ONLY expectation IDs that are explicitly provided in previous_thesis.active_expectations.
8. Every event reference in actual_event_refs and evidence_references must match an actual event_id from the supplied timeline.
9. Think deeply internally before committing to the structured answer. Do not output raw chain-of-thought text.

EXTERNAL CONTEXT & GLOBAL SHOCK RADAR PROTOCOL:
10. External context (macro events, global equity futures, Asian bourses, India VIX / CBOE VIX, US 10Y yields, crude oil, geopolitical developments) is strictly supplementary background.
11. Underlying canonical market evidence (spot, futures, OI structure, order flow) is PRIMARY.
12. Never allow external news/events or global moves alone to generate a CALL or PUT verdict.
13. Compare external radar movements against actual domestic Indian market transmission.
14. If external context conflicts with live market structure, explicitly state the contradiction in strongest_contradiction.
15. If external context is stale, unverified, conflicted, or unavailable, state it in data_gaps and rely solely on canonical market evidence.

Execute your analysis strictly across the following 9 internal passes:
PASS 1 (OBSERVE): What objectively changed in canonical market facts?
PASS 2 (SEQUENCE): Reconstruct chronological order from timestamps. What actually occurred first in the evidence timeline?
PASS 3 (POSITIONING): What strike-wise positioning is forming or unwinding based on closed OI deltas?
PASS 4 (CALL CASE): Construct the strongest factual Bull thesis supported by evidence.
PASS 5 (PUT CASE): Construct the strongest factual Bear thesis supported by evidence.
PASS 6 (NO-TRADE CASE): Construct the strongest evidence-backed NO-TRADE interpretation.
PASS 7 (SELF-ATTACK): Actively challenge your favored interpretation against counter-evidence and external context contradictions.
PASS 8 (EXPECTATION EVALUATION): Evaluate previous pre-registered expectations (SUPPORTED, PARTIALLY_SUPPORTED, CONTRADICTED, UNRESOLVED) referencing actual event IDs.
PASS 9 (PRE-REGISTER & EMIT): Update thesis state and pre-register testable forward expectations with explicit invalidation conditions.
"""


def validate_structured_model_output(value: Any, schema: Optional[Dict[str, Any]] = None) -> List[str]:
    """Validate provider JSON independently of provider-side schema enforcement."""

    errors: List[str] = []

    def visit(node: Any, schema: Dict[str, Any], path: str) -> None:
        expected = schema.get("type")
        if expected == "object":
            if not isinstance(node, dict):
                errors.append(f"{path}: expected object")
                return
            properties = schema.get("properties", {})
            for required in schema.get("required", []):
                if required not in node:
                    errors.append(f"{path}.{required}: required field missing")
            if schema.get("additionalProperties") is False:
                for key in node:
                    if key not in properties:
                        errors.append(f"{path}.{key}: unexpected field")
            for key, child in node.items():
                child_schema = properties.get(key)
                if isinstance(child_schema, dict):
                    visit(child, child_schema, f"{path}.{key}")
        elif expected == "array":
            if not isinstance(node, list):
                errors.append(f"{path}: expected array")
                return
            if "maxItems" in schema and len(node) > schema["maxItems"]:
                errors.append(f"{path}: too many items")
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for index, child in enumerate(node):
                    visit(child, item_schema, f"{path}[{index}]")
        elif expected == "string" and not isinstance(node, str):
            errors.append(f"{path}: expected string")
        enum_values = schema.get("enum")
        if enum_values is not None and node not in enum_values:
            errors.append(f"{path}: value outside allowed enum")

    visit(value, schema if schema is not None else SOL_STRUCTURED_OUTPUT_JSON_SCHEMA["schema"], "output")
    return errors


class SolReasoningOrchestrator:
    """Orchestrates the 9-Pass reasoning cycle for GPT-5.6 Sol / Gemini 3.7 Flash."""

    def __init__(
        self,
        model_adapter: Optional[Any] = None,
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
        is_manual: bool = False,
        use_reserved_quota: bool = False,
    ) -> Tuple[ThesisState, SolBeaconOutput, Dict[str, Any], SolModelRequestEnvelope]:
        """Execute one complete reasoning pass across canonical data with single canonical cycle_id."""
        # 1. Enforce Fail-Closed Field Allowlist Verification
        ProvenanceGuard.verify_field_level_allowlist(snapshot.to_dict(), strict=True)

        # 2. Establish Canonical Cycle ID before any invocation
        canonical_cycle_id = cycle_id or f"cyc_{uuid.uuid4().hex[:12]}"

        # 3. Check Upstream System Health (Fail-Closed on unavailable or off-market unless manual test)
        if snapshot.system_status in {SystemStatus.UNAVAILABLE, SystemStatus.OFF_MARKET} and not is_manual:
            return self._build_system_unavailable_state(snapshot, canonical_cycle_id)

        # 4. Retrieve context and event cursor from memory (ZERO event loss)
        prev_thesis = self.thesis_memory.get_active_thesis()
        all_events = self.memory.get_all_session_events()
        last_cursor = self.thesis_memory.last_analyzed_event_id

        if recent_events is not None:
            events = recent_events
        elif not last_cursor:
            events = list(all_events)
        else:
            cursor_idx = -1
            for idx, e in enumerate(all_events):
                if e.event_id == last_cursor:
                    cursor_idx = idx
                    break
            if cursor_idx >= 0:
                events = list(all_events[cursor_idx + 1:])
            else:
                events = list(all_events)

        active_story = self.memory.get_active_story()
        known_event_ids: Set[str] = {e.event_id for e in (all_events or events)}
        known_expectation_ids: Set[str] = {e.expectation_id for e in prev_thesis.active_expectations}

        # 5. Prepare structured user payload with clear delimiters and zero lossless redundancy
        snapshot_dict = snapshot.to_dict()
        for key in ("source_hashes", "vob_free_verified", "schema_version", "canonical_snapshot_id", "identity_quality", "replay_stable"):
            snapshot_dict.pop(key, None)

        avail_matrix = snapshot_dict.get("availability_matrix", {})

        user_payload: Dict[str, Any] = {
            "cycle_id": canonical_cycle_id,
            "snapshot": snapshot_dict,
            "recent_event_timeline": [e.to_dict() for e in events],
            "active_market_story": active_story.to_dict(),
            "previous_thesis": {
                "thesis_id": prev_thesis.thesis_id,
                "market_verdict": prev_thesis.market_verdict.value if prev_thesis.market_verdict else None,
                "developing_state": prev_thesis.developing_state.value,
                "core_narrative": prev_thesis.core_narrative,
                "strongest_contradiction": prev_thesis.strongest_contradiction,
                "active_expectations": [
                    e.to_dict() for e in prev_thesis.active_expectations
                ],
            },
            "external_context": external_context.to_projection_dict() if external_context and hasattr(external_context, "to_projection_dict") else None,
            "system_truth_contract": {
                "role": "CITADEL is deterministic sensor/calculation authority; model is contextual/temporal interpretation layer.",
                "constraints": "Use ONLY supplied evidence. Never invent data. Zero VOB. Distinguish fact from interpretation and data gaps.",
            },
            "session": {
                "timestamp_ist": snapshot.timestamp_ist,
                "timestamp_utc": snapshot.timestamp_utc,
                "market_session_date": snapshot.market_session_date,
                "system_status": snapshot.system_status.value,
                "snapshot_id": snapshot.snapshot_id,
            },
            "data_quality": avail_matrix,
            "task": (
                "Re-evaluate the market context from scratch using NOW (snapshot), then compare it against PRIOR THESIS using CHANGES (recent_event_timeline). "
                "Determine whether the previous thesis strengthened, weakened, changed, or remains unresolved. "
                "Explicitly search for evidence that contradicts the preferred view. "
                "Think deeply internally before committing to the structured answer."
            ),
        }

        # 6. Invoke Sol Model Adapter with Request Envelope & Pacing governor arguments
        invoke_kwargs = {
            "cycle_id": canonical_cycle_id,
            "system_prompt": SYSTEM_PROMPT,
            "user_payload": user_payload,
        }
        if hasattr(self.adapter, "invoke_reasoning"):
            import inspect
            sig = inspect.signature(self.adapter.invoke_reasoning)
            if "is_manual" in sig.parameters:
                invoke_kwargs["is_manual"] = is_manual
            if "use_reserved_quota" in sig.parameters:
                invoke_kwargs["use_reserved_quota"] = use_reserved_quota
            if "new_events_count" in sig.parameters:
                invoke_kwargs["new_events_count"] = len(events)

        parsed_output, telemetry, envelope = self.adapter.invoke_reasoning(**invoke_kwargs)

        now_utc = datetime.now(timezone.utc).isoformat()
        now_ist = snapshot.timestamp_ist

        if parsed_output is None:
            # Degraded Advisory Mode (System is alive, but Sol AI Reasoning is unconfigured/offline/held by pacing)
            status_desc = telemetry.get("status", "UNAVAILABLE")
            beacon_out = SolBeaconOutput(
                system_status=snapshot.system_status.value,
                reasoning_status=ReasoningStatus.DEGRADED_ADVISORY.value,
                market_verdict=None,  # Do NOT output fake NO_TRADE
                developing_state=DevelopingState.UNRESOLVED.value,
                why_bullets=[
                    f"Reasoning state: {status_desc}",
                    f"Canonical Sensorium active: Spot {snapshot.spot_ltp or 'N/A'}",
                    "Market thesis suspended to prevent ungrounded signals",
                ],
                main_contradiction=f"SOL_PROVIDER_{status_desc}",
                what_changed="Advisory reasoning unconfigured or cooling down.",
                thesis_timestamp_ist=now_ist,
                feed_age_ms=snapshot.dhan_quote_age_ms,
                configured_model=self.adapter.configured_model,
                actually_invoked_model="NONE",
            )
            return prev_thesis, beacon_out, telemetry, envelope

        # 7. Validate the whole structured response independently of the provider.
        schema_errors = validate_structured_model_output(parsed_output)
        if schema_errors:
            telemetry["status"] = "OUTPUT_SCHEMA_INVALID"
            telemetry["validation_errors"] = schema_errors
            beacon_out = SolBeaconOutput(
                system_status=snapshot.system_status.value,
                reasoning_status=ReasoningStatus.OUTPUT_INVALID.value,
                market_verdict=None,
                developing_state=DevelopingState.UNRESOLVED.value,
                why_bullets=["Gemini returned an invalid structured response"],
                main_contradiction="OUTPUT_SCHEMA_VIOLATION",
                what_changed="Invalid model output was rejected.",
                thesis_timestamp_ist=now_ist,
                feed_age_ms=snapshot.dhan_quote_age_ms,
                configured_model=self.adapter.configured_model,
                actually_invoked_model=telemetry.get("successful_reasoning_model", "NONE"),
            )
            return prev_thesis, beacon_out, telemetry, envelope

        # 8. Validate Evidence References and Expectation IDs
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
                market_verdict=None,
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

            new_thesis_id = f"ths_{uuid.uuid4().hex[:8]}"

            # 9. Build verified evaluations without mutating durable memory yet.
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
                            eval_rec = ExpectationEvaluationRecord(
                                evaluation_id=f"eval_{uuid.uuid4().hex[:12]}",
                                expectation_id=exp_id,
                                evaluated_at_utc=now_utc,
                                result=res_enum,
                                actual_event_refs=event_refs,
                                evaluation_notes=str(e_dict.get("notes", "")),
                                evidence_refs=[],
                            )
                            evaluations.append(eval_rec)

            # 10. Build new expectations without mutating durable memory yet.
            new_expectations: List[ExpectationRecord] = []
            raw_expectations = parsed_output.get("pre_registered_expectations", [])
            if isinstance(raw_expectations, list):
                for exp_dict in raw_expectations:
                    if isinstance(exp_dict, dict) and "expected_condition" in exp_dict:
                        exp_rec = ExpectationRecord(
                            expectation_id=f"exp_{uuid.uuid4().hex[:12]}",
                            cycle_id=canonical_cycle_id,
                            thesis_id=new_thesis_id,
                            created_at_utc=now_utc,
                            evidence_snapshot_id=snapshot.snapshot_id,
                            expected_condition=str(exp_dict.get("expected_condition", "")),
                            invalidation_condition=str(exp_dict.get("invalidation_condition", "")),
                            evidence_refs=[],
                            model_identifier=self.adapter.configured_model,
                        )
                        new_expectations.append(exp_rec)

            # 12. Construct Updated Thesis State with Distinct Lineage
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

            self.thesis_memory.commit_reasoning_result(
                new_thesis,
                last_analyzed_event_id=(
                    events[-1].event_id if events else self.thesis_memory.last_analyzed_event_id
                ),
                expectations=new_expectations,
                evaluations=evaluations,
            )

            # 13. Construct Minimal Beacon Output
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
            market_verdict=None,
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
