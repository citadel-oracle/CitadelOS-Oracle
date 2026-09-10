"""Phase-1.1 Live Cognitive Decision Coordinator (Truth Repair).

Coordinates the three independent model roles:
1. Qwen 3.8 27B Fast Sentinel (continuous fast observer).
2. Gemini 3.7 Flash Independent Senior Reviewer (zero veto authority).
3. GPT-OSS 120B Primary Deep Synthesizer (5 concurrent hypotheses).

Strict Zero-Echo-Chamber Execution:
CANONICAL EVIDENCE
   ├──> QWEN SENTINEL (independent)
   ├──> GEMINI REVIEWER (independent)
   └──> GPT SYNTHESIZER (receives evidence + hypotheses marked UNTRUSTED_MODEL_HYPOTHESIS)

Zero deterministic trade-direction fallbacks:
If a model cannot run, the system preserves last valid output and reports
UNAVAILABLE / RATE_LIMITED / AWAITING_FIRST_ANALYSIS, never an invented trade state.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from src.oracle_sol.brain_packet_compiler import BrainPacket
from src.oracle_sol.contracts import (
    GeminiReview,
    PrimarySynthesisOutput,
    QwenObservation,
)
from src.oracle_sol.evidence_gate import EvidenceGate, GateValidationResult
from src.oracle_sol.freshness_scheduler import FreshnessScheduler
from src.oracle_sol.gemini_reviewer_adapter import GeminiReviewerAdapter
from src.oracle_sol.qwen_sentinel_adapter import QwenSentinelAdapter
from src.oracle_sol.quota_governor import CognitiveQuotaGovernor
from src.oracle_sol.synthesizer_adapter import SynthesizerAdapter
from src.oracle_sol.thesis_graph import ThesisGraph, ThesisNode

logger = logging.getLogger(__name__)


class Phase1CognitiveCoordinator:
    """Manages multi-model execution, freshness, quota governance, and fail-closed isolation."""

    def __init__(
        self,
        thesis_graph: Optional[ThesisGraph] = None,
        evidence_gate: Optional[EvidenceGate] = None,
        quota_governor: Optional[CognitiveQuotaGovernor] = None,
        freshness_scheduler: Optional[FreshnessScheduler] = None,
        qwen_sentinel: Optional[QwenSentinelAdapter] = None,
        gpt_synthesizer: Optional[SynthesizerAdapter] = None,
        gemini_reviewer: Optional[GeminiReviewerAdapter] = None,
        luna_adapter: Optional[Any] = None,
        analyst_mode: Optional[str] = None,
    ) -> None:
        self.thesis_graph = thesis_graph or ThesisGraph()
        self.evidence_gate = evidence_gate or EvidenceGate(thesis_graph=self.thesis_graph)
        self.quota_governor = quota_governor or CognitiveQuotaGovernor()
        self.freshness_scheduler = freshness_scheduler or FreshnessScheduler(quota_governor=self.quota_governor)

        if analyst_mode is not None:
            self.analyst_mode = analyst_mode
        elif luna_adapter is not None:
            self.analyst_mode = "luna"
        elif qwen_sentinel is not None or gpt_synthesizer is not None or gemini_reviewer is not None:
            self.analyst_mode = "legacy_multi_model"
        else:
            self.analyst_mode = "luna"

        if self.analyst_mode == "luna":
            from src.oracle_sol.luna_cognitive_adapter import LunaCognitiveAdapter
            self.luna_adapter = luna_adapter or LunaCognitiveAdapter()
        else:
            self.luna_adapter = luna_adapter

        self.qwen_sentinel = qwen_sentinel or QwenSentinelAdapter()
        self.gpt_synthesizer = gpt_synthesizer or SynthesizerAdapter()
        self.gemini_reviewer = gemini_reviewer or GeminiReviewerAdapter()

        self.last_qwen_obs: Optional[QwenObservation] = None
        self.last_gemini_rev: Optional[GeminiReview] = None
        self.last_synthesis: Optional[PrimarySynthesisOutput] = None
        self.last_luna_output: Optional[Dict[str, Any]] = None
        self.last_luna_telemetry: Optional[Dict[str, Any]] = None
        self.last_committed_thesis: Optional[ThesisNode] = None
        self._current_session_id: Optional[str] = None
        self._session_generation = 0
        self._state_lock = threading.RLock()
        self._last_cycle: Dict[str, Any] = {"status": "INITIALIZED", "models_attempted": []}

    def rollover_session(self, session_id: str) -> None:
        """Clear process-local model state while retaining durable prior history."""
        with self._state_lock:
            if self._current_session_id == session_id:
                return
            active = self.thesis_graph.get_active_thesis()
            if active is None or active.session_id != session_id:
                self.thesis_graph.rollover_session(session_id)
            self.last_qwen_obs = None
            self.last_gemini_rev = None
            self.last_synthesis = None
            self.last_luna_output = None
            self.last_luna_telemetry = None
            self.last_committed_thesis = None
            self.freshness_scheduler = FreshnessScheduler(quota_governor=self.quota_governor)
            self._current_session_id = session_id
            self._session_generation += 1
            self._last_cycle = {"status": "SESSION_RESET", "models_attempted": []}

    def execute_cycle(
        self,
        packet: BrainPacket,
        force_full_run: bool = False,
        acceptance_guard: Optional[Callable[[BrainPacket], bool]] = None,
    ) -> Dict[str, Any]:
        """Executes an event-aware cognitive cycle across configured model(s)."""
        if self._current_session_id != packet.session_id:
            self.rollover_session(packet.session_id)
        with self._state_lock:
            cycle_generation = self._session_generation

        started_at = datetime.now(timezone.utc).isoformat()

        if self.analyst_mode == "luna" and self.luna_adapter is not None:
            return self._execute_luna_cycle(
                packet=packet,
                acceptance_guard=acceptance_guard,
                started_at=started_at,
                cycle_generation=cycle_generation,
            )

        attempted = []
        gate_status: Optional[str] = None
        # A session rollover replaces the public scheduler immediately.  Keep
        # this cycle on its captured scheduler so a late old-session provider
        # completion cannot mutate the new session's freshness state.
        cycle_scheduler = self.freshness_scheduler

        def owns_generation() -> bool:
            with self._state_lock:
                return (
                    self._current_session_id == packet.session_id
                    and self._session_generation == cycle_generation
                )

        def still_current() -> bool:
            return owns_generation() and (
                acceptance_guard is None or bool(acceptance_guard(packet))
            )

        def stale_result(stage: str) -> Dict[str, Any]:
            stale_cycle = {
                "status": "STALE_RESULT_NOT_PROMOTED",
                "stage": stage,
                "session_id": packet.session_id,
                "input_revision": packet.revision,
                "evidence_frontier": packet.unseen_event_ids[-1] if packet.unseen_event_ids else None,
                "models_attempted": list(attempted),
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "gate_status": gate_status,
            }
            with self._state_lock:
                if (
                    self._current_session_id == packet.session_id
                    and self._session_generation == cycle_generation
                ):
                    self._last_cycle = stale_cycle
            payload = self.get_telemetry_payload(packet)
            payload["cycle"] = stale_cycle
            return payload

        if not still_current():
            return stale_result("BEFORE_PROVIDER")

        unseen_count = len(packet.unseen_event_ids)
        cycle_scheduler.update_canonical_state(
            latest_revision=packet.revision,
            unseen_events_count=unseen_count,
        )

        has_new_events = unseen_count > 0
        relationship_changed = bool(packet.temporal_relationships)

        # ── Step 1: Qwen Fast Sentinel (Independent) ──
        if force_full_run or cycle_scheduler.should_run_qwen(has_new_events, relationship_changed):
            attempted.append("qwen")
            try:
                cycle_scheduler.freshness["qwen"].is_running = True
                qwen_candidate = self.qwen_sentinel.observe(packet)
                # Learn real quota headers
                qwen_headers = getattr(getattr(self.qwen_sentinel, "backend_adapter", None), "rate_limits", {})
                self.quota_governor.update_from_groq_headers(
                    model_key="qwen",
                    rate_headers=qwen_headers,
                    http_status=self.qwen_sentinel.last_http_status,
                    latency_ms=qwen_candidate.latency_ms,
                )
                if qwen_candidate.status == "CURRENT":
                    if not still_current():
                        self.quota_governor.record_call_success(
                            "qwen", 250, qwen_candidate.latency_ms
                        )
                        cycle_scheduler.freshness["qwen"].is_running = False
                        return stale_result("AFTER_QWEN")
                    with self._state_lock:
                        if not owns_generation():
                            return stale_result("AFTER_QWEN")
                        self.last_qwen_obs = qwen_candidate
                    cycle_scheduler.record_model_completion(
                        model_key="qwen",
                        revision_analyzed=packet.revision,
                        tokens_consumed=250,
                        latency_ms=qwen_candidate.latency_ms,
                    )
                else:
                    if not still_current():
                        cycle_scheduler.freshness["qwen"].is_running = False
                        return stale_result("AFTER_QWEN")
                    with self._state_lock:
                        if not owns_generation():
                            return stale_result("AFTER_QWEN")
                        self.last_qwen_obs = qwen_candidate
                    cycle_scheduler.freshness["qwen"].is_running = False
            except Exception as exc:
                logger.error("Qwen Sentinel failure (isolated): %s", exc)
                cycle_scheduler.freshness["qwen"].is_running = False

        if not still_current():
            return stale_result("BEFORE_GEMINI")

        # ── Step 2: Gemini Senior Reviewer (Independent & Non-Blocking) ──
        if force_full_run or cycle_scheduler.should_run_gemini(self.last_qwen_obs, self.last_synthesis):
            attempted.append("gemini")
            try:
                cycle_scheduler.freshness["gemini"].is_running = True
                gemini_candidate = self.gemini_reviewer.review(packet)
                if gemini_candidate.status == "CURRENT":
                    if not still_current():
                        self.quota_governor.record_call_success(
                            "gemini", 800, gemini_candidate.latency_ms
                        )
                        cycle_scheduler.freshness["gemini"].is_running = False
                        return stale_result("AFTER_GEMINI")
                    with self._state_lock:
                        if not owns_generation():
                            return stale_result("AFTER_GEMINI")
                        self.last_gemini_rev = gemini_candidate
                    cycle_scheduler.record_model_completion(
                        model_key="gemini",
                        revision_analyzed=packet.revision,
                        tokens_consumed=800,
                        latency_ms=gemini_candidate.latency_ms,
                    )
                else:
                    if not still_current():
                        cycle_scheduler.freshness["gemini"].is_running = False
                        return stale_result("AFTER_GEMINI")
                    with self._state_lock:
                        if not owns_generation():
                            return stale_result("AFTER_GEMINI")
                        self.last_gemini_rev = gemini_candidate
                    cycle_scheduler.freshness["gemini"].is_running = False
            except Exception as exc:
                logger.warning("Gemini reviewer failure (isolated): %s", exc)
                cycle_scheduler.freshness["gemini"].is_running = False

        if not still_current():
            return stale_result("BEFORE_GPT")

        # ── Step 3: GPT-OSS Primary Deep Synthesizer (Zero Echo Chamber) ──
        if force_full_run or cycle_scheduler.should_run_gpt(self.last_qwen_obs, self.last_synthesis):
            attempted.append("gpt_oss")
            try:
                cycle_scheduler.freshness["gpt_oss"].is_running = True
                synth_candidate = self.gpt_synthesizer.synthesize(
                    packet=packet,
                    qwen_obs=self.last_qwen_obs,
                    gemini_rev=self.last_gemini_rev,
                )
                # Learn real quota headers
                gpt_headers = getattr(getattr(self.gpt_synthesizer, "backend_adapter", None), "rate_limits", {})
                self.quota_governor.update_from_groq_headers(
                    model_key="gpt_oss",
                    rate_headers=gpt_headers,
                    http_status=self.gpt_synthesizer.last_http_status,
                    latency_ms=synth_candidate.latency_ms,
                )

                if synth_candidate.status == "CURRENT":
                    if not still_current():
                        self.quota_governor.record_call_success(
                            "gpt_oss", 1200, synth_candidate.latency_ms
                        )
                        cycle_scheduler.freshness["gpt_oss"].is_running = False
                        return stale_result("BEFORE_THESIS_COMMIT")
                    cycle_scheduler.record_model_completion(
                        model_key="gpt_oss",
                        revision_analyzed=packet.revision,
                        tokens_consumed=1200,
                        latency_ms=synth_candidate.latency_ms,
                    )
                    # Commit thesis via EvidenceGate ONLY on genuine successful inference
                    gate_result = self._commit_synthesis_to_gate(
                        packet,
                        synth_candidate,
                        commit_guard=acceptance_guard,
                    )
                    gate_status = gate_result.status
                    if gate_status == "STALE_RESULT_NOT_PROMOTED":
                        return stale_result("EVIDENCE_GATE_COMMIT")
                    if gate_result.is_valid and gate_result.committed_thesis:
                        with self._state_lock:
                            if not owns_generation():
                                return stale_result("AFTER_THESIS_COMMIT")
                            self.last_synthesis = synth_candidate
                            self.last_committed_thesis = gate_result.committed_thesis
                else:
                    if not still_current():
                        cycle_scheduler.freshness["gpt_oss"].is_running = False
                        return stale_result("AFTER_GPT")
                    with self._state_lock:
                        if not owns_generation():
                            return stale_result("AFTER_GPT")
                        self.last_synthesis = synth_candidate
                    cycle_scheduler.freshness["gpt_oss"].is_running = False

            except Exception as exc:
                logger.error("GPT Synthesizer failure (isolated): %s", exc)
                cycle_scheduler.freshness["gpt_oss"].is_running = False

        if not still_current():
            return stale_result("CYCLE_COMPLETE")
        final_cycle = {
            "status": (
                "COMMITTED"
                if gate_status == "COMMITTED"
                else "REJECTED"
                if gate_status
                else "NOT_ELIGIBLE"
                if not attempted
                else "COMPLETED_NO_COMMIT"
            ),
            "session_id": packet.session_id,
            "input_revision": packet.revision,
            "evidence_frontier": packet.unseen_event_ids[-1] if packet.unseen_event_ids else None,
            "models_attempted": attempted,
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "gate_status": gate_status,
        }
        with self._state_lock:
            self._last_cycle = final_cycle
        return self.get_telemetry_payload(packet)

    def _execute_luna_cycle(
        self,
        packet: BrainPacket,
        acceptance_guard: Optional[Callable[[BrainPacket], bool]] = None,
        started_at: Optional[str] = None,
        cycle_generation: int = 0,
    ) -> Dict[str, Any]:
        """Executes a solitary, bounded cognitive cycle using gpt-5.6-luna."""
        started_at = started_at or datetime.now(timezone.utc).isoformat()
        attempted = ["luna"]
        gate_status: Optional[str] = None

        def owns_generation() -> bool:
            with self._state_lock:
                return (
                    self._current_session_id == packet.session_id
                    and self._session_generation == cycle_generation
                )

        def still_current() -> bool:
            return owns_generation() and (
                acceptance_guard is None or bool(acceptance_guard(packet))
            )

        def stale_result(stage: str) -> Dict[str, Any]:
            stale_cycle = {
                "status": "STALE_RESULT_NOT_PROMOTED",
                "stage": stage,
                "session_id": packet.session_id,
                "input_revision": packet.revision,
                "evidence_frontier": packet.unseen_event_ids[-1] if packet.unseen_event_ids else None,
                "models_attempted": list(attempted),
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "gate_status": gate_status,
            }
            with self._state_lock:
                if (
                    self._current_session_id == packet.session_id
                    and self._session_generation == cycle_generation
                ):
                    self._last_cycle = stale_cycle
            payload = self.get_telemetry_payload(packet)
            payload["cycle"] = stale_cycle
            return payload

        # 1. Staleness check before calling provider
        if not still_current():
            return stale_result("BEFORE_LUNA")

        # 2. Invoke Luna via LunaCognitiveAdapter
        output, telemetry = self.luna_adapter.analyze(packet)

        # 3. Staleness check after Luna inference (essential for ~20-25s latency)
        if not still_current():
            return stale_result("AFTER_LUNA")

        if output and telemetry.get("status") == "CURRENT":
            # 4. Commit via EvidenceGate
            gate_result = self.evidence_gate.validate_and_commit(
                raw_response=output,
                packet=packet,
                model_name=self.luna_adapter.model_name,
                system_prompt="CITADEL Luna Production Cognitive Analyst",
                commit_guard=acceptance_guard,
                input_receipt=telemetry.get("input_receipt"),
            )
            gate_status = gate_result.status
            if gate_status == "STALE_RESULT_NOT_PROMOTED":
                return stale_result("EVIDENCE_GATE_COMMIT")

            if gate_result.is_valid and gate_result.committed_thesis:
                with self._state_lock:
                    if not owns_generation():
                        return stale_result("AFTER_THESIS_COMMIT")
                    self.last_committed_thesis = gate_result.committed_thesis
                    self.last_luna_output = output
                    self.last_luna_telemetry = telemetry
            else:
                logger.warning("EvidenceGate rejected Luna output: %s - %s", gate_status, gate_result.error_details)
        else:
            gate_status = telemetry.get("status") or "PROVIDER_UNAVAILABLE"
            with self._state_lock:
                self.last_luna_telemetry = telemetry

        if not still_current():
            return stale_result("CYCLE_COMPLETE")

        final_cycle = {
            "status": (
                "COMMITTED"
                if gate_status == "COMMITTED"
                else "REJECTED"
                if gate_status and gate_status not in ("CURRENT", "NOT_ELIGIBLE")
                else "COMPLETED_NO_COMMIT"
            ),
            "session_id": packet.session_id,
            "input_revision": packet.revision,
            "evidence_frontier": packet.unseen_event_ids[-1] if packet.unseen_event_ids else None,
            "models_attempted": attempted,
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "gate_status": gate_status,
        }
        with self._state_lock:
            self._last_cycle = final_cycle
        return self.get_telemetry_payload(packet)

    def _commit_synthesis_to_gate(
        self,
        packet: BrainPacket,
        synth: PrimarySynthesisOutput,
        commit_guard: Optional[Callable[[BrainPacket], bool]] = None,
    ) -> GateValidationResult:
        """Packages synthesis output into raw dict for EvidenceGate validation."""
        contra_summary = synth.reversal_watch.get("first_contradiction", "NONE")
        rw = synth.reversal_watch

        raw = {
            "observer": {"what_changed": f"Revision {synth.input_revision} analyzed.", "key_shifts": []},
            "market_story": {"narrative": "; ".join(synth.why_now), "sequence_unfolding": ""},
            "call_case": {"argument": synth.five_hypotheses.get("call_continuation", {}).get("why", ""), "evidence_ids": synth.evidence_ids},
            "put_case": {"argument": synth.five_hypotheses.get("put_continuation", {}).get("why", ""), "evidence_ids": synth.evidence_ids},
            "no_trade_case": {"argument": synth.five_hypotheses.get("no_trade_transition", {}).get("why", ""), "evidence_ids": synth.evidence_ids},
            "reversal_analysis": {
                "absorption_or_exhaustion": contra_summary,
                "failed_move_evidence": rw.get("what_failed", "NONE"),
                "reversal_developing": "REVERSAL" in synth.current_state,
                "evidence_ids": synth.evidence_ids,
            },
            "reversal_watch": {
                "direction": rw.get("direction", "NONE"),
                "earliest_contradiction_event_id": None,
                "supporting_evidence_ids": synth.evidence_ids,
                "opposing_evidence_ids": [],
                "aggression_price_response": rw.get("what_failed", "NONE"),
                "premium_confirmation": rw.get("premium_confirmation", "UNRESOLVED"),
                "failed_move": "SUPPORTED" if "REVERSAL" in synth.current_state else "UNRESOLVED",
                "reason_not_confirmed": rw.get("why_not_confirmed", ""),
            },
            "option_buyer_analysis": {
                "underlying_view": synth.current_state,
                "ce_premium_response": "UNRESOLVED",
                "pe_premium_response": "UNRESOLVED",
                "iv_response": "UNRESOLVED",
                "liquidity_or_spread": "UNRESOLVED",
                "option_buyer_side": synth.option_buyer_side,
                "reasoning": "; ".join(synth.why_now),
            },
            "contradictions": {
                "strongest_contradiction": contra_summary,
                "contradicting_evidence_ids": synth.evidence_ids,
            },
            "temporal_analysis": {
                "evolution_from_previous": "UNRESOLVED",
                "what_strengthened": "UNRESOLVED",
                "what_weakened": "UNRESOLVED",
                "what_superseded": "UNRESOLVED",
            },
            "external_context": {"interpretation": "MARKET_INTERNAL", "cited_external_event_ids": []},
            "counterfactual": {
                "opposite_thesis_conditions": "; ".join(synth.what_would_change_my_mind),
                "watch_triggers": synth.what_would_change_my_mind,
            },
            "human_miss_candidate": {"subtle_relationship": contra_summary, "cited_evidence_ids": synth.evidence_ids},
            "synthesis": {
                "state": synth.current_state,
                "no_trade_reason": "DIRECTION_UNCLEAR" if synth.current_state == "NO_TRADE" else "NOT_APPLICABLE",
                "transition_reason": synth.setup_family,
                "supporting_evidence_ids": synth.evidence_ids,
                "contradicting_evidence_ids": [],
                "unresolved_evidence_ids": [],
                "watch_next": synth.what_would_change_my_mind,
                "invalidation_conditions": synth.what_would_change_my_mind,
            },
            "entry_window": synth.entry_window,
            "why_now": synth.why_now,
            "what_would_change_my_mind": synth.what_would_change_my_mind,
            "five_hypotheses": synth.five_hypotheses,
            "qwen_observation": self.last_qwen_obs.to_dict() if self.last_qwen_obs else {},
            "gemini_review": self.last_gemini_rev.to_dict() if self.last_gemini_rev else {},
        }

        return self.evidence_gate.validate_and_commit(
            raw_response=raw,
            packet=packet,
            model_name=synth.model_name,
            system_prompt="Phase-1.1 Multi-Model Coordinator",
            commit_guard=commit_guard,
        )

    def get_telemetry_payload(self, packet: Optional[BrainPacket] = None) -> Dict[str, Any]:
        """Formats the authoritative Section K telemetry contract for frontend rendering."""
        active_thesis = self.thesis_graph.get_active_thesis()

        if self.analyst_mode == "luna":
            luna_out = self.last_luna_output
            luna_tel = self.last_luna_telemetry or {}

            state = active_thesis.state if active_thesis else (luna_out.get("state") if luna_out else "AWAITING_FIRST_ANALYSIS")
            entry_window = active_thesis.entry_window if active_thesis else (luna_out.get("entry_window", "WAIT") if luna_out else "WAIT")
            why_now = active_thesis.why_now if active_thesis else ([c["claim"] for c in luna_out.get("conclusions", []) if c.get("purpose") == "why_now"] if luna_out else ["Awaiting live cognitive state"])
            reversal_watch = active_thesis.reversal_watch if (active_thesis and active_thesis.reversal_watch) else ({"direction": "REVERSAL_WATCH"} if (luna_out and luna_out.get("thesis_evolution") == "REVERSAL_WATCH") else None)
            what_changed = active_thesis.what_changed if active_thesis else (luna_out.get("what_changed") if luna_out else None)

            primary_decision = {
                "state": state,
                "entry_window": entry_window,
                "why_now": why_now,
                "what_changed": what_changed,
                "reversal_watch": reversal_watch,
                "option_buyer_side": active_thesis.option_buyer_view if (active_thesis and active_thesis.option_buyer_view) else None,
                "premium_confirmation": active_thesis.premium_confirmation if (active_thesis and active_thesis.premium_confirmation) else None,
                "model_tension": "NO CHALLENGER READ: Solitary production cognitive analyst (gpt-5.6-luna)",
                "thesis_evolution": luna_out.get("thesis_evolution", "UNRESOLVED") if luna_out else "UNRESOLVED",
                "opportunity_maturity": luna_out.get("opportunity_maturity", "UNKNOWN") if luna_out else "UNKNOWN",
                "promotion_reason": luna_out.get("promotion_reason", "") if luna_out else "",
            }

            model_id = self.luna_adapter.model_name if self.luna_adapter else "gpt-5.6-luna"
            luna_status = luna_tel.get("status") if luna_tel else ("AWAITING_FIRST_ANALYSIS" if not active_thesis else "CURRENT")

            luna_entry = {
                "model_id": model_id,
                "provider": "experiential",
                "status": luna_status,
                "last_success": luna_tel.get("started_at"),
                "age_seconds": None,
                "analyzed_revision": packet.revision if packet else (active_thesis.input_revision if active_thesis else 0),
                "unseen_events": len(packet.unseen_event_ids) if packet and packet.unseen_event_ids else 0,
                "output": luna_out,
                "telemetry": luna_tel,
            }

            five_hypos = active_thesis.five_hypotheses if active_thesis and active_thesis.five_hypotheses else (luna_out.get("hypotheses", {}) if luna_out else {})

            return {
                "cycle": dict(self._last_cycle),
                "cognitive_live": {
                    "revision": packet.revision if packet else (active_thesis.input_revision if active_thesis else 0),
                    "market_timestamp": datetime.now(timezone.utc).isoformat(),
                    "primary_decision": primary_decision,
                    "luna": luna_entry,
                    "gpt": luna_entry,  # compatibility alias for frontend/projections
                    "qwen": {
                        "model_id": "qwen/qwen3.8-27b",
                        "provider": "groq",
                        "status": "NOT_INVOKED",
                        "output": None,
                    },
                    "gemini": {
                        "model_id": "gemini-3.8-flash",
                        "provider": "google",
                        "status": "NOT_INVOKED",
                        "output": None,
                    },
                    "five_hypotheses": five_hypos,
                    "option_continuity": packet.option_continuity if packet else {},
                    "quota": {
                        "experiential": {
                            "plan": "Experiential Promotional Free Tier",
                            "cost_micro_usd": luna_tel.get("cost_micro_usd", 0),
                            "cash_cost_usd": 0.000000,
                            "enforce_zero_cost": True,
                        }
                    },
                    "evidence_gate": {
                        "last_commit_id": self.last_committed_thesis.thesis_id if self.last_committed_thesis else None,
                        "last_commit_revision": self.last_committed_thesis.input_revision if self.last_committed_thesis else None,
                    },
                }
            }
        synth = self.last_synthesis
        active_thesis = self.thesis_graph.get_active_thesis()

        # Compute Model Tension
        qwen_state = self.last_qwen_obs.continuation_status if self.last_qwen_obs else "UNKNOWN"
        gpt_state = synth.current_state if synth else "AWAITING_FIRST_ANALYSIS"
        gemini_risk = self.last_gemini_rev.reversal_risk if self.last_gemini_rev else "UNKNOWN"

        if "REVERSAL" in qwen_state and "CONTINUATION" in (synth.setup_family if synth else ""):
            model_tension = "HIGH_TENSION: Qwen signals reversal while GPT maintains continuation"
        elif gemini_risk in ("ELEVATED", "HIGH"):
            model_tension = "MODERATE_TENSION: Gemini signals elevated reversal risk"
        elif gpt_state in ("AWAITING_FIRST_ANALYSIS", "UNAVAILABLE"):
            model_tension = "NEUTRAL: Awaiting live model synthesis"
        else:
            model_tension = "ALIGNED: Models in directional agreement"

        primary_decision = {
            "state": synth.current_state if synth else "AWAITING_FIRST_ANALYSIS",
            "entry_window": synth.entry_window if synth else "WAIT",
            "why_now": synth.why_now if synth else ["Awaiting live cognitive state"],
            "reversal_watch": synth.reversal_watch if synth else {"direction": "NONE"},
            "option_buyer_side": synth.option_buyer_side if synth else "UNRESOLVED",
            "premium_confirmation": synth.premium_confirmation if synth else "UNRESOLVED",
            "model_tension": model_tension,
        }

        freshness_data = {
            key: {
                "age_seconds": self.freshness_scheduler.freshness[key].age_seconds() if (self.freshness_scheduler and key in self.freshness_scheduler.freshness) else 999.0,
                "unseen_events_count": self.freshness_scheduler.freshness[key].unseen_events_count if (self.freshness_scheduler and key in self.freshness_scheduler.freshness) else 0,
            }
            for key in ("qwen", "gpt_oss", "gemini")
        }
        quota_data = self.quota_governor.get_provider_status_summary() if self.quota_governor else {}

        return {
            "cycle": dict(self._last_cycle),
            "cognitive_live": {
                "revision": packet.revision if packet else (synth.input_revision if synth else 0),
                "market_timestamp": datetime.now(timezone.utc).isoformat(),
                "primary_decision": primary_decision,
                "qwen": {
                    "model_id": self.qwen_sentinel.model_name,
                    "provider": "groq",
                    "status": self.last_qwen_obs.status if self.last_qwen_obs else "AWAITING_FIRST_ANALYSIS",
                    "last_success": self.last_qwen_obs.observed_at if (self.last_qwen_obs and self.last_qwen_obs.status == "CURRENT") else None,
                    "age_seconds": round(freshness_data.get("qwen", {}).get("age_seconds", 999.0), 1),
                    "analyzed_revision": self.last_qwen_obs.input_revision if self.last_qwen_obs else 0,
                    "unseen_events": freshness_data.get("qwen", {}).get("unseen_events_count", 0),
                    "output": self.last_qwen_obs.to_dict() if self.last_qwen_obs else None,
                },
                "gpt": {
                    "model_id": self.gpt_synthesizer.model_name,
                    "provider": "groq",
                    "status": synth.status if synth else "AWAITING_FIRST_ANALYSIS",
                    "last_success": synth.synthesized_at if (synth and synth.status == "CURRENT") else None,
                    "age_seconds": round(freshness_data.get("gpt_oss", {}).get("age_seconds", 999.0), 1),
                    "analyzed_revision": synth.input_revision if synth else 0,
                    "unseen_events": freshness_data.get("gpt_oss", {}).get("unseen_events_count", 0),
                    "output": synth.to_dict() if synth else None,
                },
                "gemini": {
                    "model_id": self.gemini_reviewer.model_name,
                    "provider": "google",
                    "status": self.last_gemini_rev.status if self.last_gemini_rev else "AWAITING_FIRST_ANALYSIS",
                    "last_success": self.last_gemini_rev.reviewed_at if (self.last_gemini_rev and self.last_gemini_rev.status == "CURRENT") else None,
                    "age_seconds": round(freshness_data.get("gemini", {}).get("age_seconds", 999.0), 1),
                    "analyzed_revision": self.last_gemini_rev.input_revision if self.last_gemini_rev else 0,
                    "unseen_events": freshness_data.get("gemini", {}).get("unseen_events_count", 0),
                    "output": self.last_gemini_rev.to_dict() if self.last_gemini_rev else None,
                },
                "five_hypotheses": synth.five_hypotheses if synth else {},
                "option_continuity": packet.option_continuity if packet else {},
                "quota": quota_data,
                "evidence_gate": {
                    "last_commit_id": self.last_committed_thesis.thesis_id if self.last_committed_thesis else None,
                    "last_commit_revision": self.last_committed_thesis.input_revision if self.last_committed_thesis else None,
                },
            }
        }
