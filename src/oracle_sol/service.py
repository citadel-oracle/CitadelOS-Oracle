"""Central Service Integration for CITADEL MARKET BRAIN (Gemini 3.7 Flash & Sol).

Connects the verified canonical sensorium, Durable Session Event Store,
reasoning orchestrators, Shadow Ledger, and Beacon SSE broadcasting with
unified market session identity, truth firewall fail-closed invalidation, and baseline recovery.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple
from zoneinfo import ZoneInfo

from src.oracle_sol.contracts import (
    DevelopingState,
    ReasoningStatus,
    SolBeaconOutput,
    SolEvidenceSnapshot,
    SolModelRequestEnvelope,
    SystemStatus,
    ThesisState,
    resolve_canonical_market_state,
)
from src.oracle_sol.event_sourced_memory import EventSourcedMarketMemory
from src.oracle_sol.event_story_builder import MarketEventStoryBuilder
from src.oracle_sol.external_context import (
    ExternalContextPayload,
    ExternalContextStore,
    validate_external_context_payload,
)
from src.oracle_sol.gemini_adapter import safe_provider_error_telemetry
from src.oracle_sol.provider_factory import get_reasoning_adapter
from src.oracle_sol.provenance_guard import (
    ProvenanceGuard,
    UnverifiedLineageError,
    VobContaminationError,
)
from src.oracle_sol.reasoning_protocol import SolReasoningOrchestrator
from src.oracle_sol.replay import SolCycleReplayEngine
from src.oracle_sol.shadow_ledger import SolShadowLedger
from src.oracle_sol.thesis_memory import ThesisMemory
from src.oracle_sol.worker import SolMarketBrainWorker, SolReasoningJob

IST = ZoneInfo("Asia/Kolkata")


def _coverage_status(values: List[Any]) -> str:
    """Describe structural evidence coverage without deriving market meaning."""
    if not values:
        return "UNAVAILABLE"
    present = sum(value is not None for value in values)
    if present == 0:
        return "UNAVAILABLE"
    if present == len(values):
        return "AVAILABLE"
    return "PARTIAL"


def _matrix_domain_status(
    snapshot: Optional[SolEvidenceSnapshot], fields: List[str]
) -> Dict[str, Any]:
    if snapshot is None:
        return {"status": "UNAVAILABLE", "fields": {field: "UNAVAILABLE" for field in fields}}
    field_status = {
        field: str(snapshot.availability_matrix.get(field, "UNAVAILABLE"))
        for field in fields
    }
    available_values = {"AVAILABLE", "OBSERVED_ZERO"}
    available_count = sum(value in available_values for value in field_status.values())
    status = (
        "AVAILABLE"
        if available_count == len(field_status)
        else "PARTIAL"
        if available_count > 0
        else "UNAVAILABLE"
    )
    return {"status": status, "fields": field_status}


def _options_oi_reading_status(snapshot: Optional[SolEvidenceSnapshot]) -> Dict[str, str]:
    """Expose backend-owned OPTIONS/OI availability exactly as sent to reasoning."""
    if snapshot is None:
        return {
            "status": "UNAVAILABLE",
            "option_quotes": "UNAVAILABLE",
            "closed_5m_oi": "UNAVAILABLE",
            "closed_15m_oi": "UNAVAILABLE",
            "total_oi": "UNAVAILABLE",
            "pcr_oi": "UNAVAILABLE",
            "sudden_oi": "UNAVAILABLE",
        }

    ladder = [row for row in snapshot.strike_ladder if isinstance(row, Mapping)]
    closed_5m_values: List[Any] = []
    closed_15m_values: List[Any] = []
    for row in ladder:
        for side in ("ce", "pe"):
            if row.get(f"{side}_security_id") is not None:
                closed_5m_values.append(row.get(f"{side}_closed_5m_oi"))
                closed_15m_values.append(row.get(f"{side}_closed_15m_oi"))

    quote_status = _coverage_status([snapshot.ce_pricing, snapshot.pe_pricing])
    sudden_status = _coverage_status([snapshot.sudden_oi_call, snapshot.sudden_oi_put])
    closed_5m_status = _coverage_status(closed_5m_values)
    closed_15m_status = _coverage_status(closed_15m_values)
    components = [
        quote_status,
        sudden_status,
        closed_5m_status,
        closed_15m_status,
        "UNAVAILABLE",  # total OI is not in the current Sol snapshot contract
        "UNAVAILABLE",  # PCR OI is not in the current Sol snapshot contract
    ]
    status = (
        "AVAILABLE"
        if all(component == "AVAILABLE" for component in components)
        else "PARTIAL"
        if any(component != "UNAVAILABLE" for component in components)
        else "UNAVAILABLE"
    )
    return {
        "status": status,
        "option_quotes": quote_status,
        "closed_5m_oi": closed_5m_status,
        "closed_15m_oi": closed_15m_status,
        "total_oi": "UNAVAILABLE",
        "pcr_oi": "UNAVAILABLE",
        "sudden_oi": sudden_status,
    }


class SolMarketBrainService:
    """The central runtime service for Sol Market Brain."""

    _instance: Optional[SolMarketBrainService] = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> SolMarketBrainService:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(runtime_mode="LIVE")
            return cls._instance

    @classmethod
    def shutdown_if_initialized(cls) -> None:
        """Stop background workers without constructing a service during shutdown."""
        with cls._instance_lock:
            instance = cls._instance
        if instance is not None:
            instance.stop()

    def __init__(
        self,
        storage_dir: Optional[str] = None,
        model_adapter: Optional[Any] = None,
        runtime_mode: Optional[str] = None,
        cognitive_bridge_enabled: Optional[bool] = None,
    ) -> None:
        if runtime_mode is None:
            raise ValueError("runtime_mode must be explicitly set to LIVE, REPLAY, or TEST")
        normalized_runtime_mode = str(runtime_mode).strip().upper()
        if normalized_runtime_mode not in {"LIVE", "REPLAY", "TEST"}:
            raise ValueError("runtime_mode must be one of LIVE, REPLAY, or TEST")

        self.runtime_mode = normalized_runtime_mode
        self.storage_dir = Path(storage_dir or "data/sol_shadow")
        self.story_builder = MarketEventStoryBuilder(storage_dir=storage_dir)
        self.memory = EventSourcedMarketMemory(raw_buffer_capacity=50, storage_dir=storage_dir)
        resolved_model_adapter = model_adapter or get_reasoning_adapter()
        self.model_adapter = resolved_model_adapter
        cfg_model = getattr(resolved_model_adapter, "configured_model", getattr(resolved_model_adapter, "model_name", "UNKNOWN"))
        self.thesis_memory = ThesisMemory(
            storage_dir=storage_dir,
            configured_model=cfg_model,
        )
        self.external_context_store = ExternalContextStore(
            storage_dir=storage_dir,
            runtime_mode=self.runtime_mode,
        )
        from src.oracle_sol.quota_ledger import GeminiQuotaLedger
        self.quota_ledger = GeminiQuotaLedger(
            storage_dir=str(self.storage_dir),
            api_key=getattr(resolved_model_adapter, "api_key", None),
        )
        if hasattr(resolved_model_adapter, "quota_ledger"):
            resolved_model_adapter.quota_ledger = self.quota_ledger

        self.model_adapter = resolved_model_adapter
        self.orchestrator = SolReasoningOrchestrator(
            model_adapter=self.model_adapter,
            thesis_memory=self.thesis_memory,
            memory=self.memory,
        )
        self.shadow_ledger = SolShadowLedger(
            runtime_mode=self.runtime_mode,
            storage_dir=str(self.storage_dir),
        )
        self.replay_engine = SolCycleReplayEngine(ledger=self.shadow_ledger)

        # Hydrate last snapshot baseline for continuity
        self.story_builder.hydrate_last_snapshot(self.memory._session_date)

        self._successful_ai_call_count: int = 0
        self._last_analysis_timestamp_ist: Optional[str] = None
        self._is_reasoning_in_flight: bool = False
        self._last_provider_error: Optional[str] = None
        self._provider_status = (
            "IDLE" if self.model_adapter.is_configured else "NOT_CONFIGURED"
        )
        self._last_provider_error_telemetry: Dict[str, Any] = {}
        self._runtime_instance_id = uuid.uuid4().hex
        self._state_revision = 0

        self._latest_beacon = SolBeaconOutput(
            system_status=SystemStatus.UNAVAILABLE.value,
            reasoning_status=ReasoningStatus.AWAITING_EVIDENCE.value,
            market_verdict=None,  # Explicitly None, NOT NO_TRADE
            developing_state=DevelopingState.UNRESOLVED.value,
            why_bullets=[
                "Market Brain initializing",
                "Awaiting first canonical market snapshot",
                "Market thesis suspended",
            ],
            main_contradiction="ENGINE_INITIALIZING",
            what_changed="Service boot.",
            thesis_timestamp_ist="00:00:00",
            feed_age_ms=None,
            configured_model=self.model_adapter.configured_model,
            actually_invoked_model="NONE",
            schema_version="3.2.0-beacon-gemini",
        )
        self._latest_snapshot: Optional[SolEvidenceSnapshot] = None
        self._lock = threading.Lock()
        self._session_lock = threading.RLock()
        self._active_session_date = self.memory._session_date
        self._session_generation = 0

        # SSE Broadcasting
        self._subscribers: List[queue.Queue] = []
        self._subs_lock = threading.Lock()

        # Non-blocking worker
        self.worker = SolMarketBrainWorker(
            process_callback=self._process_snapshot_sync,
            worker_name="citadel-sol-brain-worker",
        )
        self.worker.start()

        # Phase-1 cognition is a separate, bounded downstream lane.  Default
        # activation is restricted to the real LIVE singleton; isolated tests
        # and replay instances opt in explicitly with mocked coordinators.
        self.cognitive_bridge = None
        enable_cognitive_bridge = (
            cognitive_bridge_enabled
            if cognitive_bridge_enabled is not None
            else self.runtime_mode == "LIVE" and storage_dir is None
        )
        if enable_cognitive_bridge:
            from src.external_context.core import ExternalContextCore
            from src.oracle_sol.cognitive_event_bridge import CognitiveEventBridge
            from src.oracle_sol.phase1_coordinator import Phase1CognitiveCoordinator
            from src.oracle_sol.thesis_graph import ThesisGraph

            cognitive_graph = ThesisGraph(
                storage_path="data/oracle_sol/thesis_graph.jsonl"
            )
            cognitive_coordinator = Phase1CognitiveCoordinator(thesis_graph=cognitive_graph)
            ext_core = ExternalContextCore.get_instance()
            self.cognitive_bridge = CognitiveEventBridge(
                event_source=self.memory.get_all_session_events,
                thesis_graph=cognitive_graph,
                coordinator=cognitive_coordinator,
                external_events_source=lambda: ext_core.get_latest_events(limit=20),
                external_quotes_source=ext_core.get_latest_quotes,
                status_path="data/oracle_sol/live_cognitive_status.json",
            )
            self.cognitive_bridge.start(
                self._active_session_date,
                self._session_generation,
            )

    def _handle_critical_provenance_failure(self, error_message: str) -> None:
        """Fail closed immediately upon VOB contamination, unverified lineage, or extraction error."""
        with self._lock:
            self._latest_beacon = SolBeaconOutput(
                system_status=SystemStatus.DATA_DEGRADED.value,
                reasoning_status=ReasoningStatus.NOT_INVOKED.value,
                market_verdict=None,  # Explicitly suspend any previous CALL/PUT verdict
                developing_state=DevelopingState.UNRESOLVED.value,
                why_bullets=[
                    "CRITICAL TRUTH FIREWALL FAILURE",
                    "DATA DEGRADED / REASONING SUSPENDED",
                    f"Lineage error: {error_message}",
                ],
                main_contradiction="DATA_LINEAGE_CONTAMINATION",
                what_changed="Truth firewall failure detected. Market thesis suspended.",
                thesis_timestamp_ist=datetime.now(IST).strftime("%H:%M:%S"),
                feed_age_ms=None,
                configured_model=self.model_adapter.configured_model,
                actually_invoked_model="NONE",
                schema_version="3.2.0-beacon-gemini",
            )
        self._broadcast_sse(self._latest_beacon)

    def report_projection_failure(self, error_message: str) -> None:
        """Expose producer-boundary failure as current fail-closed state."""
        self._handle_critical_provenance_failure(
            f"Production projection failure: {error_message}"
        )

    def ingest_feeds(self, feeds: Mapping[str, Any]) -> bool:
        """Convenience method to extract canonical snapshot from feeds and ingest."""
        from src.oracle_sol.snapshot_extractor import extract_sol_evidence_snapshot

        try:
            snapshot = extract_sol_evidence_snapshot(feeds)
            return self.ingest_snapshot(snapshot)
        except Exception as exc:
            self._handle_critical_provenance_failure(str(exc))
            return False

    def ingest_snapshot(self, snapshot: SolEvidenceSnapshot) -> bool:
        """Ingest a new canonical snapshot, detect session boundaries, and dispatch to worker."""
        # 1. Enforce Fail-Closed VOB-Free Field Allowlist Gate
        try:
            ProvenanceGuard.verify_field_level_allowlist(snapshot.to_dict(), strict=True)
        except Exception as exc:
            self._handle_critical_provenance_failure(str(exc))
            return False

        session_boundary_beacon: Optional[SolBeaconOutput] = None
        cognitive_trigger = None
        with self._session_lock:
            # 2. Check Session Boundary Transition (Auto-Rotate on unified market_session_date)
            session_date = snapshot.market_session_date
            rotated = self.memory.check_session_boundary(session_date)
            if rotated:
                self._session_generation += 1
                self._active_session_date = session_date
                self.thesis_memory.reset_session(session_date)
                self.story_builder.reset_session(session_date)
                self.story_builder.hydrate_last_snapshot(session_date)
                session_boundary_beacon = self._build_session_boundary_beacon(snapshot)
                if self.cognitive_bridge is not None:
                    self.cognitive_bridge.rotate_session(
                        session_date,
                        self._session_generation,
                    )

            with self._lock:
                self._latest_snapshot = snapshot
                if session_boundary_beacon is not None:
                    self._latest_beacon = session_boundary_beacon

            # 3. Two-phase Atomic Event Compilation & Commit
            try:
                events = self.story_builder.compile_events(snapshot)
                if events:
                    self.memory.append_batch(events)
                # Commit comparison baseline ONLY after durable event append succeeds
                self.story_builder.commit_baseline(snapshot)
            except Exception as exc:
                self._handle_critical_provenance_failure(f"Event transaction failure: {str(exc)}")
                return False

            job_session_date = self._active_session_date
            job_generation = self._session_generation
            if self.cognitive_bridge is not None:
                self.cognitive_bridge.observe_market_state(
                    snapshot,
                    job_session_date,
                    job_generation,
                )
                if events:
                    from src.oracle_sol.cognitive_event_bridge import CognitiveEventTrigger

                    story = self.memory.get_active_story()
                    cognitive_trigger = CognitiveEventTrigger(
                        session_id=job_session_date,
                        session_generation=job_generation,
                        source_revision=story.story_revision,
                        evidence_frontier=events[-1].event_id,
                        source_event_count=story.total_events_processed,
                        snapshot=snapshot,
                        offered_at_monotonic_ns=time.perf_counter_ns(),
                    )

        if session_boundary_beacon is not None:
            self._broadcast_sse(session_boundary_beacon)

        if cognitive_trigger is not None and self.cognitive_bridge is not None:
            # One-slot non-blocking offer; cognitive failure is isolated from the
            # existing Sol/Gemini and deterministic market-data pipelines.
            self.cognitive_bridge.offer(cognitive_trigger)

        # 4. Enqueue with immutable session ownership captured at handoff
        return self.worker.enqueue_snapshot(
            snapshot,
            session_date=job_session_date,
            session_generation=job_generation,
        )

    def stop(self) -> None:
        """Stop service-owned workers without touching any market-data owner."""
        if self.cognitive_bridge is not None:
            self.cognitive_bridge.stop()
        self.worker.stop()

    def _build_session_boundary_beacon(self, snapshot: SolEvidenceSnapshot) -> SolBeaconOutput:
        """Clear prior-session interpretation while the new session awaits reasoning."""
        return SolBeaconOutput(
            system_status=snapshot.system_status.value,
            reasoning_status=ReasoningStatus.AWAITING_EVIDENCE.value,
            market_verdict=None,
            developing_state=DevelopingState.UNRESOLVED.value,
            why_bullets=[
                f"Session {snapshot.market_session_date} initialized",
                "Awaiting current-session reasoning",
                "Prior-session interpretation is not active",
            ],
            main_contradiction="SESSION_BOUNDARY",
            what_changed="Market session rotated; current interpretation cleared.",
            thesis_timestamp_ist=snapshot.timestamp_ist,
            feed_age_ms=snapshot.dhan_quote_age_ms,
            configured_model=self.model_adapter.configured_model,
            actually_invoked_model="NONE",
            schema_version="3.2.0-beacon-gemini",
        )

    def _job_is_current(self, job: SolReasoningJob) -> bool:
        return (
            job.session_generation == self._session_generation
            and job.session_date == self._active_session_date
        )

    @contextmanager
    def _session_commit_context(self, job: SolReasoningJob):
        """Make session validation and all thesis mutations atomic against rotation."""
        with self._session_lock:
            yield self._job_is_current(job)

    def _process_snapshot_sync(
        self,
        snapshot_or_job: Any,
        is_manual: bool = False,
        use_reserved_quota: bool = False,
    ) -> Tuple[ThesisState, SolBeaconOutput, Dict[str, Any], SolModelRequestEnvelope]:
        """Synchronous reasoning cycle executed in background worker thread or manual trigger."""
        if isinstance(snapshot_or_job, SolReasoningJob):
            job = snapshot_or_job
        else:
            with self._session_lock:
                job = SolReasoningJob(
                    snapshot=snapshot_or_job,
                    session_date=self._active_session_date,
                    session_generation=self._session_generation,
                )
        snapshot = job.snapshot
        canonical_cycle_id = f"cyc_{uuid.uuid4().hex[:12]}"
        prev_thesis = self.thesis_memory.get_active_thesis()
        prev_thesis_id = prev_thesis.thesis_id

        ext_ctx = self.external_context_store.get_active_context(snapshot.market_session_date)

        self._is_reasoning_in_flight = True
        try:
            new_thesis, beacon, telemetry, envelope = self.orchestrator.execute_reasoning_cycle(
                snapshot=snapshot,
                recent_events=None,
                cycle_id=canonical_cycle_id,
                external_context=ext_ctx,
                commit_context=lambda: self._session_commit_context(job),
                is_manual=is_manual,
                use_reserved_quota=use_reserved_quota,
            )
        finally:
            self._is_reasoning_in_flight = False

        with self._session_commit_context(job) as session_is_current:
            if not session_is_current:
                telemetry["status"] = "OBSOLETE_SESSION_RESULT"
                telemetry["discarded"] = True
                return new_thesis, beacon, telemetry, envelope

            status = telemetry.get("status")
            if status == "SUCCESS":
                self._successful_ai_call_count += 1
                self._last_analysis_timestamp_ist = datetime.now(IST).strftime("%H:%M:%S")
                self._last_provider_error = None
                self._provider_status = "CONNECTED"
            elif status == "QUOTA_LIMIT_RPD":
                self._provider_status = "DAILY_QUOTA_USED"
                self._last_provider_error = "QUOTA_LIMIT_RPD"
                safe_error = safe_provider_error_telemetry(
                    telemetry, getattr(self.model_adapter, "api_key", None)
                )
                safe_error.setdefault("error_at_utc", datetime.now(timezone.utc).isoformat())
                self._last_provider_error_telemetry = safe_error
            elif status in {
                "PACING_GOVERNOR_HOLD",
                "MIN_INTERVAL_COOLDOWN",
                "NO_NEW_EVENTS",
                "FAIL_CLOSED_SYSTEM_STATUS",
            }:
                # Pacing hold is normal standby operation, not a degraded failure
                if status == "FAIL_CLOSED_SYSTEM_STATUS":
                    # Local market/data gating made no provider request. Preserve
                    # the last actual provider/quota outcome instead of replacing it.
                    quota_status = self.quota_ledger.get_telemetry(
                        self.model_adapter.configured_model
                    ).get("quota_status")
                    self._provider_status = (
                        "DAILY_QUOTA_USED" if quota_status == "QUOTA_LIMIT_RPD" else "IDLE"
                    )
                else:
                    self._provider_status = "PACING_HOLD" if status != "NO_NEW_EVENTS" else "IDLE"
            elif status == "RETRY_DEFERRED":
                self._provider_status = "COOLDOWN"
                if not self._last_provider_error_telemetry:
                    self._last_provider_error = "RETRY_DEFERRED"
                    self._last_provider_error_telemetry = safe_provider_error_telemetry(
                        telemetry,
                        getattr(self.model_adapter, "api_key", None),
                    )
            elif status == "REAL_CALLS_DISABLED":
                self._provider_status = "PROTECTED_OFFLINE"
            else:
                self._provider_status = "DEGRADED"
                self._last_provider_error = str(status or "UNAVAILABLE")
                safe_error = safe_provider_error_telemetry(
                    telemetry,
                    getattr(self.model_adapter, "api_key", None),
                )
                safe_error.setdefault("error_at_utc", datetime.now(timezone.utc).isoformat())
                self._last_provider_error_telemetry = safe_error

            with self._lock:
                self._latest_beacon = beacon

            # Record only a result still owned by the active session.
            recent_event_ids = [e.event_id for e in self.memory.get_recent_raw_events(limit=25)]
            self.shadow_ledger.record_cycle(
                cycle_id=canonical_cycle_id,
                snapshot=snapshot,
                previous_thesis_id=prev_thesis_id,
                new_thesis=new_thesis,
                beacon=beacon,
                telemetry=telemetry,
                recent_event_ids=recent_event_ids,
                request_envelope=envelope,
            )

            self._broadcast_sse(beacon)

        return new_thesis, beacon, telemetry, envelope

    def ingest_external_context(
        self, raw_payload: Dict[str, Any]
    ) -> Tuple[bool, List[str], Optional[ExternalContextPayload]]:
        """Validate and ingest a structured Spark external context payload."""
        source_type = str(raw_payload.get("source_type", "")).strip().upper()
        is_test_fixture = bool(raw_payload.get("is_test_fixture")) or source_type == "TEST_FIXTURE"
        if is_test_fixture and self.runtime_mode != "TEST":
            return False, ["Test fixtures require an isolated TEST runtime."], None

        payload_for_validation = dict(raw_payload)
        if self.runtime_mode != "TEST":
            received_now_utc = datetime.now(timezone.utc)
            payload_for_validation["received_at_utc"] = received_now_utc.isoformat()
            payload_for_validation["received_at_ist"] = received_now_utc.astimezone(IST).strftime("%H:%M:%S")

        valid, errors, payload_obj = validate_external_context_payload(payload_for_validation)
        if not valid or not payload_obj:
            return False, errors, None

        appended = self.external_context_store.append(payload_obj)
        if not appended:
            return False, ["Failed to persist external context payload to disk."], None

        return True, [], payload_obj

    def get_latest_beacon(self) -> SolBeaconOutput:
        """Retrieve current minimal Beacon state."""
        with self._lock:
            return self._latest_beacon

    def get_latest_beacon_state(self) -> Dict[str, Any]:
        """Return Beacon plus monotonic runtime identity for transport ordering."""
        with self._lock:
            return {
                **self._latest_beacon.to_dict(),
                "canonical_market_state": resolve_canonical_market_state(
                    self._latest_beacon.market_verdict,
                    self._latest_beacon.developing_state,
                ),
                "state_revision": self._state_revision,
                "runtime_instance_id": self._runtime_instance_id,
            }

    def get_latest_thesis(self) -> ThesisState:
        """Retrieve current detailed thesis state."""
        return self.thesis_memory.get_active_thesis()

    def get_latest_state(self) -> Dict[str, Any]:
        """Return full inspection state for developer dashboard and API."""
        with self._lock:
            beacon = self._latest_beacon
            snapshot = self._latest_snapshot
            state_revision = self._state_revision
            runtime_instance_id = self._runtime_instance_id

        thesis = self.thesis_memory.get_active_thesis()
        recent_events = self.memory.get_recent_raw_events(limit=15)
        active_story = self.memory.get_active_story()

        # Derive independent health strip states
        data_stream = "UNAVAILABLE"
        if snapshot:
            if snapshot.system_status == SystemStatus.HEALTHY:
                data_stream = "LIVE"
            elif snapshot.system_status == SystemStatus.DATA_DEGRADED:
                data_stream = "DEGRADED"
            elif snapshot.system_status == SystemStatus.OFF_MARKET:
                data_stream = "OFF_MARKET"

        brain_worker = "WATCHING" if self.worker.health_summary().get("healthy") else "STOPPED"

        ai_provider = self._provider_status

        if self._is_reasoning_in_flight:
            reasoning_state = "ANALYZING"
        elif beacon.system_status == "DATA_DEGRADED" or not self.model_adapter.is_configured:
            reasoning_state = "SUSPENDED"
        else:
            reasoning_state = "IDLE"

        last_event_time = recent_events[-1].timestamp_ist if recent_events else "NONE"
        session_date = self.memory._session_date
        external_context_summary = self.external_context_store.get_health_summary(session_date)

        # Compute pending unanalyzed events count from cursor
        all_events = self.memory.get_all_session_events()
        cursor = self.thesis_memory.last_analyzed_event_id
        if not cursor:
            pending_events_count = len(all_events)
        else:
            cursor_idx = -1
            for idx, e in enumerate(all_events):
                if e.event_id == cursor:
                    cursor_idx = idx
                    break
            pending_events_count = len(all_events) - (cursor_idx + 1) if cursor_idx >= 0 else len(all_events)
        pending_events_count = max(0, pending_events_count)

        cfg_model = getattr(self.model_adapter, "configured_model", getattr(self.model_adapter, "model_name", "UNKNOWN"))
        quota_tel = (
            self.quota_ledger.get_telemetry(cfg_model)
            if hasattr(self, "quota_ledger")
            else {}
        )

        # External Context Core and Local Brain integration
        try:
            from src.external_context.core import ExternalContextCore
            from src.oracle_sol.local_brain_service import LocalBrainService
            from src.oracle_sol.cognitive_status import get_cognitive_models_status
            ext_core = ExternalContextCore.get_instance()
            local_brain = LocalBrainService.get_instance()
            local_brain_state = local_brain.get_shadow_state()
            latest_events = ext_core.get_latest_events(limit=10)
            latest_quotes = ext_core.get_latest_quotes()
            ext_health = ext_core.get_health()
            from src.external_context.adapters.world_market import UNAVAILABLE_TARGETS
            cognitive_models_status = get_cognitive_models_status()
            world_context_state = {
                "quotes": [q.to_dict() for q in latest_quotes],
                "events": [e.to_dict() for e in latest_events],
                "health": ext_health,
                "cockpit": ext_core.get_cockpit_context(),
                "unavailable_context": UNAVAILABLE_TARGETS,
            }
            if latest_events or ext_health.get("configured_providers", 0) > 0:
                external_context_summary["source_verification_status"] = "CONNECTED"
                if "radar" in external_context_summary:
                    external_context_summary["radar"]["source_check"] = "CONNECTED"
        except Exception as exc:
            logger.debug("Failed projecting external context state: %s", exc)
            local_brain_state = {"mode": "SHADOW", "shadow_status": "OFFLINE"}
            world_context_state = {"quotes": [], "events": [], "health": {}}
            cognitive_models_status = {"provider": "GROQ", "models": {}}

        return {
            "service": "CitadelMarketBrainService",
            "runtime_mode": self.runtime_mode,
            "session_generation": self._session_generation,
            "vob_free_verified": "ZERO_VOB_ALLOWLIST_CONFIRMED",
            "state_revision": state_revision,
            "runtime_instance_id": runtime_instance_id,
            "canonical_market_state": resolve_canonical_market_state(
                beacon.market_verdict,
                beacon.developing_state,
            ),
            "beacon": {
                **beacon.to_dict(),
                "state_revision": state_revision,
                "runtime_instance_id": runtime_instance_id,
            },
            "thesis": thesis.to_dict(),
            "thesis_history": self.thesis_memory.get_thesis_history(limit=10),
            "active_market_story": active_story.to_dict(),
            "recent_events": [e.to_dict() for e in recent_events],
            "snapshot": snapshot.to_dict() if snapshot else None,
            "worker": self.worker.health_summary(),
            "cognitive_bridge": (
                self.cognitive_bridge.get_telemetry()
                if self.cognitive_bridge is not None
                else {
                    "bridge_state": "DISABLED",
                    "paper_only": True,
                    "live_trading": False,
                    "broker_submission": False,
                    "execution_influence": 0,
                    "ai_vob_influence": 0,
                }
            ),
            "external_context": external_context_summary,
            "local_brain": local_brain_state,
            "world_context": world_context_state,
            "cognitive_models": cognitive_models_status,
            "reading_domains": {
                "futures": _matrix_domain_status(
                    snapshot,
                    ["futures_ltp", "futures_basis"],
                ),
                "options_oi": _options_oi_reading_status(snapshot),
                "flow": _matrix_domain_status(
                    snapshot,
                    ["mlofi_5l", "current_flow_x", "mlofi_session_extreme"],
                ),
                "volatility": _matrix_domain_status(
                    snapshot,
                    [
                        "atm_iv",
                        "skew_25d",
                        "skew_10d",
                        "atm_straddle_price",
                        "straddle_change_5m",
                        "expected_move_pts",
                        "net_gex_inr",
                        "highest_gex_strike",
                        "zero_gamma_level",
                    ],
                ),
                "external": {
                    "status": external_context_summary.get("reading_status", "UNAVAILABLE"),
                    "fields": {
                        "today_context": (
                            "AVAILABLE"
                            if external_context_summary.get("radar", {}).get("today_news")
                            or any(
                                section.get("items")
                                for section in external_context_summary.get("radar", {}).get("market_sections", [])
                            )
                            else "UNAVAILABLE"
                        ),
                        "source_verification": external_context_summary.get(
                            "source_verification_status", "NOT_CONNECTED"
                        ),
                    },
                },
            },
            "provider_telemetry": self.get_provider_health(),
            "quota_ledger": quota_tel,
            "health_strip": {
                "data_stream": data_stream,
                "brain_worker": brain_worker,
                "ai_provider": ai_provider,
                "reasoning_state": reasoning_state,
                "model_name": self.model_adapter.configured_model.upper(),
                "last_event_time": last_event_time,
                "last_analysis_time": self._last_analysis_timestamp_ist or "NONE",
                "last_latency_ms": self.worker.health_summary().get("last_latency_ms"),
                "pending_events_count": pending_events_count,
                "successful_ai_calls": self._successful_ai_call_count,
                "free_budget_used": quota_tel.get("requests_attempted", 0),
                "segment_remaining": quota_tel.get("segment_remaining", 0),
                "total_day_remaining": quota_tel.get("total_day_remaining", 20),
                "provider_reset_ist": quota_tel.get("provider_reset_ist_short", "12:30:00 IST"),
            },
            "persistence": {
                "jsonl_health": self.memory.event_store_status,
                "thesis_store_status": self.thesis_memory.thesis_store_status,
                "baseline_store_status": self.story_builder.baseline_store_status,
                "duckdb_health": self.shadow_ledger.duckdb_health,
                "last_successful_write_utc": self.thesis_memory.last_successful_write_utc or self.memory.last_successful_write_utc,
                "last_successful_baseline_write_utc": self.story_builder.last_successful_baseline_write_utc,
                "last_persistence_error": self.thesis_memory.last_persistence_error or self.memory.last_persistence_error or self.story_builder.last_baseline_error,
                "ledger_file_path": str(self.shadow_ledger.ledger_file_path),
                "duckdb_path": str(self.shadow_ledger.duckdb_path),
            },
            "configured_model": self.model_adapter.configured_model,
            "actually_invoked_model": beacon.actually_invoked_model,
            "model_configured": self.model_adapter.is_configured,
            "api_key_present": self.model_adapter.is_configured,
        }

    def analyze_now(
        self, use_reserved_quota: bool = False
    ) -> Tuple[ThesisState, SolBeaconOutput, Dict[str, Any], SolModelRequestEnvelope]:
        """Manually trigger immediate reasoning cycle consuming from the same quota ledger."""
        with self._lock:
            snap = self._latest_snapshot
        if snap is None:
            if self.story_builder._last_snapshot:
                snap = self.story_builder._last_snapshot
            else:
                raise ValueError("No canonical snapshot available for analysis.")
        return self._process_snapshot_sync(
            snap, is_manual=True, use_reserved_quota=use_reserved_quota
        )

    def get_provider_health(self) -> Dict[str, Any]:
        """Return only safe, allowlisted Gemini provider failure and quota telemetry."""
        last_error = dict(self._last_provider_error_telemetry)
        quota_tel = (
            self.quota_ledger.get_telemetry(self.model_adapter.configured_model)
            if hasattr(self, "quota_ledger")
            else {}
        )
        return {
            "provider_status": self._provider_status,
            "last_http_status": last_error.get("http_status"),
            "last_error_category": (
                last_error.get("last_error_category")
                or quota_tel.get("last_error_category")
            ),
            "last_error_at": last_error.get("error_at_utc"),
            "last_safe_error_message": last_error.get("safe_provider_message"),
            "provider_error_code": last_error.get("provider_error_code"),
            "provider_error_status": last_error.get("provider_error_status"),
            "quota_metric": last_error.get("quota_metric"),
            "quota_id": last_error.get("quota_id"),
            "quota_limit": last_error.get("quota_limit"),
            "quota_dimensions": last_error.get("quota_dimensions"),
            "retry_after": last_error.get("retry_after") or last_error.get("retry_delay"),
            "retry_after_seconds": last_error.get("retry_after_seconds"),
            "provider_request_attempt": last_error.get("provider_request_attempt"),
            "quota_ledger": quota_tel,
        }

    def subscribe_sse(self) -> queue.Queue:
        """Subscribe a new SSE client queue."""
        q: queue.Queue = queue.Queue(maxsize=100)
        with self._subs_lock:
            self._subscribers.append(q)
        return q

    def unsubscribe_sse(self, q: queue.Queue) -> None:
        """Remove an SSE subscriber queue upon client disconnect."""
        with self._subs_lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def _broadcast_sse(self, beacon: SolBeaconOutput) -> None:
        """Non-blockingly push beacon state updates to all active SSE subscribers."""
        with self._lock:
            self._state_revision += 1
            payload = {
                **beacon.to_dict(),
                "canonical_market_state": resolve_canonical_market_state(
                    beacon.market_verdict,
                    beacon.developing_state,
                ),
                "state_revision": self._state_revision,
                "runtime_instance_id": self._runtime_instance_id,
            }
        msg = f"event: beacon_state\ndata: {json.dumps(payload)}\n\n".encode("utf-8")
        with self._subs_lock:
            dead_queues = []
            for q in self._subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead_queues.append(q)
            for dq in dead_queues:
                self._subscribers.remove(dq)
