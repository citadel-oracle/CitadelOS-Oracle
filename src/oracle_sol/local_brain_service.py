from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.external_context.core import ExternalContextCore
from src.oracle_sol.brain_packet_compiler import BrainPacket, BrainPacketCompiler
from src.oracle_sol.brain_provider_adapter import BrainProviderAdapter
from src.oracle_sol.cognitive_status import (
    record_model_execution,
    set_model_in_flight,
    set_model_shadow_enabled,
)
from src.oracle_sol.contracts import MarketEvent, SolEvidenceSnapshot
from src.oracle_sol.episode_memory import MarketEpisodeMemory
from src.oracle_sol.evidence_gate import EvidenceGate, GateValidationResult
from src.oracle_sol.groq_adapter import GroqBrainAdapter
from src.oracle_sol.local_model_adapter import LocalModelAdapter, OllamaQwenAdapter
from src.oracle_sol.resource_governor import ResourceGovernor
from src.oracle_sol.thesis_graph import (
    COGNITIVE_SHADOW_SYSTEM_PROMPT,
    COGNITIVE_STRUCTURED_OUTPUT_SCHEMA,
    ThesisGraph,
    ThesisNode,
)

logger = logging.getLogger(__name__)

ADVERSARIAL_REVIEW_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "current_gpt_thesis": {"type": "string"},
        "strongest_evidence_against_it": {"type": "string"},
        "missed_reversal_evidence": {"type": "string"},
        "misinterpreted_oi": {"type": "string"},
        "option_premium_contradiction": {"type": "string"},
        "cited_evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "current_gpt_thesis",
        "strongest_evidence_against_it",
        "missed_reversal_evidence",
        "misinterpreted_oi",
        "option_premium_contradiction",
        "cited_evidence_ids",
    ],
}


class LocalBrainService:
    """Central coordinator for Citadel Cloud Cognitive Shadow (GPT-OSS Primary + Qwen Challenger)."""

    _instance: Optional[LocalBrainService] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> LocalBrainService:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(
        self,
        adapter: Optional[BrainProviderAdapter] = None,
        challenger_adapter: Optional[BrainProviderAdapter] = None,
        compiler: Optional[BrainPacketCompiler] = None,
        thesis_graph: Optional[ThesisGraph] = None,
        governor: Optional[ResourceGovernor] = None,
        external_context: Optional[ExternalContextCore] = None,
        episode_memory: Optional[MarketEpisodeMemory] = None,
    ) -> None:
        # Default primary: Groq GPT-OSS 120B (fallback to Ollama if explicitly requested)
        if adapter is not None:
            self.adapter = adapter
        else:
            groq = GroqBrainAdapter(model_name="openai/gpt-oss-120b")
            self.adapter = groq if groq.is_configured else OllamaQwenAdapter()

        # Default challenger: Groq Qwen 3.8 27B preview
        self.challenger_adapter = challenger_adapter or GroqBrainAdapter(model_name="qwen/qwen3.8-27b")
        self.compiler = compiler or BrainPacketCompiler()
        self.thesis_graph = thesis_graph or ThesisGraph(storage_path="data/oracle_sol/thesis_graph.jsonl")
        self.evidence_gate = EvidenceGate(thesis_graph=self.thesis_graph)
        self.governor = governor or ResourceGovernor()
        self.external_context = external_context or ExternalContextCore.get_instance()
        self.episode_memory = episode_memory or MarketEpisodeMemory()

        self._eval_lock = threading.Lock()
        self._session_lock = threading.RLock()
        self._last_telemetry: Dict[str, Any] = {}
        self._last_packet: Optional[BrainPacket] = None
        self._last_gate_result: Optional[GateValidationResult] = None
        self._coalesced_drops: int = 0
        self._pending_unseen_events: List[MarketEvent] = []
        restored_thesis = self.thesis_graph.get_active_thesis()
        self._current_session_id: Optional[str] = (
            restored_thesis.session_id if restored_thesis else self.episode_memory.session_id
        )
        self.shadow_status: str = "SHADOW_INITIALIZED"

    def _ensure_session(self, session_id: str) -> None:
        """Clear active cognitive state before compiling a packet for a new session."""
        with self._session_lock:
            if self._current_session_id == session_id:
                return
            self.thesis_graph.rollover_session(session_id)
            self._pending_unseen_events = [
                event for event in self._pending_unseen_events
                if event.session_date == session_id
            ]
            self._last_packet = None
            self._last_gate_result = None
            self._last_telemetry = {}
            self._current_session_id = session_id
            self.shadow_status = "SHADOW_AWAITING_SESSION"

    def is_cloud_provider(self) -> bool:
        """Return True if active adapter is cloud-based (Groq)."""
        prov = getattr(self.adapter, "provider", "").lower()
        return "groq" in prov or isinstance(self.adapter, GroqBrainAdapter)

    def on_canonical_event(
        self,
        event: MarketEvent,
        current_snapshot: SolEvidenceSnapshot,
        session_id: str,
        revision: int,
    ) -> Tuple[Optional[ThesisNode], Dict[str, Any]]:
        """Event-driven entry point: coalesces rapid events and triggers non-blocking inference."""
        if not event:
            return None, {"status": "EMPTY_EVENT_SKIPPED"}

        with self._session_lock:
            self._ensure_session(session_id)
            self._pending_unseen_events.append(event)
            unseen_to_process = list(self._pending_unseen_events)

        # Run cycle (if busy, drops gracefully with coalescing)
        thesis, tel = self.run_cycle(
            session_id=session_id,
            revision=revision,
            current_snapshot=current_snapshot,
            unseen_events=unseen_to_process,
        )

        # If inference was accepted, clear processed events
        if thesis is not None:
            self._pending_unseen_events.clear()

        return thesis, tel

    def run_cycle(
        self,
        session_id: str,
        revision: int,
        current_snapshot: SolEvidenceSnapshot,
        unseen_events: List[MarketEvent],
    ) -> Tuple[Optional[ThesisNode], Dict[str, Any]]:
        """Executes a single coalesced reasoning cycle."""
        # Non-blocking coalescing: if evaluation is in flight, drop and coalesce
        acquired = self._eval_lock.acquire(blocking=False)
        if not acquired:
            self._coalesced_drops += 1
            logger.info("CognitiveShadow: Cycle dropped due to active inference (coalesced: %d)", self._coalesced_drops)
            return None, {
                "status": "COALESCED_DROP",
                "coalesced_drops": self._coalesced_drops,
            }

        # Signal in-flight telemetry
        set_model_in_flight("gpt_oss", True)

        try:
            self._ensure_session(session_id)
            # 1. Resource Governor Check (Cloud Groq incurs 0 host memory pressure)
            if not self.is_cloud_provider():
                permitted, reason = self.governor.should_permit_inference()
                if not permitted:
                    logger.warning("CognitiveShadow: Local inference prevented by Governor: %s", reason)
                    self.governor.enforce_shedding(self.adapter)
                    self.shadow_status = "LOCAL_MODEL_SHED"
                    return None, {
                        "status": "BLOCKED_BY_RESOURCE_GOVERNOR",
                        "reason": reason,
                    }

            # 2. Gather Context & Episode Memory
            active_thesis = self.thesis_graph.get_active_thesis()
            prev_thesis_dict = active_thesis.to_dict() if active_thesis else None
            active_state = active_thesis.state if active_thesis else "NO_TRADE"
            episode = self.episode_memory.get_or_create_episode(
                session_id=session_id,
                current_state=active_state,
                current_cursor=self.thesis_graph.get_cursor(),
            )
            if unseen_events:
                self.episode_memory.record_events(unseen_events)

            # Retrieve verified external events and latest quotes
            ext_events = self.external_context.get_latest_events(limit=5)
            ext_quotes = self.external_context.get_latest_quotes()

            # 3. Compile Deterministic BrainPacket (Cognitive V2)
            packet = self.compiler.compile_packet(
                session_id=session_id,
                revision=revision,
                current_snapshot=current_snapshot,
                previous_thesis=prev_thesis_dict,
                unseen_events=unseen_events,
                external_events=ext_events,
                external_quotes=ext_quotes,
                episode_id=episode.episode_id,
            )
            self._last_packet = packet

            # 4. Invoke Shadow Primary Model (GPT Request Economy: compact prompt)
            user_prompt = (
                f"BrainPacket Input:\n{json.dumps(packet.to_dict(), default=str, separators=(',', ':'))}\n\n"
                f"Analyze the market evidence and respond strictly with the 14-section JSON structure defined in the system instructions."
            )
            model_id = getattr(self.adapter, "configured_model", "openai/gpt-oss-120b")
            raw_response, telemetry = self.adapter.invoke_reasoning(
                request_id=packet.packet_id,
                system_prompt=COGNITIVE_SHADOW_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                schema=COGNITIVE_STRUCTURED_OUTPUT_SCHEMA,
            )
            self._last_telemetry = telemetry

            # Provider failure handling: do NOT synthesize NO_TRADE; cursor unchanged; episode memory keeps accumulating
            if not raw_response or telemetry.get("error"):
                logger.warning("CognitiveShadow: Model invocation failed (%s). Cursor remains unchanged.", telemetry.get("error"))
                self.shadow_status = f"PROVIDER_ERROR_{telemetry.get('schema_status', 'FAILED')}"
                return None, {
                    "status": "PROVIDER_FAILURE",
                    "error": telemetry.get("error"),
                    "telemetry": telemetry,
                }

            # 5. Evidence Gate Validation & Commit
            gate_result = self.evidence_gate.validate_and_commit(
                raw_response=raw_response,
                packet=packet,
                model_name=model_id,
                system_prompt=COGNITIVE_SHADOW_SYSTEM_PROMPT,
            )
            self._last_gate_result = gate_result

            if gate_result.is_valid and gate_result.committed_thesis:
                self.shadow_status = "SHADOW_ACTIVE"
                # Advance episode memory with accepted thesis
                self.episode_memory.record_thesis_commit(
                    thesis_id=gate_result.committed_thesis.thesis_id,
                    new_state=gate_result.committed_thesis.state,
                    cursor=gate_result.committed_thesis.event_cursor_after or "",
                )
                # Update dynamic telemetry
                record_model_execution("gpt_oss", {
                    "last_success_at": datetime.now(timezone.utc).isoformat(),
                    "last_http_status": 200,
                    "last_latency_ms": telemetry.get("total_duration_ms", 0),
                    "last_prompt_tokens": telemetry.get("prompt_tokens", 0),
                    "last_completion_tokens": telemetry.get("completion_tokens", 0),
                    "last_total_tokens": telemetry.get("total_tokens", 0),
                    "last_schema_status": "SCHEMA_VALID_JSON",
                    "last_evidence_gate_status": "COMMITTED",
                    "last_thesis_state": gate_result.committed_thesis.state,
                })
                return gate_result.committed_thesis, telemetry
            else:
                self.shadow_status = f"SHADOW_REJECTED_{gate_result.status}"
                return None, {
                    "status": gate_result.status,
                    "error_details": gate_result.error_details,
                    "unsupported_evidence_ids": gate_result.unsupported_evidence_ids,
                    "telemetry": telemetry,
                }

        finally:
            set_model_in_flight("gpt_oss", False)
            self._eval_lock.release()

    def invoke_adversarial_review(
        self,
        current_thesis: ThesisNode,
        packet: BrainPacket,
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """Adversarial Reviewer Hook: Qwen 3.8 27B independently attacks the GPT primary thesis."""
        if not self.challenger_adapter.is_available():
            return None, {"status": "CHALLENGER_KEY_UNAVAILABLE"}

        adversarial_system_prompt = (
            "You are the CITADEL ADVERSARIAL REVIEWER running Qwen 3.8 27B in PREVIEW mode.\n"
            "Your explicit mission: Find the strongest evidence-supported case that the current GPT thesis is wrong.\n"
            "Ground EVERY counter-argument in valid evidence IDs. Zero execution authority."
        )
        user_prompt = (
            f"PRIMARY THESIS TO ATTACK:\n{json.dumps(current_thesis.to_dict(), default=str)}\n\n"
            f"CANONICAL EVIDENCE PACKET:\n{json.dumps(packet.to_dict(), default=str)}"
        )

        set_model_in_flight("qwen", True)
        try:
            raw_response, telemetry = self.challenger_adapter.invoke_reasoning(
                request_id=f"adv_{packet.packet_id}",
                system_prompt=adversarial_system_prompt,
                user_prompt=user_prompt,
                schema=ADVERSARIAL_REVIEW_SCHEMA,
            )
            if raw_response and not telemetry.get("error"):
                record_model_execution("qwen", {
                    "last_success_at": datetime.now(timezone.utc).isoformat(),
                    "last_http_status": 200,
                    "last_latency_ms": telemetry.get("total_duration_ms", 0),
                    "last_prompt_tokens": telemetry.get("prompt_tokens", 0),
                    "last_completion_tokens": telemetry.get("completion_tokens", 0),
                    "last_total_tokens": telemetry.get("total_tokens", 0),
                    "last_schema_status": "SCHEMA_VALID_JSON",
                    "last_evidence_gate_status": "ADVERSARIAL_REVIEW_COMPLETED",
                })
            return raw_response, telemetry
        finally:
            set_model_in_flight("qwen", False)

    def get_shadow_state(self) -> Dict[str, Any]:
        """Returns the public state for dashboard presentation."""
        active_thesis = self.thesis_graph.get_active_thesis()
        latest_ext = self.external_context.get_latest_events(limit=5)
        quotes = self.external_context.get_latest_quotes()

        return {
            "mode": "SHADOW",
            "provider": "GROQ",
            "primary_model": "openai/gpt-oss-120b",
            "challenger_model": "qwen/qwen3.8-27b",
            "shadow_status": self.shadow_status,
            "active_thesis": active_thesis.to_dict() if active_thesis else None,
            "last_telemetry": self._last_telemetry,
            "last_gate_status": self._last_gate_result.status if self._last_gate_result else "INITIAL",
            "coalesced_drops": self._coalesced_drops,
            "external_events_count": len(latest_ext),
            "external_quotes_count": len(quotes),
            "historical_analogs": "NOT_IMPLEMENTED",
        }

    def get_last_packet(self) -> Optional[BrainPacket]:
        return self._last_packet

    def get_last_gate_result(self) -> Optional[GateValidationResult]:
        return self._last_gate_result

    def get_last_telemetry(self) -> Optional[Dict[str, Any]]:
        return self._last_telemetry
