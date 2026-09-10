"""Process and Thread-Isolated Worker for Sol Market Brain.

Runs downstream and out-of-band to ensure zero blocking of Dhan ingestion,
Fast Lane serialization, or FastAPI request handling.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from src.oracle_sol.contracts import SolBeaconOutput, SolEvidenceSnapshot, ThesisState


@dataclass(frozen=True)
class SolReasoningJob:
    """Snapshot plus the active-session ownership captured at enqueue time."""

    snapshot: SolEvidenceSnapshot
    session_date: str
    session_generation: int


class SolMarketBrainWorker:
    """Non-blocking asynchronous background worker for Sol reasoning."""

    def __init__(
        self,
        process_callback: Callable[[SolReasoningJob], Any],
        worker_name: str = "citadel-sol-market-brain-worker",
    ) -> None:
        self.process_callback = process_callback
        self.worker_name = worker_name
        self._queue: queue.Queue[SolReasoningJob] = queue.Queue(maxsize=10)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._heartbeat_monotonic = time.monotonic()
        self._processed_count = 0
        self._last_latency_ms = 0.0
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the background worker thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name=self.worker_name, daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal worker to stop and join thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def enqueue_snapshot(
        self,
        snapshot: SolEvidenceSnapshot,
        session_date: str,
        session_generation: int,
    ) -> bool:
        """Enqueue a new snapshot for background processing (coalescing if full)."""
        try:
            # If queue is full, drop oldest unstarted snapshot to avoid lag
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
            self._queue.put_nowait(
                SolReasoningJob(
                    snapshot=snapshot,
                    session_date=session_date,
                    session_generation=session_generation,
                )
            )
            return True
        except Exception:
            return False

    def _run_loop(self) -> None:
        """Continuous execution loop."""
        while not self._stop_event.is_set():
            try:
                job = self._queue.get(timeout=1.0)
            except queue.Empty:
                with self._lock:
                    self._heartbeat_monotonic = time.monotonic()
                continue

            try:
                start_t = time.perf_counter()
                self.process_callback(job)
                elapsed_ms = (time.perf_counter() - start_t) * 1000.0

                with self._lock:
                    self._processed_count += 1
                    self._last_latency_ms = elapsed_ms
                    self._heartbeat_monotonic = time.monotonic()
            except Exception:
                with self._lock:
                    self._heartbeat_monotonic = time.monotonic()
            finally:
                self._queue.task_done()

    def health(self) -> Dict[str, Any]:
        """Return worker health telemetry."""
        with self._lock:
            age_s = time.monotonic() - self._heartbeat_monotonic
            return {
                "worker_name": self.worker_name,
                "alive": bool(self._thread and self._thread.is_alive()),
                "heartbeat_age_s": round(age_s, 2),
                "healthy": age_s < 10.0,
                "processed_count": self._processed_count,
                "last_latency_ms": round(self._last_latency_ms, 2),
                "queue_size": self._queue.qsize(),
            }

    def health_summary(self) -> Dict[str, Any]:
        return self.health()
