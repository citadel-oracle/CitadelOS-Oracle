"""Bounded production bridge from durable Sol events to Cognitive Phase 1.

The producer-side contract is deliberately tiny: publish one immutable trigger
after a Sol event transaction commits, then return.  Packet compilation,
eligibility checks, provider calls, and thesis commits belong to the single
background worker and the existing Phase1CognitiveCoordinator.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from src.external_context.contracts import ExternalEvent, ExternalQuote
from src.oracle_sol.brain_packet_compiler import BrainPacket, BrainPacketCompiler
from src.oracle_sol.contracts import MarketEvent, SolEvidenceSnapshot, SystemStatus
from src.oracle_sol.phase1_coordinator import Phase1CognitiveCoordinator
from src.oracle_sol.thesis_graph import ThesisGraph


@dataclass(frozen=True)
class CognitiveEventTrigger:
    """Frozen ownership and evidence frontier captured at durable handoff."""

    session_id: str
    session_generation: int
    source_revision: int
    evidence_frontier: str
    source_event_count: int
    snapshot: SolEvidenceSnapshot
    offered_at_monotonic_ns: int

    @property
    def identity(self) -> str:
        return f"{self.session_id}:{self.session_generation}:{self.evidence_frontier}"


class CognitiveEventBridge:
    """One-worker, one-pending-trigger bridge with cumulative event coalescing."""

    def __init__(
        self,
        *,
        event_source: Callable[[], List[MarketEvent]],
        thesis_graph: ThesisGraph,
        coordinator: Phase1CognitiveCoordinator,
        compiler: Optional[BrainPacketCompiler] = None,
        external_events_source: Optional[Callable[[], Sequence[ExternalEvent]]] = None,
        external_quotes_source: Optional[Callable[[], Sequence[ExternalQuote]]] = None,
        status_path: Optional[str] = "data/oracle_sol/live_cognitive_status.json",
        worker_name: str = "citadel-cognitive-event-bridge",
    ) -> None:
        self.event_source = event_source
        self.thesis_graph = thesis_graph
        self.coordinator = coordinator
        self.compiler = compiler or BrainPacketCompiler()
        self.external_events_source = external_events_source or (lambda: ())
        self.external_quotes_source = external_quotes_source or (lambda: ())
        self.status_path = Path(status_path) if status_path else None
        self.worker_name = worker_name

        self._condition = threading.Condition(threading.RLock())
        self._stop = False
        self._accepting = False
        self._thread: Optional[threading.Thread] = None
        self._pending: Optional[CognitiveEventTrigger] = None
        self._in_flight: Optional[CognitiveEventTrigger] = None
        self._active_session_id: Optional[str] = None
        self._active_session_generation: int = -1
        self._last_accepted_identity: Optional[str] = None
        self._last_packet: Optional[BrainPacket] = None
        self._last_failure_reason: Optional[str] = None
        self._bridge_state = "STOPPED"
        self._market_state = "UNAVAILABLE"

        self._offers_received = 0
        self._accepted_offers = 0
        self._coalesced_triggers = 0
        self._duplicate_triggers_suppressed = 0
        self._mailbox_full_events = 0
        self._cycles_started = 0
        self._cycles_completed = 0
        self._cycles_failed = 0
        self._stale_session_triggers_rejected = 0
        self._stale_source_triggers_rejected = 0
        self._stale_results_not_promoted = 0
        self._market_closed_rejections = 0
        self._already_committed_triggers_skipped = 0
        self._last_seen_source_revision: Optional[int] = None
        self._last_seen_evidence_frontier: Optional[str] = None
        self._last_eligible_trigger: Optional[str] = None
        self._last_started_trigger: Optional[str] = None
        self._last_completed_trigger: Optional[str] = None
        self._last_cycle_latency_ms: Optional[float] = None
        self._offer_latencies_ms: List[float] = []

    def start(self, session_id: str, session_generation: int) -> bool:
        """Start exactly one worker and establish current session ownership."""
        with self._condition:
            self._roll_session_locked(session_id, session_generation)
            if self._thread and self._thread.is_alive():
                self._accepting = True
                return False
            self._stop = False
            self._accepting = True
            self._bridge_state = "RUNNING"
            self._thread = threading.Thread(
                target=self._run,
                name=self.worker_name,
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self, timeout: float = 5.0) -> None:
        """Stop accepting triggers and join the sole bridge worker."""
        with self._condition:
            self._accepting = False
            self._stop = True
            self._pending = None
            self._condition.notify_all()
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=max(0.0, timeout))
        with self._condition:
            self._bridge_state = "STOPPED" if not (thread and thread.is_alive()) else "STOPPING"

    def rotate_session(self, session_id: str, session_generation: int) -> None:
        """Atomically invalidate old trigger ownership without deleting history."""
        with self._condition:
            self._roll_session_locked(session_id, session_generation)
            self._condition.notify_all()

    def _roll_session_locked(self, session_id: str, session_generation: int) -> None:
        if (
            self._active_session_id == session_id
            and self._active_session_generation == session_generation
        ):
            return
        if hasattr(self.coordinator, "rollover_session"):
            self.coordinator.rollover_session(session_id)
        else:
            active = self.thesis_graph.get_active_thesis()
            if active is None or active.session_id != session_id:
                self.thesis_graph.rollover_session(session_id)
        self._active_session_id = session_id
        self._active_session_generation = session_generation
        self._pending = None
        self._last_accepted_identity = None
        self._last_packet = None
        self._last_failure_reason = None
        self._last_seen_source_revision = None
        self._last_seen_evidence_frontier = None

    def observe_market_state(
        self,
        snapshot: SolEvidenceSnapshot,
        session_id: str,
        session_generation: int,
    ) -> None:
        """Update operational truth even when no thesis-relevant event was emitted."""
        with self._condition:
            if (
                session_id != self._active_session_id
                or session_generation != self._active_session_generation
            ):
                self._roll_session_locked(session_id, session_generation)
            status = snapshot.system_status.value if hasattr(snapshot.system_status, "value") else str(snapshot.system_status)
            self._market_state = status
            self._bridge_state = "RUNNING_OFF_MARKET" if status == SystemStatus.OFF_MARKET.value else "RUNNING"

    def offer(self, trigger: CognitiveEventTrigger) -> bool:
        """Non-blocking one-slot offer; never waits for inference or a full queue."""
        started_ns = time.perf_counter_ns()
        with self._condition:
            self._offers_received += 1

            if not self._accepting or self._stop:
                self._last_failure_reason = "BRIDGE_NOT_ACCEPTING"
                return False
            if (
                trigger.session_id != self._active_session_id
                or trigger.session_generation != self._active_session_generation
            ):
                self._stale_session_triggers_rejected += 1
                self._last_failure_reason = "STALE_SESSION_TRIGGER"
                return False
            status = trigger.snapshot.system_status.value if hasattr(trigger.snapshot.system_status, "value") else str(trigger.snapshot.system_status)
            self._market_state = status
            if status != SystemStatus.HEALTHY.value:
                if status == SystemStatus.OFF_MARKET.value:
                    self._market_closed_rejections += 1
                    self._bridge_state = "RUNNING_OFF_MARKET"
                    self._last_failure_reason = "OFF_MARKET"
                else:
                    self._bridge_state = "RUNNING_NOT_ELIGIBLE"
                    self._last_failure_reason = f"SYSTEM_STATUS_{status}"
                return False

            if self._last_seen_source_revision is not None:
                source_moved_back = trigger.source_revision < self._last_seen_source_revision
                same_revision_conflict = (
                    trigger.source_revision == self._last_seen_source_revision
                    and trigger.evidence_frontier != self._last_seen_evidence_frontier
                )
                if source_moved_back or same_revision_conflict:
                    self._stale_source_triggers_rejected += 1
                    self._last_failure_reason = "NON_MONOTONIC_SOURCE_TRIGGER"
                    return False

            if trigger.identity in {
                self._last_accepted_identity,
                self._pending.identity if self._pending else None,
                self._in_flight.identity if self._in_flight else None,
            }:
                self._duplicate_triggers_suppressed += 1
                return False


            if not self.thesis_graph.set_acceptance_frontier(
                trigger.session_id,
                trigger.evidence_frontier,
            ):
                self._stale_session_triggers_rejected += 1
                self._last_failure_reason = "STALE_SESSION_TRIGGER"
                return False
            self._last_seen_source_revision = trigger.source_revision
            self._last_seen_evidence_frontier = trigger.evidence_frontier

            if self._pending is not None:
                # Safe only because _events_for_trigger reconstructs the complete
                # accepted-cursor -> latest-frontier event interval.
                self._coalesced_triggers += 1
                self._mailbox_full_events += 1
            self._pending = trigger
            self._accepted_offers += 1
            self._last_accepted_identity = trigger.identity
            self._last_eligible_trigger = trigger.identity
            self._bridge_state = "RUNNING"
            self._condition.notify()
            self._offer_latencies_ms.append((time.perf_counter_ns() - started_ns) / 1_000_000.0)
            if len(self._offer_latencies_ms) > 2048:
                del self._offer_latencies_ms[:-1024]
            return True

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._stop and self._pending is None:
                    self._condition.wait(timeout=1.0)
                if self._stop:
                    return
                trigger = self._pending
                self._pending = None
                self._in_flight = trigger
                self._cycles_started += 1
                self._last_started_trigger = trigger.identity if trigger else None
            if trigger is None:
                continue

            started = time.perf_counter()
            try:
                packet = self._build_packet(trigger)
                if packet is None:
                    with self._condition:
                        self._already_committed_triggers_skipped += 1
                        self._cycles_completed += 1
                        self._last_completed_trigger = trigger.identity
                    continue
                self._last_packet = packet
                # Specialists start independently; Luna never waits for their futures.
                try:
                    from dataclasses import replace
                    from src.oracle_sol.privacy_sanitizer import sanitize_brain_packet
                    from src.oracle_sol.shadow_runtime import LiveShadowOrchestrator
                    shadows = LiveShadowOrchestrator.get_instance()
                    context = []
                    cutoff = sanitize_brain_packet(packet)["decision_cutoff_ist"]
                    for view in shadows.get_projected_views().values():
                        if view.get("session_date") == packet.session_id and view.get("status") == "CURRENT" and isinstance(view.get("decision_cutoff"), str) and view["decision_cutoff"] <= cutoff and view.get("headline"):
                            context.append({"kind": "PRIOR_SPECIALIST_ASSERTION_NOT_CANONICAL_FACT", **{key: view.get(key) for key in ("model_id", "receipt_id", "revision", "session_date", "decision_cutoff", "headline", "bullets", "missing_evidence", "packet_hash")}})
                    shadows.process_live_packet(packet, recent_events=self._events_for_trigger(trigger))
                    candidate = replace(packet, specialist_context=context)
                    sanitize_brain_packet(candidate)
                    packet = candidate
                    self._last_packet = packet
                except Exception as shadow_exc:
                    logger.warning("Specialist dispatch isolated from Luna: %s", shadow_exc)
                payload = self.coordinator.execute_cycle(
                    packet,
                    acceptance_guard=lambda _packet: self._trigger_is_current(trigger),
                )
                cycle = payload.get("cycle") if isinstance(payload, dict) else {}
                stale = bool(isinstance(cycle, dict) and cycle.get("status") == "STALE_RESULT_NOT_PROMOTED")
                if stale or not self._trigger_is_current(trigger):
                    with self._condition:
                        self._stale_results_not_promoted += 1
                        self._bridge_state = "RUNNING_NEW_EVIDENCE_PENDING"
                if not stale and self._trigger_is_current(trigger):
                    self._persist_safe_status(packet, payload)
                with self._condition:
                    self._cycles_completed += 1
                    self._last_completed_trigger = trigger.identity
                    if self._bridge_state not in {"RUNNING_NEW_EVIDENCE_PENDING", "RUNNING_OFF_MARKET"}:
                        self._bridge_state = "RUNNING"
                    self._last_failure_reason = None
            except Exception as exc:
                with self._condition:
                    self._cycles_failed += 1
                    self._last_failure_reason = f"{type(exc).__name__}:{exc}"
                    self._bridge_state = "DEGRADED"
            finally:
                with self._condition:
                    self._last_cycle_latency_ms = (time.perf_counter() - started) * 1000.0
                    self._in_flight = None
                    self._condition.notify_all()

    def _events_for_trigger(self, trigger: CognitiveEventTrigger) -> List[MarketEvent]:
        events = [event for event in self.event_source() if event.session_date == trigger.session_id]
        frontier_index = next(
            (index for index, event in enumerate(events) if event.event_id == trigger.evidence_frontier),
            -1,
        )
        if frontier_index < 0:
            raise ValueError("EVIDENCE_FRONTIER_NOT_FOUND")
        cursor = self.thesis_graph.get_cursor()
        cursor_index = -1
        if cursor:
            cursor_index = next(
                (index for index, event in enumerate(events[: frontier_index + 1]) if event.event_id == cursor),
                -1,
            )
        return events[cursor_index + 1 : frontier_index + 1]

    @staticmethod
    def _parse_time(value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None

    def _context_at_trigger(
        self,
        trigger: CognitiveEventTrigger,
    ) -> tuple[List[ExternalEvent], List[ExternalQuote]]:
        cutoff = self._parse_time(trigger.snapshot.timestamp_utc)
        if cutoff is None:
            return [], []
        events = [
            item
            for item in self.external_events_source()
            if (self._parse_time(getattr(item, "retrieved_at", None)) or datetime.max.replace(tzinfo=timezone.utc)) <= cutoff
        ]
        quotes = [
            item
            for item in self.external_quotes_source()
            if (self._parse_time(getattr(item, "retrieved_at", None)) or datetime.max.replace(tzinfo=timezone.utc)) <= cutoff
        ]
        return events, quotes

    def _build_packet(self, trigger: CognitiveEventTrigger) -> Optional[BrainPacket]:
        events = self._events_for_trigger(trigger)
        if not events:
            return None
        active = self.thesis_graph.get_active_thesis()
        previous = active.to_dict() if active and active.session_id == trigger.session_id else None
        external_events, external_quotes = self._context_at_trigger(trigger)
        return self.compiler.compile_packet(
            session_id=trigger.session_id,
            revision=trigger.source_revision,
            current_snapshot=trigger.snapshot,
            previous_thesis=previous,
            unseen_events=events,
            external_events=external_events,
            external_quotes=external_quotes,
        )

    def _trigger_is_current(self, trigger: CognitiveEventTrigger) -> bool:
        with self._condition:
            return bool(
                trigger.session_id == self._active_session_id
                and trigger.session_generation == self._active_session_generation
                and trigger.evidence_frontier == self._last_seen_evidence_frontier
            )

    def wait_until_idle(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while self._pending is not None or self._in_flight is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
            return True

    def _persist_safe_status(self, packet: BrainPacket, payload: Dict[str, Any]) -> None:
        if self.status_path is None:
            return
        cognitive = payload.get("cognitive_live", {}) if isinstance(payload, dict) else {}
        cycle = payload.get("cycle", {}) if isinstance(payload, dict) else {}
        models: Dict[str, Any] = {}
        for source_key, target_key in (("qwen", "qwen"), ("gpt", "gpt_oss"), ("gemini", "gemini"), ("luna", "luna")):
            raw = cognitive.get(source_key) if isinstance(cognitive, dict) else None
            raw = raw if isinstance(raw, dict) else {}
            output = raw.get("output") if isinstance(raw.get("output"), dict) else {}
            telemetry = output.get("telemetry") if isinstance(output, dict) else {}
            telemetry = telemetry if isinstance(telemetry, dict) else {}
            model_status = raw.get("status")
            cycle_status = cycle.get("status", "COMPLETED")
            if cycle_status == "REJECTED" and target_key in ("gpt_oss", "luna"):
                model_status = "OUTPUT_INVALID"
            models[target_key] = {
                "model_id": raw.get("model_id"),
                "status": model_status,
                "input_revision": raw.get("analyzed_revision"),
                "completed_at": raw.get("last_success"),
                "http_status": telemetry.get("http_status"),
                "error_category": telemetry.get("error_category"),
                "latency_ms": telemetry.get("latency_ms"),
                "prompt_tokens": telemetry.get("prompt_tokens", 0),
                "completion_tokens": telemetry.get("completion_tokens", 0),
                "total_tokens": telemetry.get("total_tokens", 0),
            }
        document = {
            "status": cycle.get("status", "COMPLETED"),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "session_id": packet.session_id,
            "input_revision": packet.revision,
            "input_hash": packet.packet_hash,
            "decision": {
                "model_tension": (cognitive.get("primary_decision") or {}).get("model_tension")
                if isinstance(cognitive, dict)
                else None,
                "agreement_status": "UNAVAILABLE",
            },
            "models": models,
            "bridge": self.get_telemetry(),
        }
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.status_path.with_suffix(self.status_path.suffix + ".tmp")
        with open(temp_path, "w", encoding="utf-8") as stream:
            json.dump(document, stream, sort_keys=True, separators=(",", ":"), default=str)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, self.status_path)

    def get_last_packet(self) -> Optional[BrainPacket]:
        with self._condition:
            return self._last_packet

    def get_telemetry(self) -> Dict[str, Any]:
        with self._condition:
            samples = sorted(self._offer_latencies_ms)

            def percentile(fraction: float) -> Optional[float]:
                if not samples:
                    return None
                index = min(len(samples) - 1, int((len(samples) - 1) * fraction))
                return round(samples[index], 4)

            return {
                "bridge_state": self._bridge_state,
                "owner_process_id": os.getpid(),
                "owner_thread": self.worker_name,
                "worker_alive": bool(self._thread and self._thread.is_alive()),
                "current_session_id": self._active_session_id,
                "session_generation": self._active_session_generation,
                "market_state": self._market_state,
                "last_seen_source_revision": self._last_seen_source_revision,
                "last_seen_evidence_frontier": self._last_seen_evidence_frontier,
                "last_eligible_trigger": self._last_eligible_trigger,
                "last_started_trigger": self._last_started_trigger,
                "last_completed_trigger": self._last_completed_trigger,
                "cycle_in_flight": self._in_flight is not None,
                "pending_trigger_present": self._pending is not None,
                "pending_depth": 1 if self._pending is not None else 0,
                "maximum_pending_depth": 1,
                "offers_received": self._offers_received,
                "accepted_offers": self._accepted_offers,
                "cycles_started": self._cycles_started,
                "cycles_completed": self._cycles_completed,
                "cycles_failed": self._cycles_failed,
                "duplicate_triggers_suppressed": self._duplicate_triggers_suppressed,
                "coalesced_triggers": self._coalesced_triggers,
                "stale_session_triggers_rejected": self._stale_session_triggers_rejected,
                "stale_source_triggers_rejected": self._stale_source_triggers_rejected,
                "stale_results_not_promoted": self._stale_results_not_promoted,
                "mailbox_full_events": self._mailbox_full_events,
                "market_closed_rejections": self._market_closed_rejections,
                "already_committed_triggers_skipped": self._already_committed_triggers_skipped,
                "last_cycle_latency_ms": round(self._last_cycle_latency_ms, 3)
                if self._last_cycle_latency_ms is not None
                else None,
                "last_failure_reason": self._last_failure_reason,
                "offer_latency_ms": {
                    "samples": len(samples),
                    "p50": percentile(0.50),
                    "p95": percentile(0.95),
                    "max": round(samples[-1], 4) if samples else None,
                },
                "cumulative_evidence_coalescing": "CURSOR_TO_LATEST_FRONTIER",
                "paper_only": True,
                "live_trading": False,
                "broker_submission": False,
                "execution_influence": 0,
                "ai_vob_influence": 0,
            }
