"""Bounded FastAPI event-loop lag telemetry for R2.1G."""

from __future__ import annotations

import asyncio
import hashlib
import sys
import threading
import time
import traceback
from collections import deque
from copy import deepcopy
from typing import Any


class EventLoopWatchdog:
    """Record monotonic wake-up lag and bounded task/thread signatures."""

    THRESHOLDS_MS = (50, 100, 250, 500, 1_000)

    def __init__(
        self,
        *,
        interval_seconds: float = 0.05,
        sample_capacity: int = 8_192,
        capture_cooldown_seconds: float = 5.0,
    ) -> None:
        self.interval_seconds = max(0.01, float(interval_seconds))
        self.capture_cooldown_seconds = max(1.0, float(capture_cooldown_seconds))
        self._samples: deque[float] = deque(maxlen=max(256, int(sample_capacity)))
        # Health is a hot serving contract, not a stack-dump transport.  Keep
        # only compact, bounded signatures here; detailed diagnosis belongs in
        # an explicit forensic capture, never every /health/live response.
        self._stalls: deque[dict[str, Any]] = deque(maxlen=8)
        self._signature_counts: dict[str, dict[str, Any]] = {}
        self._counts = {threshold: 0 for threshold in self.THRESHOLDS_MS}
        self._task: asyncio.Task | None = None
        self._last_capture_monotonic = 0.0
        self._started_monotonic: float | None = None
        self._snapshot: dict[str, Any] = self._empty_snapshot()

    def start(self) -> bool:
        if self._task is not None and not self._task.done():
            return False
        self._started_monotonic = time.monotonic()
        self._task = asyncio.create_task(self._run(), name="oracle-event-loop-watchdog")
        return True

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def snapshot(self) -> dict[str, Any]:
        # The event-loop task replaces this mapping atomically. Readers never
        # sort the live sample deque or inspect stacks.
        return deepcopy(self._snapshot)

    async def _run(self) -> None:
        expected = time.monotonic() + self.interval_seconds
        refresh_at = expected
        while True:
            await asyncio.sleep(max(0.0, expected - time.monotonic()))
            now = time.monotonic()
            lag_ms = max(0.0, (now - expected) * 1_000.0)
            self._samples.append(lag_ms)
            for threshold in self.THRESHOLDS_MS:
                if lag_ms > threshold:
                    self._counts[threshold] += 1
            if (
                lag_ms > 250.0
                and now - self._last_capture_monotonic >= self.capture_cooldown_seconds
            ):
                self._last_capture_monotonic = now
                stall = self._capture_stall(lag_ms)
                self._stalls.append(stall)
                signature = str(stall["signature_id"])
                aggregate = self._signature_counts.setdefault(
                    signature,
                    {
                        "signature_id": signature,
                        "count": 0,
                        "max_lag_ms": 0.0,
                        "top": stall.get("top"),
                    },
                )
                aggregate["count"] += 1
                aggregate["max_lag_ms"] = max(
                    float(aggregate["max_lag_ms"]), lag_ms
                )
            if now >= refresh_at or lag_ms > 50.0:
                self._refresh_snapshot(now)
                refresh_at = now + 1.0
            expected = now + self.interval_seconds

    def _refresh_snapshot(self, now: float) -> None:
        ordered = sorted(self._samples)

        def point(fraction: float) -> float | None:
            if not ordered:
                return None
            index = min(len(ordered) - 1, int((len(ordered) - 1) * fraction))
            return round(ordered[index], 3)

        self._snapshot = {
            "status": "RUNNING",
            "sample_count": len(ordered),
            "interval_ms": round(self.interval_seconds * 1_000.0, 3),
            "uptime_seconds": round(max(0.0, now - (self._started_monotonic or now)), 3),
            "lag_ms": {
                "p50": point(0.50),
                "p95": point(0.95),
                "p99": point(0.99),
                "max": round(ordered[-1], 3) if ordered else None,
            },
            "stall_counts": {
                f"over_{threshold}ms": self._counts[threshold]
                for threshold in self.THRESHOLDS_MS
            },
            "top_stall_signatures": sorted(
                (
                    {
                        **value,
                        "max_lag_ms": round(float(value["max_lag_ms"]), 3),
                    }
                    for value in self._signature_counts.values()
                ),
                key=lambda value: (-int(value["count"]), str(value["signature_id"])),
            )[:8],
            "recent_stalls": list(self._stalls),
        }

    def _capture_stall(self, lag_ms: float) -> dict[str, Any]:
        current = asyncio.current_task()
        tasks = []
        for task in sorted(asyncio.all_tasks(), key=lambda value: value.get_name())[:8]:
            if task is current or task.done():
                continue
            stack = task.get_stack(limit=2)
            tasks.append(
                {
                    "name": task.get_name(),
                    "top": self._frame_signature(stack[-1]) if stack else None,
                }
            )
        thread_names = {thread.ident: thread.name for thread in threading.enumerate()}
        threads = []
        for ident, frame in list(sys._current_frames().items())[:32]:
            name = thread_names.get(ident, f"thread-{ident}")
            if name == threading.current_thread().name:
                continue
            extracted = traceback.extract_stack(frame, limit=3)
            if extracted:
                threads.append(
                    {
                        "name": name,
                        "top": f"{extracted[-1].filename}:{extracted[-1].lineno}:{extracted[-1].name}",
                    }
                )
        # Prefer active application frames over standard-library waiters, and
        # publish at most four compact signatures.
        threads.sort(
            key=lambda value: (
                0 if "/src/" in str(value.get("top")) or "/app/" in str(value.get("top")) else 1,
                str(value.get("name")),
            )
        )
        compact_tasks = tasks[:4]
        compact_threads = threads[:4]
        signature_material = "|".join(
            str(value.get("top") or value.get("name"))
            for value in compact_threads + compact_tasks
        )
        return {
            "signature_id": hashlib.sha256(signature_material.encode()).hexdigest()[:12],
            "lag_ms": round(lag_ms, 3),
            "top": compact_threads[0] if compact_threads else compact_tasks[0] if compact_tasks else None,
            "tasks": compact_tasks,
            "threads": compact_threads,
        }

    @staticmethod
    def _frame_signature(frame) -> str:
        code = frame.f_code
        return f"{code.co_filename}:{frame.f_lineno}:{code.co_name}"

    def _empty_snapshot(self) -> dict[str, Any]:
        return {
            "status": "NOT_STARTED",
            "sample_count": 0,
            "interval_ms": round(self.interval_seconds * 1_000.0, 3),
            "uptime_seconds": 0.0,
            "lag_ms": {"p50": None, "p95": None, "p99": None, "max": None},
            "stall_counts": {
                f"over_{threshold}ms": 0 for threshold in self.THRESHOLDS_MS
            },
            "top_stall_signatures": [],
            "recent_stalls": [],
        }
