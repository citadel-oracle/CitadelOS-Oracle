"""Bounded latest-state delivery for non-sequential Oracle consumers.

This lane is deliberately *not* a market-event queue.  It is used only after
the canonical Order Flow service has accepted a packet and produced a complete
projection.  Cosmetic meter revisions may replace an obsolete pending meter;
rare Flow Pulse action transitions retain FIFO ordering in their own bounded
queue.  Neither behaviour is used for market-data calculation.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from typing import Any, Callable, Mapping


def _distribution(values: deque[float]) -> dict[str, float | int | None]:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "p50": None, "p95": None, "p99": None, "max": None}

    def pick(percentile: float) -> float:
        return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * percentile))], 3)

    return {
        "count": len(ordered),
        "p50": pick(0.50),
        "p95": pick(0.95),
        "p99": pick(0.99),
        "max": round(ordered[-1], 3),
    }


class FlowPublicationLane:
    """Keep Fast Lane/Fusion work off the lossless Order Flow callback.

    ``FLOW_PULSE_ACTION`` carries an actual transition and therefore keeps its
    own FIFO lane.  ``FLOW_PULSE_METERS`` is a latest-state display update: a
    newer meter fully supersedes an older pending meter and is counted as a
    coalesce rather than a drop.
    """

    def __init__(
        self,
        callback: Callable[[str, Mapping[str, Any]], None],
        *,
        action_capacity: int = 256,
    ) -> None:
        self._callback = callback
        self._actions: queue.Queue[tuple[str, dict[str, Any], int]] = queue.Queue(
            maxsize=max(1, int(action_capacity))
        )
        self._meters: tuple[str, dict[str, Any], int] | None = None
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._action_enqueued = 0
        self._action_drops = 0
        self._meter_enqueued = 0
        self._meter_coalesces = 0
        self._callback_failures = 0
        self._callback_ms: deque[float] = deque(maxlen=2_048)
        self._queue_wait_ms: deque[float] = deque(maxlen=2_048)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="oracle-flow-latest-publication",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)

    def submit(self, kind: str, payload: Mapping[str, Any]) -> bool:
        """Make a bounded, non-blocking handoff from canonical Order Flow."""

        queued_at = time.perf_counter_ns()
        value = (str(kind), dict(payload), queued_at)
        if kind == "FLOW_PULSE_ACTION":
            try:
                self._actions.put_nowait(value)
                with self._lock:
                    self._action_enqueued += 1
                self._wake.set()
                return True
            except queue.Full:
                # This is a real loss and must never be presented as coalesce.
                with self._lock:
                    self._action_drops += 1
                return False
        if kind != "FLOW_PULSE_METERS":
            raise ValueError(f"unsupported Flow Pulse publication kind: {kind}")
        with self._lock:
            if self._meters is not None:
                self._meter_coalesces += 1
            self._meters = value
            self._meter_enqueued += 1
        self._wake.set()
        return True

    def _next(self) -> tuple[str, dict[str, Any], int] | None:
        try:
            return self._actions.get_nowait()
        except queue.Empty:
            pass
        with self._lock:
            value = self._meters
            self._meters = None
        return value

    def _run(self) -> None:
        while not self._stop.is_set() or not self._actions.empty() or self._meters is not None:
            value = self._next()
            if value is None:
                self._wake.wait(0.1)
                self._wake.clear()
                continue
            kind, payload, queued_at = value
            started = time.perf_counter_ns()
            try:
                self._callback(kind, payload)
            except Exception:
                with self._lock:
                    self._callback_failures += 1
            finally:
                now = time.perf_counter_ns()
                with self._lock:
                    self._queue_wait_ms.append(max(0.0, (started - queued_at) / 1_000_000.0))
                    self._callback_ms.append(max(0.0, (now - started) / 1_000_000.0))
                if kind == "FLOW_PULSE_ACTION":
                    self._actions.task_done()

    def health(self) -> dict[str, Any]:
        with self._lock:
            meter_pending = self._meters is not None
            return {
                "delivery_semantics": "ACTION_FIFO_PLUS_LATEST_STATE_METERS",
                "worker_alive": bool(self._thread is not None and self._thread.is_alive()),
                "action_queue_depth": self._actions.qsize(),
                "action_queue_capacity": self._actions.maxsize,
                "action_enqueued": self._action_enqueued,
                "action_drops": self._action_drops,
                "meter_submissions": self._meter_enqueued,
                "meter_coalesces": self._meter_coalesces,
                "meter_pending": meter_pending,
                "callback_failures": self._callback_failures,
                "queue_wait_ms": _distribution(self._queue_wait_ms),
                "callback_ms": _distribution(self._callback_ms),
            }
