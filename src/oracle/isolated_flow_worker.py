"""Dedicated process ownership for the lossless Order Flow hot path.

The parent proxy deliberately mirrors the small public surface used by
``app.main``.  All packet-sequential OrderFlowService state lives in the child;
the parent only enqueues immutable packets/control messages and consumes
already-calculated current state or ordered action events.
"""

from __future__ import annotations

import os
import json
import multiprocessing as mp
import queue
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from src.order_flow.contracts import InstrumentIdentity
from src.order_flow.service import OrderFlowService
from src.oracle.shared_ipc import SharedFlag, shared_int_slots


def _distribution(values: deque[float] | tuple[float, ...]) -> dict[str, float | int | None]:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "p50": None, "p95": None, "p99": None, "max": None}

    def pick(percentile: float) -> float:
        index = min(len(ordered) - 1, int((len(ordered) - 1) * percentile))
        return round(float(ordered[index]), 3)

    return {
        "count": len(ordered),
        "p50": pick(0.50),
        "p95": pick(0.95),
        "p99": pick(0.99),
        "max": round(float(ordered[-1]), 3),
    }


def _replace_latest(target: Any, value: Any) -> int:
    replaced = 0
    try:
        while True:
            target.get_nowait()
            replaced += 1
    except queue.Empty:
        pass
    try:
        target.put_nowait(value)
    except queue.Full:
        pass
    return replaced


class _WorkerRecorderSink:
    """Recorder-compatible, non-blocking IPC sink used only inside the child."""

    def __init__(
        self,
        target: Any,
        drops: Any,
        paper_session_id: str,
        paper_rows: list[dict[str, Any]],
    ) -> None:
        self._target = target
        self._drops = drops
        self._paper_session_id = paper_session_id
        self._paper_rows = tuple(dict(row) for row in paper_rows)

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def submit(self, event_type: str, payload: Mapping[str, Any], key: str) -> bool:
        try:
            self._target.put_nowait((str(event_type), dict(payload), str(key)))
            return True
        except queue.Full:
            with self._drops.get_lock():
                self._drops.value += 1
            return False

    def read_paper_session(self, session_id: str) -> list[dict[str, Any]]:
        if session_id != self._paper_session_id:
            return []
        return [dict(row) for row in self._paper_rows]

    def health(self) -> dict[str, Any]:
        return {
            "status": "READY",
            "worker_alive": True,
            "queue_depth": None,
            "ipc_derived_drops": int(self._drops.value),
        }


def _isolated_flow_child(
    input_queue: Any,
    action_queue: Any,
    meter_queue: Any,
    snapshot_queue: Any,
    record_queue: Any,
    result_queue: Any,
    health_queue: Any,
    stop_event: Any,
    ready_event: Any,
    generation: int,
    processed: Any,
    last_processed_sequence: Any,
    required_drops: Any,
    action_drops: Any,
    meter_coalesces: Any,
    snapshot_coalesces: Any,
    record_drops: Any,
    initial_controls: list[tuple[str, dict[str, Any]]],
    paper_session_id: str,
    paper_rows: list[dict[str, Any]],
) -> None:
    recorder = _WorkerRecorderSink(record_queue, record_drops, paper_session_id, paper_rows)
    service = OrderFlowService(recorder=recorder)
    queue_ages: deque[float] = deque(maxlen=20_000)
    compute_ms: deque[float] = deque(maxlen=20_000)
    publish_ms: deque[float] = deque(maxlen=20_000)
    ingress_times: deque[int] = deque(maxlen=20_000)
    processed_times: deque[int] = deque(maxlen=20_000)
    metrics_lock = threading.Lock()
    metrics_cache_lock = threading.Lock()
    metrics_stop = threading.Event()
    empty_distribution = _distribution(())
    metrics_cache: dict[str, Any] = {
        "queue_age": empty_distribution,
        "compute": empty_distribution,
        "feature_publish": empty_distribution,
        "input_rate": 0.0,
        "processing_rate": 0.0,
        "refresh_count": 0,
        "refresh_ms": None,
        "published_ns": 0,
        "last_error": None,
    }
    last_packet_source_ns = 0
    last_output_ns = 0
    last_health_ns = 0
    last_snapshot_ns = 0
    last_error: str | None = None

    def publish_flow(kind: str, payload: Mapping[str, Any]) -> None:
        nonlocal last_output_ns
        started = time.perf_counter_ns()
        value = (str(kind), dict(payload), started)
        if kind == "FLOW_PULSE_ACTION":
            try:
                action_queue.put_nowait(value)
            except queue.Full:
                with action_drops.get_lock():
                    action_drops.value += 1
        else:
            replaced = _replace_latest(meter_queue, value)
            if replaced:
                with meter_coalesces.get_lock():
                    meter_coalesces.value += replaced
        last_output_ns = time.perf_counter_ns()
        with metrics_lock:
            publish_ms.append(max(0.0, (last_output_ns - started) / 1_000_000.0))

    service.subscribe_flow_pulse(publish_flow)

    def telemetry_loop() -> None:
        refresh_count = 0
        while not metrics_stop.wait(1.0):
            refresh_started = time.perf_counter_ns()
            try:
                with metrics_lock:
                    queue_values = tuple(queue_ages)
                    compute_values = tuple(compute_ms)
                    publish_values = tuple(publish_ms)
                    ingress_values = tuple(ingress_times)
                    processed_values = tuple(processed_times)
                now = time.perf_counter_ns()
                cutoff = now - 10_000_000_000
                refresh_count += 1
                value = {
                    "queue_age": _distribution(queue_values),
                    "compute": _distribution(compute_values),
                    "feature_publish": _distribution(publish_values),
                    "input_rate": round(
                        sum(item >= cutoff for item in ingress_values) / 10.0, 3
                    ),
                    "processing_rate": round(
                        sum(item >= cutoff for item in processed_values) / 10.0, 3
                    ),
                    "refresh_count": refresh_count,
                    "refresh_ms": round(
                        max(0.0, (time.perf_counter_ns() - refresh_started) / 1_000_000.0),
                        3,
                    ),
                    "published_ns": time.perf_counter_ns(),
                    "last_error": None,
                }
            except Exception as error:
                with metrics_cache_lock:
                    value = {
                        **metrics_cache,
                        "last_error": f"{type(error).__name__}:{error}",
                    }
            with metrics_cache_lock:
                metrics_cache.clear()
                metrics_cache.update(value)

    telemetry_thread = threading.Thread(
        target=telemetry_loop,
        name="flow-worker-telemetry",
        daemon=True,
    )

    def apply_control(command: str, payload: Mapping[str, Any]) -> Any:
        if command == "REGISTER_INSTRUMENTS":
            identities = tuple(InstrumentIdentity(**dict(item)) for item in payload.get("identities", ()))
            service.register_instruments(identities)
            return len(identities)
        if command == "REGISTER_OPTION_DELTA":
            service.register_option_delta(
                str(payload["security_id"]),
                float(payload["delta"]),
                receive_ns=int(payload["receive_ns"]),
            )
            return True
        if command == "REGISTER_DECISION_STRUCTURE":
            service.register_decision_structure(
                dict(payload.get("projection") or {}), receive_ns=int(payload["receive_ns"])
            )
            return True
        if command == "REGISTER_REFERENCE_LEVELS":
            service.register_futures_reference_levels(**dict(payload))
            return True
        if command == "REGISTER_OPENING_RANGE":
            service.register_futures_opening_range(**dict(payload))
            return True
        if command == "BEGIN_RECOVERY":
            service.begin_recovery()
            return True
        if command == "RESTORE_JOURNAL":
            return service.restore_flow_pulse_journal(
                Path(str(payload["journal_path"])),
                checkpoint_path=Path(str(payload["checkpoint_path"])),
                cutoff_bytes=payload.get("cutoff_bytes"),
                checkpoint_identity=dict(payload.get("checkpoint_identity") or {}),
            )
        raise ValueError(f"UNKNOWN_FLOW_CONTROL:{command}")

    try:
        for command, payload in initial_controls:
            apply_control(command, payload)
        service.start()
        telemetry_thread.start()
        ready_event.set()
        while not stop_event.is_set():
            now_ns = time.perf_counter_ns()
            try:
                envelope = input_queue.get(timeout=0.05)
            except queue.Empty:
                envelope = None
            if envelope is not None:
                kind, sequence, queued_ns, command, payload, request_id = envelope
                if kind == "STOP":
                    break
                if kind == "CONTROL":
                    try:
                        result = apply_control(str(command), dict(payload or {}))
                        if request_id:
                            result_queue.put((request_id, True, result), timeout=1.0)
                    except Exception as error:
                        last_error = f"{type(error).__name__}:{error}"
                        if request_id:
                            result_queue.put((request_id, False, last_error), timeout=1.0)
                    continue

                started_ns = time.perf_counter_ns()
                with metrics_lock:
                    ingress_times.append(started_ns)
                    queue_ages.append(
                        max(0.0, (started_ns - int(queued_ns)) / 1_000_000.0)
                    )
                tick = dict(payload or {})
                last_packet_source_ns = int(tick.get("feed_receive_ns") or started_ns)
                try:
                    service.ingest_tick(tick)
                except Exception as error:
                    last_error = f"{type(error).__name__}:{error}"
                completed_ns = time.perf_counter_ns()
                with metrics_lock:
                    compute_ms.append(
                        max(0.0, (completed_ns - started_ns) / 1_000_000.0)
                    )
                    processed_times.append(completed_ns)
                with processed.get_lock():
                    processed.value += 1
                with last_processed_sequence.get_lock():
                    last_processed_sequence.value = int(sequence)
                last_snapshot_ns = 0

            now_ns = time.perf_counter_ns()
            if now_ns - last_snapshot_ns >= 100_000_000:
                projection = service.latest_projection()
                snapshot = {
                    "projection": projection,
                    "decision_hud": service.latest_decision_hud(),
                    "service_telemetry": service.telemetry(),
                    "published_ns": now_ns,
                }
                replaced = _replace_latest(snapshot_queue, snapshot)
                if replaced:
                    with snapshot_coalesces.get_lock():
                        snapshot_coalesces.value += replaced
                last_output_ns = now_ns
                last_snapshot_ns = now_ns

            if now_ns - last_health_ns >= 250_000_000:
                with metrics_cache_lock:
                    cached_metrics = dict(metrics_cache)
                queue_age = dict(cached_metrics["queue_age"])
                compute = dict(cached_metrics["compute"])
                feature_publish = dict(cached_metrics["feature_publish"])
                metrics_published_ns = int(cached_metrics.get("published_ns") or 0)
                health = {
                    "FLOW_WORKER_ALIVE": True,
                    "FLOW_WORKER_PID": __import__("os").getpid(),
                    "FLOW_WORKER_GENERATION": generation,
                    "FLOW_INPUT_PROCESSED": int(processed.value),
                    "FLOW_REQUIRED_DROPS": int(required_drops.value) + int(action_drops.value),
                    "FLOW_INPUT_RATE": cached_metrics["input_rate"],
                    "FLOW_PROCESSING_RATE": cached_metrics["processing_rate"],
                    "FLOW_QUEUE_AGE_MS": queue_age,
                    "FLOW_QUEUE_AGE_P50": queue_age["p50"],
                    "FLOW_QUEUE_AGE_P95": queue_age["p95"],
                    "FLOW_QUEUE_AGE_P99": queue_age["p99"],
                    "FLOW_QUEUE_AGE_MAX": queue_age["max"],
                    "FLOW_COMPUTE_MS": compute,
                    "FLOW_COMPUTE_P50": compute["p50"],
                    "FLOW_COMPUTE_P95": compute["p95"],
                    "FLOW_COMPUTE_P99": compute["p99"],
                    "FLOW_FEATURE_PUBLISH_MS": feature_publish,
                    "FLOW_FEATURE_PUBLISH_P50": feature_publish["p50"],
                    "FLOW_FEATURE_PUBLISH_P95": feature_publish["p95"],
                    "FLOW_FEATURE_PUBLISH_P99": feature_publish["p99"],
                    "FLOW_TELEMETRY_MODE": "ASYNC_CACHED_EXACT",
                    "FLOW_TELEMETRY_THREAD_ALIVE": telemetry_thread.is_alive(),
                    "FLOW_TELEMETRY_REFRESH_COUNT": cached_metrics["refresh_count"],
                    "FLOW_TELEMETRY_REFRESH_MS": cached_metrics["refresh_ms"],
                    "FLOW_TELEMETRY_CACHE_AGE_MS": (
                        round(
                            max(0.0, (now_ns - metrics_published_ns) / 1_000_000.0),
                            3,
                        )
                        if metrics_published_ns else None
                    ),
                    "FLOW_TELEMETRY_LAST_ERROR": cached_metrics["last_error"],
                    "FLOW_METER_COALESCES": int(meter_coalesces.value),
                    "FLOW_SNAPSHOT_COALESCES": int(snapshot_coalesces.value),
                    "FLOW_ACTION_DROPS": int(action_drops.value),
                    "FLOW_RECORDER_IPC_DROPS": int(record_drops.value),
                    "FLOW_LAST_PACKET_SOURCE_AGE_MS": (
                        round(max(0.0, (now_ns - last_packet_source_ns) / 1_000_000.0), 3)
                        if last_packet_source_ns else None
                    ),
                    "FLOW_LAST_OUTPUT_AGE_MS": (
                        round(max(0.0, (now_ns - last_output_ns) / 1_000_000.0), 3)
                        if last_output_ns else None
                    ),
                    "FLOW_WORKER_LAST_ERROR": last_error,
                    "execution_influence": "ZERO",
                }
                _replace_latest(health_queue, health)
                last_health_ns = now_ns
    except BaseException as error:
        last_error = f"{type(error).__name__}:{error}"
        _replace_latest(
            health_queue,
            {
                "FLOW_WORKER_ALIVE": False,
                "FLOW_WORKER_PID": __import__("os").getpid(),
                "FLOW_WORKER_GENERATION": generation,
                "FLOW_WORKER_LAST_ERROR": last_error,
                "execution_influence": "ZERO",
            },
        )
        raise
    finally:
        ready_event.clear()
        metrics_stop.set()
        if telemetry_thread.is_alive():
            telemetry_thread.join(timeout=2.0)
        service.stop()


class IsolatedOrderFlowWorker:
    """Parent-side proxy for the child-owned canonical OrderFlowService."""

    def __init__(self, *, recorder: Any, queue_size: int = 16_384) -> None:
        self.recorder = recorder
        self.execution_influence = "ZERO"
        self._ctx = mp.get_context("spawn")
        capacity = min(32_760, max(2_048, int(queue_size)))
        self._input = self._ctx.Queue(maxsize=capacity)
        self._actions = self._ctx.Queue(maxsize=4_096)
        self._meters = self._ctx.Queue(maxsize=1)
        self._snapshots = self._ctx.Queue(maxsize=1)
        self._records = self._ctx.Queue(maxsize=capacity)
        self._results = self._ctx.Queue(maxsize=16)
        self._health_samples = self._ctx.Queue(maxsize=1)
        self._ipc_state, ipc_slots = shared_int_slots(self._ctx, 9)
        (
            self._processed,
            self._last_processed_sequence,
            self._required_drops,
            self._action_drops,
            self._meter_coalesces,
            self._snapshot_coalesces,
            self._record_drops,
            _stop_slot,
            _ready_slot,
        ) = ipc_slots
        self._stop_event = SharedFlag(self._ipc_state, 7)
        self._ready_event = SharedFlag(self._ipc_state, 8)
        self._process: mp.Process | None = None
        self._generation = 0
        self._sequence = 0
        self._sequence_lock = threading.Lock()
        self._outstanding: deque[tuple[int, int]] = deque()
        self._outstanding_lock = threading.Lock()
        self._listeners: list[Callable[[str, Mapping[str, Any]], None]] = []
        self._listeners_lock = threading.RLock()
        self._controls: dict[str, tuple[str, dict[str, Any]]] = {}
        self._projection: dict[str, Any] | None = None
        self._decision_hud: dict[str, Any] = {"status": "UNAVAILABLE", "reason": "FLOW_WORKER_NOT_READY"}
        self._service_telemetry: dict[str, Any] = {}
        self._health: dict[str, Any] = {
            "FLOW_WORKER_ALIVE": False,
            "FLOW_WORKER_PID": None,
            "FLOW_WORKER_GENERATION": 0,
            "FLOW_REQUIRED_DROPS": 0,
            "execution_influence": "ZERO",
        }
        self._state_lock = threading.RLock()
        self._parent_stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._input_times: deque[int] = deque(maxlen=20_000)
        self._output_ages: deque[float] = deque(maxlen=20_000)
        self._metrics_lock = threading.Lock()
        self._parent_action_failures = 0
        self._recorder_submit_failures = 0

    def start(self) -> None:
        if self.worker_alive:
            return
        self.recorder.start()
        session_id = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
        try:
            paper_rows = self.recorder.read_paper_session(session_id)
        except Exception:
            paper_rows = []
        self._generation += 1
        self._parent_stop.clear()
        self._stop_event.clear()
        self._ready_event.clear()
        self._process = self._ctx.Process(
            target=_isolated_flow_child,
            args=(
                self._input, self._actions, self._meters, self._snapshots, self._records,
                self._results, self._health_samples, self._stop_event, self._ready_event,
                self._generation, self._processed, self._last_processed_sequence,
                self._required_drops, self._action_drops, self._meter_coalesces,
                self._snapshot_coalesces, self._record_drops, self._control_payloads(),
                session_id, paper_rows,
            ),
            name="oracle-order-flow-worker",
            daemon=True,
        )
        self._process.start()
        self._start_dispatchers()
        if not self._ready_event.wait(timeout=8.0):
            raise RuntimeError("FLOW_WORKER_START_TIMEOUT")

    def stop(self) -> None:
        try:
            # STOP is ordered behind every accepted packet/control message.
            # A normal shutdown therefore drains the lossless input lane.
            self._input.put(("STOP", 0, 0, None, None, None), timeout=1.0)
        except queue.Full:
            self._stop_event.set()
        process = self._process
        if process is not None and process.is_alive():
            process.join(timeout=4.0)
            if process.is_alive():
                self._stop_event.set()
                process.terminate()
                process.join(timeout=2.0)
        # Let independent parent dispatchers consume the child's final
        # snapshot/evidence publications before stopping the recorder.
        time.sleep(0.05)
        self._parent_stop.set()
        for thread in self._threads:
            if thread is not threading.current_thread():
                thread.join(timeout=1.0)
        self.recorder.stop()

    @property
    def worker_alive(self) -> bool:
        return bool(self._process is not None and self._process.is_alive() and self._ready_event.is_set())

    def _start_dispatchers(self) -> None:
        self._threads = []
        for name, target in (
            ("actions", self._dispatch_actions),
            ("meters", self._dispatch_meters),
            ("snapshots", self._dispatch_snapshots),
            ("records", self._dispatch_records),
        ):
            thread = threading.Thread(target=target, name=f"oracle-flow-parent-{name}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def _dispatch_actions(self) -> None:
        self._dispatch_publications(self._actions)

    def _dispatch_meters(self) -> None:
        self._dispatch_publications(self._meters)

    def _dispatch_publications(self, source: Any) -> None:
        while not self._parent_stop.is_set():
            try:
                kind, payload, published_ns = source.get(timeout=0.1)
            except queue.Empty:
                continue
            with self._metrics_lock:
                self._output_ages.append(
                    max(0.0, (time.perf_counter_ns() - int(published_ns)) / 1_000_000.0)
                )
            with self._listeners_lock:
                listeners = tuple(self._listeners)
            for listener in listeners:
                try:
                    listener(str(kind), dict(payload))
                except Exception:
                    self._parent_action_failures += 1

    def _dispatch_snapshots(self) -> None:
        while not self._parent_stop.is_set():
            try:
                snapshot = self._snapshots.get(timeout=0.1)
            except queue.Empty:
                continue
            with self._state_lock:
                self._projection = dict(snapshot.get("projection") or {})
                self._decision_hud = dict(snapshot.get("decision_hud") or {})
                self._service_telemetry = dict(snapshot.get("service_telemetry") or {})

    def _dispatch_records(self) -> None:
        while not self._parent_stop.is_set():
            try:
                event_type, payload, key = self._records.get(timeout=0.1)
            except queue.Empty:
                continue
            if not self.recorder.submit(str(event_type), dict(payload), str(key)):
                self._recorder_submit_failures += 1

    def ingest_tick(self, tick: Mapping[str, Any]) -> bool:
        queued_ns = time.perf_counter_ns()
        with self._sequence_lock:
            self._sequence += 1
            sequence = self._sequence
        envelope = ("PACKET", sequence, queued_ns, None, dict(tick), None)
        try:
            self._input.put_nowait(envelope)
        except queue.Full:
            with self._required_drops.get_lock():
                self._required_drops.value += 1
            return False
        with self._metrics_lock:
            self._input_times.append(queued_ns)
        with self._outstanding_lock:
            self._outstanding.append((sequence, queued_ns))
        return True

    def _send_control(self, command: str, payload: Mapping[str, Any], *, wait: bool = False) -> Any:
        if not self.worker_alive:
            if wait:
                raise RuntimeError("FLOW_WORKER_NOT_READY")
            return False
        request_id = uuid.uuid4().hex if wait else None
        envelope = ("CONTROL", 0, time.perf_counter_ns(), command, dict(payload), request_id)
        self._input.put(envelope, timeout=1.0)
        if not wait:
            return True
        deadline = time.monotonic() + 120.0
        deferred: list[tuple[Any, ...]] = []
        try:
            while time.monotonic() < deadline:
                try:
                    result = self._results.get(timeout=min(0.5, deadline - time.monotonic()))
                except queue.Empty:
                    continue
                if result[0] != request_id:
                    deferred.append(result)
                    continue
                if not result[1]:
                    raise RuntimeError(str(result[2]))
                return result[2]
            raise TimeoutError(f"FLOW_WORKER_CONTROL_TIMEOUT:{command}")
        finally:
            for item in deferred:
                self._results.put_nowait(item)

    def _cache_control(self, key: str, command: str, payload: Mapping[str, Any]) -> None:
        with self._state_lock:
            self._controls[key] = (command, dict(payload))
        if self.worker_alive:
            self._send_control(command, payload)

    def _control_payloads(self) -> list[tuple[str, dict[str, Any]]]:
        with self._state_lock:
            values = list(self._controls.values())
        return [(str(command), dict(payload)) for command, payload in values]

    def register_instruments(self, identities: tuple[InstrumentIdentity, ...]) -> None:
        payload = {"identities": [
            {
                "exchange_segment": item.exchange_segment,
                "security_id": item.security_id,
                "role": item.role,
                "expiry": item.expiry,
                "strike": item.strike,
                "option_type": item.option_type,
            }
            for item in identities
        ]}
        self._cache_control("INSTRUMENTS", "REGISTER_INSTRUMENTS", payload)

    def register_option_delta(self, security_id: str, delta: float, *, receive_ns: int) -> None:
        self._cache_control(
            f"DELTA:{security_id}", "REGISTER_OPTION_DELTA",
            {"security_id": security_id, "delta": delta, "receive_ns": receive_ns},
        )

    def register_decision_structure(self, projection: Mapping[str, Any], *, receive_ns: int) -> None:
        self._cache_control(
            "DECISION_STRUCTURE", "REGISTER_DECISION_STRUCTURE",
            {"projection": dict(projection), "receive_ns": receive_ns},
        )

    def register_futures_reference_levels(self, **payload: Any) -> None:
        self._cache_control("REFERENCE_LEVELS", "REGISTER_REFERENCE_LEVELS", payload)

    def register_futures_opening_range(self, **payload: Any) -> None:
        self._cache_control("OPENING_RANGE", "REGISTER_OPENING_RANGE", payload)

    def begin_recovery(self) -> None:
        self._send_control("BEGIN_RECOVERY", {})

    def restore_flow_pulse_journal(
        self,
        journal_path: Path,
        *,
        checkpoint_path: Path,
        cutoff_bytes: int | None = None,
        checkpoint_identity: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self._send_control(
            "RESTORE_JOURNAL",
            {
                "journal_path": str(journal_path),
                "checkpoint_path": str(checkpoint_path),
                "cutoff_bytes": cutoff_bytes,
                "checkpoint_identity": dict(checkpoint_identity or {}),
            },
            wait=True,
        )
        return dict(result or {})

    def subscribe_flow_pulse(
        self, listener: Callable[[str, Mapping[str, Any]], None]
    ) -> Callable[[], None]:
        with self._listeners_lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._listeners_lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def _load_visual_history(self) -> dict[str, Any]:
        session_id = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
        candidate_roots = [
            Path(os.environ.get("CITADEL_STATE_ROOT", "/Users/ayushmudgal/Developer/CitadelOS/logs")) / "order_flow" / "evidence",
            Path("/Users/ayushmudgal/Developer/CitadelOS-Oracle-Post-E9/logs/order_flow/evidence"),
        ]
        if self.recorder and hasattr(self.recorder, "root"):
            candidate_roots.insert(0, Path(self.recorder.root))
        for root in candidate_roots:
            cache_path = root / f"flow_map_visual_history_{session_id}.json"
            if cache_path.exists():
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
        return {}

    def latest_projection(self) -> dict[str, Any]:
        with self._state_lock:
            if self._projection is None:
                vis = self._load_visual_history()
                events = vis.get("visual_events", [])
                has_history = len(events) > 0
                return {
                    "status": "AVAILABLE" if has_history else "UNAVAILABLE",
                    "reason": "RECORDED_SESSION_HISTORY_HYDRATED" if has_history else "ORDER_FLOW_PROJECTION_NOT_READY",
                    "execution_influence": "ZERO",
                    "authority_20_depth": "DISABLED",
                    "visual_events": events,
                    "depth_snapshots": vis.get("depth_snapshots", []),
                    "cvd_series": vis.get("cvd_series", []),
                    "cvd": vis.get("cvd", 0),
                }
            value = dict(self._projection)
            if not value.get("visual_events"):
                vis = self._load_visual_history()
                if vis:
                    value["visual_events"] = vis.get("visual_events", [])
                    value["depth_snapshots"] = vis.get("depth_snapshots", [])
                    value["cvd_series"] = vis.get("cvd_series", [])
                    value["cvd"] = vis.get("cvd", 0)
        if not self.worker_alive:
            value["projection_state"] = "LAST_GOOD"
            value["action_eligible"] = False
            locks = set(value.get("action_lock_reasons") or ())
            locks.add("FLOW_WORKER_UNAVAILABLE")
            value["action_lock_reasons"] = sorted(locks)
        return value

    def latest_decision_hud(self) -> dict[str, Any]:
        with self._state_lock:
            return dict(self._decision_hud)

    def _drain_health(self) -> None:
        latest = None
        try:
            while True:
                latest = self._health_samples.get_nowait()
        except queue.Empty:
            pass
        if latest is not None:
            with self._state_lock:
                self._health = dict(latest)

    def health(self) -> dict[str, Any]:
        self._drain_health()
        now_ns = time.perf_counter_ns()
        last_processed = int(self._last_processed_sequence.value)
        with self._outstanding_lock:
            while self._outstanding and self._outstanding[0][0] <= last_processed:
                self._outstanding.popleft()
            debt = len(self._outstanding)
            oldest_age_ms = (
                max(0.0, (now_ns - self._outstanding[0][1]) / 1_000_000.0)
                if self._outstanding else 0.0
            )
        cutoff = now_ns - 10_000_000_000
        with self._state_lock:
            value = dict(self._health)
        # The two publication dispatchers and the Dhan dispatch thread append
        # concurrently with health probes.  Snapshot under one telemetry-only
        # lock so a readiness request can never fail with ``deque mutated``.
        with self._metrics_lock:
            input_times = tuple(self._input_times)
            output_ages = tuple(self._output_ages)
        output_age = _distribution(output_ages)
        value.update({
            "FLOW_WORKER_ALIVE": self.worker_alive,
            "FLOW_WORKER_PID": self._process.pid if self.worker_alive and self._process else None,
            "FLOW_WORKER_GENERATION": self._generation,
            "FLOW_INPUT_RECEIVED": self._sequence,
            "FLOW_INPUT_PROCESSED": int(self._processed.value),
            "FLOW_REQUIRED_DROPS": int(self._required_drops.value) + int(self._action_drops.value),
            "FLOW_INPUT_RATE": round(sum(item >= cutoff for item in input_times) / 10.0, 3),
            "FLOW_PROCESSING_DEBT": debt,
            "FLOW_ACTION_QUEUE_AGE_MS": output_age,
            "FLOW_ACTION_QUEUE_AGE": output_age["max"],
            "FLOW_OUTPUT_AGE_MS": output_age,
            "FLOW_OLDEST_UNPROCESSED_AGE_MS": round(oldest_age_ms, 3),
            "FLOW_METER_COALESCES": int(self._meter_coalesces.value),
            "FLOW_ACTION_DROPS": int(self._action_drops.value),
            "FLOW_RECORDER_IPC_DROPS": int(self._record_drops.value),
            "FLOW_RECORDER_SUBMIT_FAILURES": self._recorder_submit_failures,
            "FLOW_PARENT_PUBLICATION_FAILURES": self._parent_action_failures,
            "execution_influence": "ZERO",
        })
        return value

    def telemetry(self) -> dict[str, Any]:
        with self._state_lock:
            service = dict(self._service_telemetry)
        return {
            **service,
            "dedicated_worker": self.health(),
            "recorder": self.recorder.health(),
            "execution_influence": "ZERO",
        }
