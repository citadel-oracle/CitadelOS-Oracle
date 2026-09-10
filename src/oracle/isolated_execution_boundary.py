"""Small process boundaries for Oracle CPU-heavy analytical domains.

The parent owns transport and cache publication only. The child owns the
stateful calculation callback. Input is ordered and lossless; output is a
latest-state lane because obsolete presentation snapshots have no event
semantics. Required events remain persisted by their owning engines.

R3 EXTENSION: Resilient child worker supervision, authoritative lifecycle
telemetry, crash-loop bounding, separated CURRENT vs LAST_GOOD, and
automatic in-memory rehydration.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import queue
import threading
import time
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping


class WorkerState(str, Enum):
    """Authoritative lifecycle states for isolated child workers."""
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    HEALTHY = "HEALTHY"
    AGING = "AGING"
    STALE = "STALE"
    FAILED = "FAILED"
    RESTARTING = "RESTARTING"
    REHYDRATING = "REHYDRATING"
    CRASH_LOOP = "CRASH_LOOP"


class IsolatedExecutionBoundary:
    """One explicitly-owned child process with ordered input/latest output and supervision."""

    def __init__(
        self,
        *,
        name: str,
        processor: Callable[[str, Any], Any],
        snapshotter: Callable[[], Any] | None = None,
        on_start: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        on_snapshot: Callable[[Any], None] | None = None,
        input_capacity: int = 512,
        publish_interval_seconds: float = 0.5,
        context_name: str | None = None,
        max_restarts_per_minute: int = 5,
        enable_supervision: bool = True,
        max_stale_seconds: float = 5.0,
    ) -> None:
        self.name = str(name)
        self.processor = processor
        self.snapshotter = snapshotter
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_snapshot = on_snapshot
        self.input_capacity = max(8, int(input_capacity))
        self.publish_interval_seconds = max(0.05, float(publish_interval_seconds))
        self.max_restarts_per_minute = max(1, int(max_restarts_per_minute))
        self.enable_supervision = bool(enable_supervision)
        self.max_stale_seconds = max(1.0, float(max_stale_seconds))

        self.context_name = context_name or ("fork" if "fork" in mp.get_all_start_methods() else "spawn")
        self._context = mp.get_context(self.context_name)
        self._input = None
        self._output = None
        self._stop = None
        self._process = None
        self._listener_stop = threading.Event()
        self._listener = None
        self._supervisor_stop = threading.Event()
        self._supervisor = None
        self._lock = threading.RLock()

        # Telemetry & State
        self._state = WorkerState.STOPPED
        self._current: Any = None
        self._last_good: Any = None
        self._last_good_monotonic: float | None = None
        self._last_good_timestamp: str | None = None
        self._started_at: float | None = None
        self._generation = 0
        self._submitted = 0
        self._received = 0
        self._processed = 0
        self._required_drops = 0
        self._snapshot_coalesces = 0
        self._last_error: str | None = None
        self._last_output_monotonic: float | None = None
        self._last_input_monotonic: float | None = None
        self._last_heartbeat_at: str | None = None
        self._last_output_at: str | None = None
        self._exit_code: int | None = None
        self._latest_telemetry: dict[str, Any] = {}
        self._restart_count = 0
        self._restart_history = deque(maxlen=64)
        self._coalesces_shared = self._context.Value("Q", 0)
        self._processed_shared = self._context.Value("Q", 0)

    def start(self, *, start_listener: bool = True, is_restart: bool = False) -> bool:
        with self._lock:
            if self._process is not None and self._process.is_alive():
                return False
            self._input = self._context.Queue(maxsize=self.input_capacity)
            self._output = self._context.Queue(maxsize=1)
            self._stop = self._context.Event()
            self._generation += 1
            self._listener_stop.clear()
            self._supervisor_stop.clear()
            self._exit_code = None
            self._state = WorkerState.REHYDRATING if is_restart else WorkerState.STARTING
            self._process = self._context.Process(
                target=self._child_main,
                args=(os.getpid(),),
                name=self.name,
                daemon=True,
            )
            self._process.start()
            self._started_at = time.time()
            self._last_heartbeat_at = datetime.now(timezone.utc).isoformat()

        if start_listener:
            self.start_listener()

        if self.enable_supervision:
            self.start_supervisor()

        return True

    def start_listener(self) -> bool:
        with self._lock:
            if self._process is None or not self._process.is_alive():
                return False
            if self._listener is not None and self._listener.is_alive():
                return False
            self._listener_stop.clear()
            self._listener = threading.Thread(
                target=self._listen,
                name=f"{self.name}-snapshot-listener",
                daemon=True,
            )
            self._listener.start()
            return True

    def start_supervisor(self) -> bool:
        with self._lock:
            if self._supervisor is not None and self._supervisor.is_alive():
                return False
            self._supervisor_stop.clear()
            self._supervisor = threading.Thread(
                target=self._supervise,
                name=f"{self.name}-resilience-supervisor",
                daemon=True,
            )
            self._supervisor.start()
            return True

    def submit(self, kind: str, payload: Any, *, timeout: float = 5.0) -> bool:
        with self._lock:
            process = self._process
            input_queue = self._input
        if process is None or not process.is_alive() or input_queue is None:
            self._check_liveness()
            self._last_error = "WORKER_NOT_ALIVE"
            return False
        sequence = self._submitted + 1
        now_mono = time.monotonic()
        envelope = {
            "sequence": sequence,
            "submitted_monotonic": now_mono,
            "kind": str(kind),
            "payload": payload,
        }
        try:
            input_queue.put(envelope, block=True, timeout=max(0.01, float(timeout)))
        except queue.Full:
            with self._lock:
                self._required_drops += 1
                self._last_error = "INPUT_QUEUE_FULL"
            return False
        with self._lock:
            self._submitted = sequence
            self._last_input_monotonic = now_mono
        return True

    def current(self) -> Any:
        """Returns active fresh analytical output, or None if degraded/dead."""
        with self._lock:
            self._check_liveness()
            if self.is_healthy() or self.is_fresh():
                return deepcopy(self._current)
            return None

    def last_good(self) -> Any:
        """Returns the last known good calculation for diagnostic inspection."""
        with self._lock:
            return deepcopy(self._last_good)

    def latest(self) -> Any:
        """Compatibility latest-state accessor."""
        with self._lock:
            curr = self.current()
            if curr is not None:
                return curr
            return self.last_good()

    def is_healthy(self) -> bool:
        with self._lock:
            return bool(
                self._state == WorkerState.HEALTHY
                and self._process is not None
                and self._process.is_alive()
            )

    def is_fresh(self, max_age_seconds: float | None = None) -> bool:
        with self._lock:
            threshold = float(max_age_seconds or self.max_stale_seconds)
            if self._process is None or not self._process.is_alive():
                return False
            if self._last_output_monotonic is None:
                return False
            return (time.monotonic() - self._last_output_monotonic) <= threshold

    def mark_rehydrating(self) -> None:
        with self._lock:
            self._state = WorkerState.REHYDRATING
            self._current = None

    def restart(self, force: bool = False) -> bool:
        """Rate-limited bounded restart ensuring exactly one child process."""
        with self._lock:
            now = time.monotonic()
            recent = [t for t in self._restart_history if now - t < 60.0]
            if not force and len(recent) >= self.max_restarts_per_minute:
                self._state = WorkerState.CRASH_LOOP
                self._last_error = "CRASH_LOOP_LIMIT_EXCEEDED"
                self._current = None
                return False

            self._restart_history.append(now)
            self._restart_count += 1
            self._state = WorkerState.RESTARTING

        self.stop(timeout=1.0, preserve_history=True)
        return self.start(is_restart=True)

    def stop(self, *, timeout: float = 10.0, preserve_history: bool = False) -> None:
        self._supervisor_stop.set()
        supervisor = self._supervisor
        if supervisor is not None and supervisor.is_alive() and supervisor is not threading.current_thread():
            supervisor.join(timeout=1.0)

        with self._lock:
            process = self._process
            stop_event = self._stop
            input_queue = self._input
        if stop_event is not None:
            stop_event.set()
        if input_queue is not None:
            try:
                input_queue.put_nowait(None)
            except (queue.Full, ValueError, OSError):
                pass
        if process is not None:
            process.join(timeout=max(0.1, float(timeout)))
            if process.is_alive():
                process.terminate()
                process.join(timeout=1.0)
                if process.is_alive():
                    try:
                        os.kill(process.pid, 9)
                    except OSError:
                        pass
        self._listener_stop.set()
        listener = self._listener
        if listener is not None and listener.is_alive() and listener is not threading.current_thread():
            listener.join(timeout=1.0)
        for channel in (self._input, self._output):
            if channel is not None:
                try:
                    channel.close()
                    channel.join_thread()
                except (ValueError, OSError):
                    pass
        with self._lock:
            self._process = None
            self._input = None
            self._output = None
            self._stop = None
            if not preserve_history:
                self._state = WorkerState.STOPPED
                self._current = None

    def _check_liveness(self) -> bool:
        """Inspects OS process table and updates state on child failure."""
        with self._lock:
            process = self._process
            if process is not None and not process.is_alive():
                self._exit_code = process.exitcode
                if self._state not in (WorkerState.RESTARTING, WorkerState.CRASH_LOOP):
                    self._state = WorkerState.FAILED
                self._last_error = f"EXIT_CODE_{self._exit_code}" if self._exit_code is not None else "WORKER_TERMINATED"
                self._current = None
                return False
            return bool(process is not None and process.is_alive())

    def _supervise(self) -> None:
        """Active watchdog monitoring liveness, freshness, and triggering auto-recovery."""
        while not self._supervisor_stop.is_set():
            time.sleep(0.20)
            with self._lock:
                alive = self._check_liveness()
                state = self._state
                output_age = (
                    time.monotonic() - self._last_output_monotonic
                    if self._last_output_monotonic is not None
                    else None
                )

            # 1. Process Death Recovery
            if not alive and state not in (WorkerState.STOPPED, WorkerState.RESTARTING, WorkerState.CRASH_LOOP):
                self.restart()
                continue

            # 2. Freshness degradation
            if alive and output_age is not None:
                with self._lock:
                    if output_age > self.max_stale_seconds and self._state == WorkerState.HEALTHY:
                        self._state = WorkerState.STALE
                        self._current = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._check_liveness()
            process = self._process
            output_age = (
                max(0.0, time.monotonic() - self._last_output_monotonic)
                if self._last_output_monotonic is not None
                else None
            )
            if output_age is not None and output_age > self.max_stale_seconds and self._state == WorkerState.HEALTHY:
                self._state = WorkerState.STALE
                self._current = None
            return {
                "name": self.name,
                "alive": bool(process is not None and process.is_alive()),
                "pid": process.pid if process is not None else None,
                "state": self._state.value,
                "is_healthy": self.is_healthy(),
                "generation": self._generation,
                "submitted": self._submitted,
                "received": self._received,
                "processed": max(self._processed, int(self._processed_shared.value)),
                "processing_debt": max(0, self._submitted - max(self._processed, int(self._processed_shared.value))),
                "required_event_drops": self._required_drops,
                "snapshot_coalesces": self._snapshot_coalesces,
                "child_snapshot_coalesces": int(self._coalesces_shared.value),
                "last_output_age_seconds": round(output_age, 3) if output_age is not None else None,
                "last_error": self._last_error,
                "last_heartbeat_at": self._last_heartbeat_at,
                "last_output_at": self._last_output_at,
                "last_good_timestamp": self._last_good_timestamp,
                "exit_code": self._exit_code,
                "restart_count": self._restart_count,
                "crash_loop": bool(self._state == WorkerState.CRASH_LOOP),
                "started_at_epoch": self._started_at,
                "context": self.context_name,
                **deepcopy(self._latest_telemetry),
            }

    def _child_main(self, owner_pid: int) -> None:
        assert self._input is not None and self._output is not None and self._stop is not None
        owner_pid = int(owner_pid)

        def stop_if_owner_exits() -> None:
            while not self._stop.is_set():
                time.sleep(0.25)
                if os.getppid() != owner_pid:
                    os._exit(0)

        owner_watchdog = threading.Thread(
            target=stop_if_owner_exits,
            name=f"{self.name}-owner-watchdog",
            daemon=True,
        )
        owner_watchdog.start()
        last_publish = 0.0
        processed = 0
        started_at = time.monotonic()
        queue_age_ms = deque(maxlen=4096)
        compute_ms = deque(maxlen=4096)
        pending_result = None
        try:
            if callable(self.on_start):
                self.on_start()
            while not self._stop.is_set():
                envelope = None
                try:
                    envelope = self._input.get(timeout=min(0.25, self.publish_interval_seconds))
                except queue.Empty:
                    pass
                if envelope is None and self._stop.is_set():
                    break
                if isinstance(envelope, Mapping):
                    received_at = time.monotonic()
                    queue_age_ms.append(
                        max(0.0, received_at - float(envelope.get("submitted_monotonic") or received_at)) * 1000.0
                    )
                    compute_started = time.perf_counter()
                    result = self.processor(str(envelope["kind"]), envelope.get("payload"))
                    compute_ms.append((time.perf_counter() - compute_started) * 1000.0)
                    processed += 1
                    with self._processed_shared.get_lock():
                        self._processed_shared.value = processed
                    if result is not None:
                        pending_result = result
                now = time.monotonic()
                if pending_result is None and callable(self.snapshotter) and now - last_publish >= self.publish_interval_seconds:
                    pending_result = self.snapshotter()
                if pending_result is not None:
                    published = self._publish_child({
                        "pid": os.getpid(),
                        "processed": processed,
                        "published_monotonic": now,
                        "telemetry": {
                            "input_rate": round(processed / max(0.001, now - started_at), 3),
                            "processing_rate": round(processed / max(0.001, now - started_at), 3),
                            "queue_age_ms": self._percentiles(queue_age_ms),
                            "compute_ms": self._percentiles(compute_ms),
                        },
                        "payload": pending_result,
                    })
                    if published:
                        pending_result = None
                        last_publish = now
        except BaseException as error:
            try:
                self._publish_child({
                    "pid": os.getpid(),
                    "processed": processed,
                    "published_monotonic": time.monotonic(),
                    "error": f"{type(error).__name__}:{error}",
                })
            except Exception:
                pass
            raise
        finally:
            if callable(self.on_stop):
                self.on_stop()

    def _publish_child(self, message: Mapping[str, Any]) -> bool:
        assert self._output is not None
        try:
            self._output.put_nowait(dict(message))
            return True
        except queue.Full:
            with self._coalesces_shared.get_lock():
                self._coalesces_shared.value += 1
        try:
            self._output.get_nowait()
        except queue.Empty:
            pass
        try:
            self._output.put_nowait(dict(message))
            return True
        except queue.Full:
            return False

    def _listen(self) -> None:
        while not self._listener_stop.is_set():
            with self._lock:
                output = self._output
                process = self._process
            if output is None:
                return
            try:
                message = output.get(timeout=0.25)
            except queue.Empty:
                if process is not None and not process.is_alive():
                    self._check_liveness()
                    return
                continue
            except (EOFError, OSError, ValueError):
                self._check_liveness()
                return

            with self._lock:
                self._received += 1
                self._processed = max(self._processed, int(message.get("processed") or 0))
                now_utc = datetime.now(timezone.utc).isoformat()
                now_mono = time.monotonic()
                self._last_heartbeat_at = now_utc

                if message.get("error"):
                    self._last_error = str(message["error"])
                    self._state = WorkerState.FAILED
                    self._current = None
                    continue

                payload = message.get("payload")
                self._current = payload
                self._last_good = payload
                self._last_good_monotonic = now_mono
                self._last_good_timestamp = now_utc
                self._last_output_monotonic = now_mono
                self._last_output_at = now_utc
                self._latest_telemetry = deepcopy(message.get("telemetry") or {})

                if self._state in (WorkerState.STARTING, WorkerState.REHYDRATING, WorkerState.AGING, WorkerState.STALE):
                    self._state = WorkerState.HEALTHY

            if callable(self.on_snapshot):
                try:
                    self.on_snapshot(payload)
                except Exception as error:
                    with self._lock:
                        self._last_error = f"SNAPSHOT_CALLBACK:{type(error).__name__}:{error}"

    @staticmethod
    def _percentiles(values) -> dict[str, float | int]:
        ordered = sorted(float(value) for value in values)
        if not ordered:
            return {"count": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}

        def point(fraction: float) -> float:
            return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]

        return {
            "count": len(ordered),
            "p50": round(point(0.50), 3),
            "p95": round(point(0.95), 3),
            "p99": round(point(0.99), 3),
            "max": round(ordered[-1], 3),
        }
