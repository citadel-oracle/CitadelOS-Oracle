"""Canonical single-owner order-flow calculation and publication service."""

from __future__ import annotations

import os
import hashlib
import math
import pickle
import threading
import time
from collections import Counter, defaultdict, deque
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from src.broker.dhan_time import normalize_dhan_ltt

from .contracts import (
    FLOW_FORMULA_VERSION,
    SCHEMA_VERSION,
    DataQuality,
    DepthLevel,
    DirectionalState,
    FlowProjection,
    FreshnessState,
    InstrumentIdentity,
    MarketEvent,
    canonical_hash,
)
from .episodes import EpisodeEngine
from .features import (
    BookMetrics,
    BookPressureEngine,
    OptionConfirmation,
    OptionConfirmationEngine,
    ProfileDiagnostics,
    ResponseMetrics,
    ResponseQualityEngine,
    SessionProfileEngine,
    clamp,
)
from .reconciler import VolumeReconciler
from .recorder import OrderFlowEvidenceRecorder
from .reversal import ReversalEngine
from .decision_hud import OracleDecisionHudEngine
from .flow_pulse import ArgusFlowPulseEngine


IST = ZoneInfo("Asia/Kolkata")
EXCHANGE_SEGMENTS = {
    0: "IDX_I",
    1: "NSE_EQ",
    2: "NSE_FNO",
    3: "NSE_CURRENCY",
    4: "BSE_EQ",
    5: "MCX_COMM",
    7: "BSE_CURRENCY",
    8: "BSE_FNO",
}


class OrderFlowService:
    """Incremental packet->projection owner with no execution or provider I/O."""

    SCORE_CONFIG = {
        "version": FLOW_FORMULA_VERSION,
        "book_pressure_weight": 0.45,
        "response_quality_weight": 0.35,
        "option_confirmation_weight": 0.20,
        "direction_threshold": 0.20,
        "signed_coverage_gate": 0.35,
        "family_ttl_seconds": 3.0,
        "family_aging_seconds": 1.5,
        "instrument_basket_ttl_seconds": 20.0,
    }

    def __init__(
        self,
        *,
        recorder: OrderFlowEvidenceRecorder | None = None,
        clock_ns: Callable[[], int] | None = None,
        wall_clock: Callable[[], datetime] | None = None,
    ):
        self.recorder = recorder
        self.clock_ns = clock_ns or time.perf_counter_ns
        self.wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self.reconciler = VolumeReconciler()
        self.book = BookPressureEngine()
        self.response = ResponseQualityEngine()
        self.options = OptionConfirmationEngine(self.SCORE_CONFIG["family_ttl_seconds"])
        self.profile = SessionProfileEngine()
        self.reversal = ReversalEngine()
        self.episodes = EpisodeEngine()
        self.decision_hud = OracleDecisionHudEngine()
        self.flow_pulse = ArgusFlowPulseEngine(clock_ns=self.clock_ns)
        self._identities: dict[tuple[str, str], InstrumentIdentity] = {}
        self._basket_registered_ns: int | None = None
        self._latest_events: dict[str, MarketEvent] = {}
        self._latest: FlowProjection | None = None
        self._latest_book: BookMetrics | None = None
        self._latest_response: ResponseMetrics | None = None
        self._latest_profile: ProfileDiagnostics | None = None
        self._latest_option = OptionConfirmation(0, 0, "UNAVAILABLE", 0, 0, 0, 0, 0, "RAW_QUOTE_AWARE")
        self._published_base: dict[str, Any] | None = None
        self._published_events: tuple[tuple[str, MarketEvent], ...] = ()
        self._published_basket_registered_ns: int | None = None
        self._revision = 0
        self._decision_hud_recorded_revision = 0
        self._decision_hud_recorded_display_revision = 0
        self._seen_events: set[str] = set()
        self._seen_event_order: deque[str] = deque()
        self._lock = threading.RLock()
        self._latency: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=20_000))
        self._telemetry_lock = threading.Lock()
        self._telemetry_stop = threading.Event()
        self._telemetry_thread: threading.Thread | None = None
        self._telemetry_refresh_seconds = 1.0
        self._telemetry_cache: dict[str, Any] = {
            "latency_schema": "ORACLE_HOT_PATH_LATENCY_V2",
            "latency_plane": "DECISION_HOT_PATH",
            "stages_ms": {},
            "duplicates_suppressed": 0,
            "invariant_failures": 0,
            "recorder": {"status": "NOT_SAMPLED", "queue_depth": None},
            "flow_pulse": {
                "count": 0,
                "p50_ms": None,
                "p95_ms": None,
                "p99_ms": None,
                "max_ms": None,
                "stages": {},
            },
            "telemetry_mode": "ASYNC_CACHED_EXACT",
            "telemetry_refresh_count": 0,
            "telemetry_refresh_ms": None,
            "telemetry_cache_age_ms": None,
            "telemetry_last_error": None,
            "execution_influence": "ZERO",
        }
        self._telemetry_cache_published_ns = 0
        self._telemetry_refresh_count = 0
        self._telemetry_last_error: str | None = None
        self.duplicates_suppressed = 0
        self.invariant_failures = 0
        self._unknown_reasons: Counter[str] = Counter()
        self._flow_pulse_listeners: list[Callable[[str, Mapping[str, Any]], None]] = []
        self._recovering = False
        self._recovery_buffer_limit = 100_000
        self._recovery_buffer: deque[dict[str, Any]] = deque()
        self._recovery_buffer_dropped = 0
        self._recovery_metrics: dict[str, Any] = {"status": "NOT_RUN"}
        self.execution_influence = "ZERO"

    def begin_recovery(self) -> None:
        """Buffer live packets until a frozen-cutoff state is atomically restored."""
        with self._lock:
            self._recovering = True
            self._recovery_buffer.clear()
            self._recovery_buffer_dropped = 0
            self._recovery_metrics = {"status": "RUNNING"}

    def start(self) -> None:
        if self.recorder is not None:
            session_id = self.wall_clock().astimezone(IST).date().isoformat()
            self.flow_pulse.restore_paper_trades(
                self.recorder.read_paper_session(session_id)
            )
            self.recorder.start()
        self._start_telemetry()

    def stop(self) -> None:
        self._telemetry_stop.set()
        thread = self._telemetry_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._telemetry_thread = None
        if self.recorder is not None:
            self.recorder.stop()

    def register_instruments(self, identities: tuple[InstrumentIdentity, ...]) -> None:
        if not identities:
            return
        with self._lock:
            self._identities = {
                (item.exchange_segment, item.security_id): item for item in identities
            }
            self._basket_registered_ns = self.clock_ns()
            self.decision_hud.register_instruments(identities)

    def register_option_delta(self, security_id: str, delta: float, *, receive_ns: int) -> None:
        """Attach already-canonical Greeks; this method performs no fetch."""
        with self._lock:
            self.options.register_delta(security_id, delta, receive_ns=receive_ns)

    def register_decision_structure(self, projection: Mapping[str, Any], *, receive_ns: int) -> None:
        self.decision_hud.register_structure(projection, receive_ns=receive_ns)
        self._record_decision_hud(self.decision_hud.snapshot(now_ns=receive_ns))

    def register_futures_reference_levels(
        self,
        *,
        previous_day_high: float | None,
        previous_day_low: float | None,
        previous_close: float | None,
        source_timestamp: str | None = None,
    ) -> None:
        self.flow_pulse.register_reference_levels(
            previous_day_high=previous_day_high,
            previous_day_low=previous_day_low,
            previous_close=previous_close,
            source_timestamp=source_timestamp,
        )

    def register_futures_opening_range(self, *, high: float, low: float, source_timestamp: str) -> None:
        self.flow_pulse.register_opening_range(high=high, low=low, source_timestamp=source_timestamp)

    def restore_flow_pulse_session(
        self, payloads: Any, *, checkpoint_state: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Rebuild today's advisory card once from canonical raw persistence.

        This startup-only path intentionally bypasses listeners and the recorder;
        it is never reachable from live packet ingestion.
        """

        state = checkpoint_state or {}
        engine = state.get("engine") or ArgusFlowPulseEngine(clock_ns=self.clock_ns)
        if not state:
            engine.reference = self.flow_pulse.reference
        reconciler = state.get("reconciler") or VolumeReconciler()
        book_engine = state.get("book_engine") or BookPressureEngine()
        response_engine = state.get("response_engine") or ResponseQualityEngine()
        packets = int(state.get("packets") or 0)
        futures_updates = int(state.get("futures_updates") or 0)
        replayed_packets = replayed_futures = 0
        last_future: MarketEvent | None = state.get("last_future")
        source_timestamp: str | None = None
        for payload in payloads:
            if not isinstance(payload, Mapping):
                continue
            try:
                received_ist = datetime.fromisoformat(
                    str(payload["receive_wall_utc"])
                ).astimezone(IST)
                if not (
                    (received_ist.hour, received_ist.minute) >= (9, 15)
                    and (received_ist.hour, received_ist.minute) < (15, 30)
                ):
                    continue
                depth = tuple(DepthLevel(**dict(item)) for item in payload["depth_5"])
                event = MarketEvent(
                    SCHEMA_VERSION,
                    str(payload["session_id"]), int(payload.get("feed_generation") or 1),
                    str(payload["event_id"]), str(payload["exchange_segment"]),
                    str(payload["security_id"]), str(payload["instrument_role"]),
                    payload.get("expiry"), payload.get("strike"), payload.get("option_type"),
                    int(payload.get("ltt_normalized_epoch") or payload.get("exchange_ltt") or 0),
                    str(payload["receive_wall_utc"]),
                    int(payload["feed_receive_monotonic_ns"]),
                    int(payload["decode_done_monotonic_ns"]),
                    float(payload["ltp"]), int(payload["ltq"]),
                    int(payload["cumulative_volume"]), float(payload["atp"]),
                    int(payload.get("open_interest", payload.get("oi", 0))),
                    int(payload.get("high_open_interest", payload.get("high_oi", 0))),
                    int(payload.get("low_open_interest", payload.get("low_oi", 0))),
                    int(payload.get("total_buy_quantity", payload.get("total_buy_qty", 0))),
                    int(payload.get("total_sell_quantity", payload.get("total_sell_qty", 0))), depth,
                    DataQuality.DEGRADED if int(payload.get("transport_gap_count") or 0) else DataQuality.GOOD,
                    str(payload["packet_fingerprint"]),
                )
                trade = reconciler.reconcile(event)
            except (KeyError, TypeError, ValueError):
                continue
            packets += 1
            replayed_packets += 1
            source_timestamp = str(payload.get("receive_wall_utc") or "") or source_timestamp
            # Reconstructing a full live-session journal is CPU-heavy. Yield
            # cooperatively so FastAPI's cache-only health/publication thread
            # remains schedulable and an external 5s probe cannot misclassify
            # a bound, recovering runtime as dead.
            if packets % 16 == 0:
                os.sched_yield()
            book = book_engine.update(event, trade)
            response = (
                response_engine.update(event, trade, book)
                if event.instrument_role == "NIFTY_FUTURE" else None
            )
            engine.update(event, trade, book=book, response=response)
            engine.drain_transitions()
            engine.drain_semantic_transitions()
            engine.drain_level_transitions()
            engine.drain_paper_events()
            if event.instrument_role == "NIFTY_FUTURE":
                futures_updates += 1
                replayed_futures += 1
                last_future = event
        latest = engine.latest()
        if not latest or last_future is None:
            return {"status": "UNAVAILABLE", "packets": packets, "futures_updates": futures_updates}
        with self._lock:
            self.flow_pulse = engine
            self._published_base = {
                "status": "AVAILABLE", "advisory_only": True,
                "execution_influence": "ZERO", "score_authority": "NONE",
                "flow_pulse": latest,
            }
            self._published_events = (("NIFTY_FUTURE", last_future),)
            self._published_basket_registered_ns = self.clock_ns()
        return {
            "status": "RESTORED", "packets": packets,
            "futures_updates": futures_updates,
            "replayed_packets": replayed_packets,
            "replayed_futures_updates": replayed_futures,
            "session_id": engine.session_id,
            "flow_pulse_revision": latest.get("revision"),
            "source_timestamp": source_timestamp,
            "checkpoint_state": {
                "engine": engine, "reconciler": reconciler,
                "book_engine": book_engine, "response_engine": response_engine,
                "last_future": last_future, "packets": packets,
                "futures_updates": futures_updates,
            },
        }

    def restore_flow_pulse_journal(
        self,
        journal_path: str | Path,
        *,
        checkpoint_path: str | Path,
        cutoff_bytes: int | None = None,
        checkpoint_identity: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Restore from a trusted state checkpoint to one frozen journal EOF.

        The read cutoff is captured exactly once before any replay begins.  A
        checkpoint is trusted only when its journal boundary, schema, basket,
        and declared compatibility identity match this runtime.  These checks
        are operational only; the restored Flow Pulse formulas are untouched.
        """

        started = time.perf_counter()
        journal = Path(journal_path)
        checkpoint = Path(checkpoint_path)
        telemetry_path = checkpoint.with_suffix(checkpoint.suffix + ".recovery.json")
        if not journal.exists():
            result = {
                "status": "NOT_REQUIRED",
                "reason": "TODAY_RAW_JOURNAL_NOT_FOUND",
                "checkpoint_selected": None,
                "checkpoint_compatibility": "NOT_APPLICABLE",
                "recovery_complete": True,
                "live_tail_attached": True,
                "recovery_duration_ms": round((time.perf_counter() - started) * 1_000.0, 3),
            }
            self._persist_recovery_telemetry(telemetry_path, result)
            with self._lock:
                self._recovery_metrics = result
                self._recovering = False
            return dict(result)
        cutoff = min(journal.stat().st_size, int(cutoff_bytes or journal.stat().st_size))
        session_id = journal.stem
        state = None
        offset = 0
        checkpoint_used = False
        checkpoint_reason = "MISSING"
        checkpoint_created_at = None
        checkpoint_selected = str(checkpoint) if checkpoint.exists() else None
        checkpoint_universe_status = "NOT_AVAILABLE"
        checkpoint_universe_fingerprint = None
        checkpoint_source_timestamp = None
        expected_identity = self._checkpoint_identity(checkpoint_identity)
        try:
            envelope = pickle.loads(checkpoint.read_bytes())
            body = envelope["body"]
            if hashlib.sha256(body).hexdigest() != envelope["sha256"]:
                raise ValueError("CHECKPOINT_DIGEST_MISMATCH")
            saved = pickle.loads(body)
            offset = int(saved["journal_offset"])
            checkpoint_selected = str(checkpoint)
            checkpoint_created_at = saved.get("created_at")
            checkpoint_universe_fingerprint = saved.get("instrument_universe_fingerprint")
            checkpoint_source_timestamp = saved.get("source_timestamp")
            boundary_start = max(0, offset - 4096)
            with journal.open("rb") as handle:
                handle.seek(boundary_start)
                boundary = handle.read(offset - boundary_start)
            if saved.get("format_version") != 2:
                raise ValueError("CHECKPOINT_FORMAT_INCOMPATIBLE")
            if saved.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("CHECKPOINT_SCHEMA_INCOMPATIBLE")
            if saved.get("flow_formula_version") != FLOW_FORMULA_VERSION:
                raise ValueError("CHECKPOINT_FLOW_FORMULA_INCOMPATIBLE")
            if saved.get("session_date") != session_id:
                raise ValueError("CHECKPOINT_SESSION_INCOMPATIBLE")
            # The journal boundary authenticates the restored session.  The
            # live ATM basket may legitimately roll while the process is down;
            # that drift is observable but does not change Flow Pulse formulas
            # or invalidate a compatible historical checkpoint.
            checkpoint_universe_status = (
                "MATCH"
                if checkpoint_universe_fingerprint == self._instrument_universe_fingerprint()
                else "LIVE_BASKET_DIFFERENT"
            )
            saved_identity = saved.get("build_identity")
            if saved_identity != expected_identity:
                if self._topology_only_checkpoint_compatible(saved_identity, expected_identity):
                    checkpoint_reason = "COMPATIBLE_FLOW_SEMANTICS_RUNTIME_TOPOLOGY_CHANGED"
                else:
                    raise ValueError("CHECKPOINT_BUILD_INCOMPATIBLE")
            if not 0 <= offset <= cutoff or hashlib.sha256(boundary).hexdigest() != saved.get("boundary_sha256"):
                raise ValueError("CHECKPOINT_BOUNDARY_INVALID")
            state = saved["state"]
            checkpoint_used = True
            if checkpoint_reason != "COMPATIBLE_FLOW_SEMANTICS_RUNTIME_TOPOLOGY_CHANGED":
                checkpoint_reason = "COMPATIBLE"
        except (FileNotFoundError, KeyError, OSError, TypeError, ValueError, pickle.PickleError) as error:
            state = None
            offset = 0
            checkpoint_reason = str(error) or type(error).__name__

        records_read = 0
        final_offset = offset

        def payloads():
            nonlocal records_read, final_offset
            with journal.open("rb") as handle:
                handle.seek(offset)
                while handle.tell() < cutoff:
                    line_start = handle.tell()
                    line = handle.readline(cutoff - line_start)
                    if not line or not line.endswith(b"\n"):
                        break
                    final_offset = handle.tell()
                    try:
                        row = __import__("json").loads(line)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    records_read += 1
                    payload = row.get("payload") if isinstance(row, Mapping) else None
                    if isinstance(payload, Mapping):
                        yield payload

        result = self.restore_flow_pulse_session(payloads(), checkpoint_state=state)
        if result.get("source_timestamp") is None and checkpoint_source_timestamp is not None:
            result["source_timestamp"] = checkpoint_source_timestamp
        restored_state = result.pop("checkpoint_state", None)
        if result.get("status") == "RESTORED" and restored_state is not None:
            boundary_start = max(0, final_offset - 4096)
            with journal.open("rb") as handle:
                handle.seek(boundary_start)
                boundary = handle.read(final_offset - boundary_start)
            saved = {
                "format_version": 2,
                "schema_version": SCHEMA_VERSION,
                "flow_formula_version": FLOW_FORMULA_VERSION,
                "build_identity": expected_identity,
                "session_date": session_id,
                "instrument_universe_fingerprint": self._instrument_universe_fingerprint(),
                "journal_path": str(journal.resolve()),
                "journal_offset": final_offset,
                "cutoff": cutoff,
                "record_count": int(restored_state.get("packets") or result.get("packets") or records_read),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_timestamp": result.get("source_timestamp"),
                "boundary_sha256": hashlib.sha256(boundary).hexdigest(),
                "state": restored_state,
            }
            body = pickle.dumps(saved, protocol=5)
            encoded = pickle.dumps({"sha256": hashlib.sha256(body).hexdigest(), "body": body}, protocol=5)
            _atomic_write_bytes(checkpoint, encoded)

        with self._lock:
            buffered = list(self._recovery_buffer)
            self._recovery_buffer.clear()
            buffered_dropped = self._recovery_buffer_dropped
            self._recovering = False
        for tick in buffered:
            self.ingest_tick(tick)
        self._recovery_metrics = {
            **{key: value for key, value in result.items() if key != "checkpoint_state"},
            "checkpoint_used": checkpoint_used,
            "checkpoint_selected": checkpoint_selected,
            "checkpoint_created_at": checkpoint_created_at,
            "checkpoint_source_timestamp": checkpoint_source_timestamp,
            "checkpoint_offset": offset if checkpoint_selected else None,
            "checkpoint_compatibility": checkpoint_reason,
            "checkpoint_universe_status": checkpoint_universe_status,
            "checkpoint_instrument_universe_fingerprint": checkpoint_universe_fingerprint,
            "journal_cutoff_bytes": cutoff,
            "journal_start_offset": offset,
            "journal_final_offset": final_offset,
            "journal_records_read": records_read,
            "buffered_packets_applied": len(buffered),
            "buffered_live_packets": len(buffered),
            "buffered_live_packets_dropped": buffered_dropped,
            "records_replayed": result.get("replayed_packets", 0),
            "packets_replayed": result.get("replayed_packets", 0),
            "recovery_complete": True,
            "live_tail_attached": True,
            "recovery_duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "recovery_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }
        self._persist_recovery_telemetry(telemetry_path, self._recovery_metrics)
        return dict(self._recovery_metrics)

    def _checkpoint_identity(self, supplied: Mapping[str, Any] | None) -> dict[str, Any]:
        """Small explicit compatibility identity; never contains credentials."""
        base = {
            "flow_formula_version": FLOW_FORMULA_VERSION,
            "schema_version": SCHEMA_VERSION,
        }
        for key, value in dict(supplied or {}).items():
            if value is not None:
                base[str(key)] = str(value)
        return dict(sorted(base.items()))

    @staticmethod
    def _topology_only_checkpoint_compatible(
        saved: object,
        expected: Mapping[str, Any],
    ) -> bool:
        """Allow an audited runtime-topology change without accepting formula drift.

        ``code_fingerprint`` intentionally includes ``app/main.py`` so runtime
        provenance is comprehensive.  It therefore changes for isolation or
        lifecycle wiring even when the persisted Flow Pulse state and its
        formula contract are unchanged.  A checkpoint may bridge *only* that
        difference when the versioned Flow contract and the checked-out source
        revision are identical.  Any extra or missing identity field is a
        fail-closed incompatibility.
        """

        if not isinstance(saved, Mapping):
            return False
        required = {"flow_formula_version", "schema_version", "git_head", "git_branch", "code_fingerprint"}
        saved_keys = {str(key) for key in saved}
        expected_keys = {str(key) for key in expected}
        if saved_keys != required or expected_keys != required:
            return False
        for key in required - {"code_fingerprint"}:
            if str(saved.get(key)) != str(expected.get(key)):
                return False
        return bool(saved.get("code_fingerprint")) and bool(expected.get("code_fingerprint"))

    def _instrument_universe_fingerprint(self) -> str:
        with self._lock:
            values = [
                {
                    "exchange_segment": item.exchange_segment,
                    "security_id": item.security_id,
                    "role": item.role,
                    "expiry": item.expiry,
                    "strike": item.strike,
                    "option_type": item.option_type,
                }
                for item in self._identities.values()
            ]
        body = __import__("json").dumps(
            sorted(values, key=lambda item: (item["exchange_segment"], item["security_id"])),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(body.encode()).hexdigest()

    @staticmethod
    def _persist_recovery_telemetry(path: Path, value: Mapping[str, Any]) -> None:
        try:
            _atomic_write_bytes(
                path,
                __import__("json").dumps(dict(value), sort_keys=True, default=str).encode("utf-8"),
            )
        except OSError:
            # Telemetry failure must not invalidate a correctly restored engine.
            pass

    def subscribe_flow_pulse(
        self, listener: Callable[[str, Mapping[str, Any]], None]
    ) -> Callable[[], None]:
        """Attach a cache-only publisher; callbacks must never fetch or persist."""

        with self._lock:
            self._flow_pulse_listeners.append(listener)
        def unsubscribe() -> None:
            with self._lock:
                if listener in self._flow_pulse_listeners:
                    self._flow_pulse_listeners.remove(listener)
        return unsubscribe

    def latest_decision_hud(self) -> dict[str, Any]:
        hud = self.decision_hud.snapshot(now_ns=self.clock_ns())
        self._record_decision_hud(hud)
        return hud

    def _record_decision_hud(self, hud: Mapping[str, Any]) -> None:
        revision = int(hud.get("revision") or 0)
        display_revision = int(hud.get("display_revision") or 0)
        with self._lock:
            if self.recorder is None or (
                revision == self._decision_hud_recorded_revision
                and display_revision == self._decision_hud_recorded_display_revision
            ):
                return
            self._decision_hud_recorded_revision = revision
            self._decision_hud_recorded_display_revision = display_revision
            self.recorder.submit("DECISION_HUD_TRANSITION", hud, str(hud["projection_id"]))

    def ingest_tick(self, tick: Mapping[str, Any]) -> FlowProjection | None:
        if int(tick.get("response_code") or tick.get("feed_code") or 0) != 8:
            return None
        with self._lock:
            if self._recovering:
                if len(self._recovery_buffer) >= self._recovery_buffer_limit:
                    self._recovery_buffer.popleft()
                    self._recovery_buffer_dropped += 1
                self._recovery_buffer.append(dict(tick))
                return self._latest
        state_started = self.clock_ns()
        try:
            event = self._market_event(tick)
        except (KeyError, TypeError, ValueError):
            return None
        with self._lock:
            if event.event_id in self._seen_events:
                self.duplicates_suppressed += 1
                return self._latest
            self._seen_events.add(event.event_id)
            self._seen_event_order.append(event.event_id)
            if len(self._seen_event_order) > 50_000:
                self._seen_events.discard(self._seen_event_order.popleft())
            try:
                trade = self.reconciler.reconcile(event)
            except ValueError:
                self.invariant_failures += 1
                return self._latest
            if trade.unclassified_qty:
                self._unknown_reasons[_unknown_reason(trade)] += trade.unclassified_qty
            state_done_ns = self.clock_ns()
            book = self.book.update(event, trade)
            self._latest_events[event.instrument_role] = event
            if event.instrument_role == "NIFTY_FUTURE":
                self._latest_book = book
                self._latest_response = self.response.update(event, trade, book)
                self._latest_profile = self.profile.update(
                    event, trade, response_state=self._latest_response.state
                )
            elif event.option_type in {"CE", "PE"}:
                self._latest_option = self.options.update(event, trade, book, now_ns=state_done_ns)
                self.decision_hud.ingest_option(event, trade, book, now_ns=event.feed_receive_ns)
                self._record_decision_hud(self.decision_hud.snapshot(now_ns=event.feed_receive_ns))
            self.flow_pulse.update(
                event,
                trade,
                book=book if event.instrument_role == "NIFTY_FUTURE" else None,
                response=self._latest_response,
            )
            pulse_transitions = self.flow_pulse.drain_transitions()
            semantic_transitions = self.flow_pulse.drain_semantic_transitions()
            level_transitions = self.flow_pulse.drain_level_transitions()
            validation_events = self.flow_pulse.drain_validation_events()
            if self._flow_pulse_listeners:
                structural_level_change = any(
                    transition.get("action_worthy") is True
                    for transition in level_transitions
                )
                publication_kind = (
                    "FLOW_PULSE_ACTION"
                    if pulse_transitions or structural_level_change
                    else "FLOW_PULSE_METERS"
                )
                payload = (
                    self.flow_pulse.action_payload()
                    if publication_kind == "FLOW_PULSE_ACTION"
                    else self.flow_pulse.meters_payload()
                )
                for listener in tuple(self._flow_pulse_listeners):
                    try:
                        listener(publication_kind, payload)
                    except Exception:
                        # Publication is advisory and isolated from packet truth.
                        self.invariant_failures += 1
            if self.recorder is not None:
                for transition in pulse_transitions:
                    self.recorder.submit(
                        "FLOW_PULSE_TRANSITION",
                        transition,
                        f"{transition.get('timestamp')}:{transition.get('from')}:{transition.get('to')}",
                    )
                for transition in semantic_transitions:
                    self.recorder.submit(
                        "FLOW_PULSE_SEMANTIC_TRANSITION",
                        transition,
                        f"{transition.get('timestamp')}:{transition.get('field')}:{transition.get('semantic_revision')}",
                    )
                for transition in level_transitions:
                    self.recorder.submit(
                        "FLOW_PULSE_LEVEL_TRANSITION",
                        transition,
                        f"{transition.get('timestamp')}:{transition.get('level')}:{transition.get('new_state')}",
                    )
                for validation_event in validation_events:
                    self.recorder.submit(
                        "FLOW_PULSE_PLAN_VALIDATION",
                        validation_event,
                        str(validation_event.get("CANDIDATE_PLAN_ID")),
                    )
                for paper_event in self.flow_pulse.drain_paper_events():
                    self.recorder.submit(
                        "EPISODE_FLOW_PULSE_PAPER_UPDATE",
                        paper_event,
                        f"{paper_event.get('trade_id')}:{paper_event.get('state')}:{paper_event.get('entry_time')}:{paper_event.get('exit_time')}",
                    )
                    self.recorder.submit(
                        "FLOW_PULSE_PAPER_SESSION_UPDATE",
                        paper_event,
                        f"session:{paper_event.get('trade_id')}:{paper_event.get('state')}:{paper_event.get('entry_time')}:{paper_event.get('exit_time')}",
                    )
            features_done_ns = self.clock_ns()
            projection = self._project(event, state_done_ns, features_done_ns)
            score_done_ns = self.clock_ns()
            projection = self._with_latency(projection, score_done_ns)
            publish_ns = self.clock_ns()
            projection = self._with_latency(projection, score_done_ns, publish_ns)
            self._latest = projection
            self._revision += 1
            selected = _selected_option_event(projection.directional_state, self._latest_events)
            episode = self.episodes.update(
                projection,
                futures_price=(self._latest_events.get("NIFTY_FUTURE").ltp if self._latest_events.get("NIFTY_FUTURE") else None),
                contract=selected.security_id if selected else None,
                option_price=selected.ltp if selected else None,
                executable_bid=selected.depth_5[0].bid_price if selected else None,
                executable_ask=selected.depth_5[0].ask_price if selected else None,
            )
            projection_value = projection.to_dict()
            pulse = self.flow_pulse.latest()
            if isinstance(pulse.get("delta"), dict):
                pulse["delta"] = {
                    **pulse["delta"],
                    "coverage": projection_value.get("signed_flow_coverage"),
                }
            published = dict(projection_value)
            published["flow_pulse"] = pulse
            # CPython reference replacement is atomic. Readers never touch the
            # mutable service lock or rebuild the canonical projection.
            self._published_events = tuple(sorted(self._latest_events.items()))
            self._published_basket_registered_ns = self._basket_registered_ns
            self._published_base = published
            self._record_latency(event, state_done_ns, features_done_ns, score_done_ns, publish_ns)
            if self.recorder is not None:
                self.recorder.submit(
                    "FLOW_PROJECTION",
                    projection_value,
                    projection.snapshot_id,
                )
                if episode is not None:
                    self.recorder.submit(
                        "EPISODE_UPDATE",
                        asdict(episode),
                        f"{episode.episode_id}:{projection.snapshot_id}",
                    )
                for completed in self.episodes.drain_closed():
                    self.recorder.submit(
                        "EPISODE_COMPLETED",
                        asdict(completed),
                        f"completed:{completed.episode_id}",
                    )
            return projection

    def latest_projection(self) -> dict[str, Any]:
        base = self._published_base
        if base is None:
            return {
                "status": "UNAVAILABLE",
                "reason": "ORDER_FLOW_PROJECTION_NOT_READY",
                "execution_influence": "ZERO",
                "authority_20_depth": "DISABLED",
            }
        # Shallow overlay only: the nested canonical payload is immutable and
        # replaced wholesale by ingest_tick for every source revision.
        value = dict(base)
        now_ns = self.clock_ns()
        freshness = {
            role: _freshness(event, now_ns, self.SCORE_CONFIG)
            for role, event in self._published_events
        }
        value["freshness"] = freshness
        ages = [
            item.get("age_seconds")
            for item in freshness.values()
            if isinstance(item.get("age_seconds"), (int, float))
        ]
        value["snapshot_age_seconds"] = round(max(ages), 6) if ages else None
        
        # Phase 2: Complete Domestic Live Index Context
        value["domestic_indices"] = {
            role: event.ltp
            for role, event in self._published_events
            if role in ("NIFTY_SPOT", "BANKNIFTY_SPOT", "MIDCPNIFTY_SPOT")
        }
        
        locks = set(value.get("action_lock_reasons") or ())
        future_state = freshness.get("NIFTY_FUTURE", {}).get("state")
        basket_registered_ns = self._published_basket_registered_ns
        basket_stale = (
            basket_registered_ns is None
            or now_ns - basket_registered_ns
            > self.SCORE_CONFIG["instrument_basket_ttl_seconds"] * 1_000_000_000
        )
        if future_state == FreshnessState.STALE.value:
            locks.add("FUTURES_FULL_PACKET_STALE")
        if basket_stale:
            locks.add("INSTRUMENT_BASKET_STALE")
        if future_state == FreshnessState.STALE.value or basket_stale:
            value["directional_state"] = DirectionalState.DATA_LOCKED.value
            value["action_eligible"] = False
            value["data_quality"] = DataQuality.UNUSABLE.value
            value["projection_state"] = "LAST_GOOD"
        else:
            value["projection_state"] = "LIVE"
        value["action_lock_reasons"] = sorted(locks)
        pulse_source = value.get("flow_pulse")
        if isinstance(pulse_source, Mapping):
            pulse = dict(pulse_source)
            health = dict(pulse.get("live_health") or {})
            future_age = freshness.get("NIFTY_FUTURE", {}).get("age_seconds")
            health.update({
                "last_packet_age_ms": (
                    round(float(future_age) * 1_000.0, 3)
                    if isinstance(future_age, (int, float)) else None
                ),
                "last_semantic_revision": pulse.get("semantic_revision"),
                "last_action_revision": pulse.get("action_revision"),
            })
            now_ist = self.wall_clock().astimezone(IST)
            market_open = (
                now_ist.weekday() < 5
                and (now_ist.hour, now_ist.minute) >= (9, 15)
                and (now_ist.hour, now_ist.minute) < (15, 30)
            )
            if future_state == FreshnessState.STALE.value and market_open:
                health["status"] = "DATA STALE"
                health["source_advancing"] = False
                pulse["headline"] = "NO TRADE"
                pulse["story"] = "DATA STALE · NEW ACTION BLOCKED"
                pulse["what_happened"] = "DATA STALE"
                pulse["action_blocked"] = True
            elif not market_open:
                health["status"] = "SESSION CLOSED · LAST LIVE"
                health["source_advancing"] = False
                pulse["session_status"] = "SESSION CLOSED · LAST LIVE"
            else:
                health["status"] = "LIVE"
                health["source_advancing"] = True
            pulse["live_health"] = health
            value["flow_pulse"] = pulse
        return value

    def telemetry(self) -> dict[str, Any]:
        # Cache-only read.  Snapshot publication runs on the sequential packet
        # thread, so it must never sort mature telemetry windows.
        with self._telemetry_lock:
            value = dict(self._telemetry_cache)
            published_ns = self._telemetry_cache_published_ns
        value["telemetry_cache_age_ms"] = (
            round(max(0.0, (self.clock_ns() - published_ns) / 1_000_000.0), 3)
            if published_ns else None
        )
        thread = self._telemetry_thread
        value["telemetry_thread_alive"] = bool(
            thread is not None and thread.is_alive()
        )
        return value

    def refresh_telemetry(self) -> dict[str, Any]:
        """Compute exact bounded-window percentiles outside the packet thread."""

        started_ns = self.clock_ns()
        try:
            with self._telemetry_lock:
                stage_samples = {
                    name: tuple(values)
                    for name, values in self._latency.items()
                }
                duplicates = self.duplicates_suppressed
                invariant_failures = self.invariant_failures
            stages = {
                name: _distribution(list(values))
                for name, values in stage_samples.items()
            }
            flow_pulse = self.flow_pulse.telemetry()
            recorder = (
                self.recorder.health()
                if self.recorder is not None
                else {"status": "DISABLED", "queue_depth": 0}
            )
            completed_ns = self.clock_ns()
            self._telemetry_refresh_count += 1
            value = {
                "latency_schema": "ORACLE_HOT_PATH_LATENCY_V2",
                "latency_plane": "DECISION_HOT_PATH",
                "stages_ms": stages,
                "duplicates_suppressed": duplicates,
                "invariant_failures": invariant_failures,
                "recorder": recorder,
                "flow_pulse": flow_pulse,
                "telemetry_mode": "ASYNC_CACHED_EXACT",
                "telemetry_refresh_count": self._telemetry_refresh_count,
                "telemetry_refresh_ms": round(
                    max(0.0, (completed_ns - started_ns) / 1_000_000.0), 3
                ),
                "telemetry_cache_age_ms": 0.0,
                "telemetry_last_error": None,
                "execution_influence": "ZERO",
            }
            with self._telemetry_lock:
                self._telemetry_cache = value
                self._telemetry_cache_published_ns = completed_ns
                self._telemetry_last_error = None
            return dict(value)
        except Exception as error:
            self._telemetry_last_error = f"{type(error).__name__}:{error}"
            with self._telemetry_lock:
                self._telemetry_cache = {
                    **self._telemetry_cache,
                    "telemetry_last_error": self._telemetry_last_error,
                }
            return self.telemetry()

    def _start_telemetry(self) -> None:
        thread = self._telemetry_thread
        if thread is not None and thread.is_alive():
            return
        self._telemetry_stop.clear()
        self.refresh_telemetry()
        self._telemetry_thread = threading.Thread(
            target=self._telemetry_loop,
            name="order-flow-telemetry",
            daemon=True,
        )
        self._telemetry_thread.start()

    def _telemetry_loop(self) -> None:
        while not self._telemetry_stop.wait(self._telemetry_refresh_seconds):
            self.refresh_telemetry()

    def _market_event(self, tick: Mapping[str, Any]) -> MarketEvent:
        segment_value = tick["exchange_segment"]
        segment = EXCHANGE_SEGMENTS.get(segment_value, str(segment_value)) if isinstance(segment_value, int) else str(segment_value)
        security_id = str(tick["security_id"])
        identity = self._identities.get((segment, security_id))
        if identity is None:
            raise ValueError("UNROUTED_INSTRUMENT")
        generation = int(tick.get("feed_generation") or 1)
        ltt = int(tick["ltt"])
        normalized_ltt = normalize_dhan_ltt(ltt, str(tick["receive_wall_utc"]))
        if not normalized_ltt.event_session_accepted:
            raise ValueError("DHAN_LTT_OUTSIDE_NSE_SESSION")
        cumulative = int(tick["cumulative_volume"])
        fingerprint = str(tick["packet_fingerprint"])
        session_id = normalized_ltt.ist.date().isoformat()
        event_ltt = normalized_ltt.normalized_epoch
        event_seed = f"{session_id}|{generation}|{segment}|{security_id}|{event_ltt}|{cumulative}|{fingerprint}"
        event_id = "ofe_" + hashlib.sha256(event_seed.encode()).hexdigest()[:24]
        depth = tuple(
            DepthLevel(
                int(item["level"]), float(item["bid_price"]), int(item["bid_quantity"]), int(item["bid_orders"]),
                float(item["ask_price"]), int(item["ask_quantity"]), int(item["ask_orders"]),
            )
            for item in tick["depth_5"]
        )
        quality = DataQuality.DEGRADED if (
            int(tick.get("transport_gap_count") or 0)
            or int(tick.get("gateway_queue_lag_ns") or 0) > 5_000_000
            or ltt <= 0
        ) else DataQuality.GOOD
        return MarketEvent(
            SCHEMA_VERSION,
            session_id,
            generation,
            event_id,
            segment,
            security_id,
            identity.role,
            identity.expiry,
            identity.strike,
            identity.option_type,
            event_ltt,
            str(tick["receive_wall_utc"]),
            int(tick["feed_receive_ns"]),
            int(tick["decode_done_ns"]),
            float(tick["ltp"]),
            int(tick["ltq"]),
            cumulative,
            float(tick["atp"]),
            int(tick["open_interest"]),
            int(tick["high_open_interest"]),
            int(tick["low_open_interest"]),
            int(tick["total_buy_quantity"]),
            int(tick["total_sell_quantity"]),
            depth,
            quality,
            fingerprint,
        )

    def _project(self, event: MarketEvent, state_done_ns: int, features_done_ns: int) -> FlowProjection:
        book = self._latest_book
        response = self._latest_response
        option = self.options.snapshot(features_done_ns)
        self._latest_option = option
        profile = self._latest_profile
        future = self._latest_events.get("NIFTY_FUTURE")
        now = self.wall_clock().astimezone(timezone.utc)
        family_freshness = {
            role: _freshness(item, features_done_ns, self.SCORE_CONFIG)
            for role, item in sorted(self._latest_events.items())
        }
        future_state = family_freshness.get("NIFTY_FUTURE", {}).get("state", "STALE")
        book_value = book.book_pressure if book else 0.0
        response_value = response.response_quality if response else 0.0
        option_value = option.value
        book_conf = book.book_confidence if book else 0.0
        response_conf = response.confidence if response else 0.0
        option_conf = option.confidence
        total_delta = self.profile.total_delta
        known = sum(self.profile.buys.values()) + sum(self.profile.sells.values())
        signed_coverage = known / total_delta if total_delta else 0.0
        profile_coverage = profile.coverage if profile else 0.0
        future_freshness_factor = 1.0 if future_state == FreshnessState.FRESH.value else 0.5 if future_state == FreshnessState.AGING.value else 0.0
        coverage_factor = min(1.0, signed_coverage / self.SCORE_CONFIG["signed_coverage_gate"]) if total_delta else 0.0
        directional = clamp(
            (
                self.SCORE_CONFIG["book_pressure_weight"] * book_value * book_conf
                + self.SCORE_CONFIG["response_quality_weight"] * response_value * response_conf
                + self.SCORE_CONFIG["option_confirmation_weight"] * option_value * option_conf
            )
            * future_freshness_factor
            * coverage_factor
        )
        locks: list[str] = []
        quality = DataQuality.GOOD
        if any(
            item.expiry is not None and item.expiry < event.session_id
            for item in self._identities.values()
        ):
            quality = DataQuality.UNUSABLE
            locks.append("INSTRUMENT_BASKET_EXPIRED")
        if (
            self._basket_registered_ns is None
            or state_done_ns - self._basket_registered_ns
            > self.SCORE_CONFIG["instrument_basket_ttl_seconds"] * 1_000_000_000
        ):
            quality = DataQuality.UNUSABLE
            locks.append("INSTRUMENT_BASKET_STALE")
        if future is None:
            quality = DataQuality.UNUSABLE
            locks.append("FUTURES_FULL_PACKET_UNAVAILABLE")
        if future_state == FreshnessState.STALE.value:
            quality = DataQuality.UNUSABLE
            locks.append("FUTURES_FULL_PACKET_STALE")
        if book is None or book.status == "INVALID_OR_CROSSED_BOOK":
            quality = DataQuality.UNUSABLE
            locks.append("FUTURES_BOOK_INVALID")
        if future is not None and future.data_quality is not DataQuality.GOOD:
            quality = min_quality(quality, DataQuality.DEGRADED)
            locks.append("FUTURES_FEED_QUALITY_DEGRADED")
        if total_delta == 0:
            quality = min_quality(quality, DataQuality.DEGRADED)
            locks.append("SIGNED_FLOW_BASELINE_ONLY")
        elif signed_coverage < self.SCORE_CONFIG["signed_coverage_gate"]:
            quality = min_quality(quality, DataQuality.DEGRADED)
            locks.append("SIGNED_FLOW_COVERAGE_LOW")
        if option.status.startswith("STALE"):
            quality = min_quality(quality, DataQuality.DEGRADED)
            locks.append("OPTION_CONFIRMATION_STALE")
        reversal_option = _selected_option_event(
            DirectionalState.CALL if directional >= 0 else DirectionalState.PUT,
            self._latest_events,
        )
        reversal = self.reversal.update(
            directional,
            now_ns=features_done_ns,
            data_quality=quality,
            futures_price=future.ltp if future is not None else None,
            atm_premium=reversal_option.ltp if reversal_option is not None else None,
        )
        threshold = self.SCORE_CONFIG["direction_threshold"]
        if quality is DataQuality.UNUSABLE:
            state = DirectionalState.DATA_LOCKED
        elif directional >= threshold:
            state = DirectionalState.CALL
        elif directional <= -threshold:
            state = DirectionalState.PUT
        else:
            state = DirectionalState.NEUTRAL
            locks.append("NO_DIRECTIONAL_FLOW_EDGE")
        action_eligible = quality is DataQuality.GOOD and state in {DirectionalState.CALL, DirectionalState.PUT}
        if not action_eligible and not locks:
            locks.append("FLOW_DATA_QUALITY_NOT_GOOD")
        revision = self._revision + 1
        snapshot_seed = {
            "revision": revision,
            "event_id": event.event_id,
            "score": round(directional, 8),
            "quality": quality.value,
            "reversal": reversal.state.value,
        }
        snapshot_id = "flow_" + canonical_hash(snapshot_seed)[:24]
        family_values = {
            "BOOK_PRESSURE": asdict(book) if book else {"status": "UNAVAILABLE"},
            "RESPONSE_QUALITY": asdict(response) if response else {"status": "UNAVAILABLE"},
            "OPTION_CONFIRMATION": asdict(option),
            "REVERSAL": asdict(reversal),
            "LOCATION": asdict(profile) if profile else {"status": "PROFILE_DEGRADED"},
            "SCORING": dict(self.SCORE_CONFIG),
            "DATA_QUALITY_DIAGNOSTICS": {
                "unknown_top_reasons": [
                    {"reason": reason, "quantity": quantity}
                    for reason, quantity in self._unknown_reasons.most_common(7)
                ],
                "classification": "DHAN_PACKET_SEMANTIC_LIMITATION"
                if signed_coverage < self.SCORE_CONFIG["signed_coverage_gate"]
                else "SUFFICIENT_SIGNED_COVERAGE",
            },
        }
        latency = {
            "t0_packet_receive_ns": event.feed_receive_ns,
            "t1_raw_feature_ready_ns": state_done_ns,
            "t2_semantic_event_committed_ns": features_done_ns,
            "t3_canonical_payload_ready_ns": features_done_ns,
            "feed_receive_ns": event.feed_receive_ns,
            "decode_done_ns": event.decode_done_ns,
            "state_done_ns": state_done_ns,
            "features_done_ns": features_done_ns,
            "score_done_ns": features_done_ns,
            "oracle_publish_ns": features_done_ns,
        }
        return FlowProjection(
            SCHEMA_VERSION,
            FLOW_FORMULA_VERSION,
            revision,
            snapshot_id,
            event.session_id,
            now.isoformat(),
            tuple(sorted(self._identities.values(), key=lambda item: (item.role, item.security_id))),
            round(50.0 + 50.0 * directional, 6),
            round(50.0 - 50.0 * directional, 6),
            round(directional, 8),
            state,
            action_eligible,
            tuple(sorted(set(locks))),
            family_values,
            {"BOOK_PRESSURE": book_conf, "RESPONSE_QUALITY": response_conf, "OPTION_CONFIRMATION": option_conf},
            family_freshness,
            quality,
            round(signed_coverage, 6),
            round(profile_coverage, 6),
            reversal.state,
            asdict(profile) if profile else {"status": "PROFILE_DEGRADED"},
            latency,
            self.recorder.health()["status"] if self.recorder else "DISABLED",
        )

    @staticmethod
    def _with_latency(
        projection: FlowProjection,
        score_done_ns: int,
        publish_ns: int | None = None,
    ) -> FlowProjection:
        values = projection.to_dict()
        latency = dict(values["latency_timestamps"])
        latency["score_done_ns"] = score_done_ns
        latency["oracle_publish_ns"] = publish_ns or score_done_ns
        values["latency_timestamps"] = latency
        values["instruments"] = tuple(InstrumentIdentity(**item) for item in values["instruments"])
        values["directional_state"] = DirectionalState(values["directional_state"])
        values["data_quality"] = DataQuality(values["data_quality"])
        from .contracts import ReversalState
        values["reversal_state"] = ReversalState(values["reversal_state"])
        values["action_lock_reasons"] = tuple(values["action_lock_reasons"])
        return FlowProjection(**values)

    def _record_latency(
        self, event: MarketEvent, state_ns: int, features_ns: int, score_ns: int, publish_ns: int
    ) -> None:
        values = {
            "packet_to_raw": state_ns - event.feed_receive_ns,
            "raw_to_event": features_ns - state_ns,
            "event_to_payload": publish_ns - features_ns,
            "packet_to_payload": publish_ns - event.feed_receive_ns,
        }
        with self._telemetry_lock:
            for name, nanoseconds in values.items():
                self._latency[name].append(max(0.0, nanoseconds / 1_000_000.0))


def _freshness(event: MarketEvent, now_ns: int, config: Mapping[str, float]) -> dict[str, Any]:
    age = max(0.0, (now_ns - event.feed_receive_ns) / 1_000_000_000)
    if age <= config["family_aging_seconds"]:
        state = FreshnessState.FRESH
    elif age <= config["family_ttl_seconds"]:
        state = FreshnessState.AGING
    else:
        state = FreshnessState.STALE
    return {
        "state": state.value,
        "age_seconds": round(age, 6),
        "event_timestamp": event.exchange_ltt,
        "local_timestamp": event.receive_wall_utc,
        "confidence": 1.0 if state is FreshnessState.FRESH else 0.5 if state is FreshnessState.AGING else 0.0,
        "ttl_seconds": config["family_ttl_seconds"],
        "source": "DHAN_V2_FULL_WEBSOCKET",
    }


def _unknown_reason(trade) -> str:
    method = str(trade.signer_method or "")
    if method in {"BASELINE", "VOLUME_REGRESSION"}:
        return "RESET_BASELINE"
    if method == "STALE_OR_INVALID_PRE_EVENT_QUOTE":
        return "STALE_QUOTE"
    if method == "AMBIGUOUS_INSIDE_SPREAD":
        return "INSIDE_SPREAD_AMBIGUOUS"
    if trade.observed_trade_qty and trade.unclassified_qty:
        return "RESIDUAL_GT_LTQ"
    if method == "UNCLASSIFIED_AGGREGATE":
        return "LTT_AMBIGUITY"
    return "OTHER"


def min_quality(current: DataQuality, candidate: DataQuality) -> DataQuality:
    rank = {DataQuality.GOOD: 2, DataQuality.DEGRADED: 1, DataQuality.UNUSABLE: 0}
    return current if rank[current] <= rank[candidate] else candidate


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "p50": None, "p95": None, "p99": None, "max": None}
    ordered = sorted(values)
    def percentile(value: float) -> float:
        index = min(len(ordered) - 1, max(0, math.ceil(value * len(ordered)) - 1))
        return round(ordered[index], 6)
    return {
        "count": len(ordered),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": round(ordered[-1], 6),
    }


def _selected_option_event(
    state: DirectionalState,
    events: Mapping[str, MarketEvent],
) -> MarketEvent | None:
    role = "ATM_CE" if state is DirectionalState.CALL else "ATM_PE" if state is DirectionalState.PUT else None
    return events.get(role) if role else None


def _atomic_write_bytes(path: Path, value: bytes) -> None:
    """Crash-safe checkpoint/telemetry replacement with directory durability."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = __import__("tempfile").mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory = os.open(str(path.parent), os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory)
        except OSError:
            pass
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
