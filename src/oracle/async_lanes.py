"""Independent Async Lanes & Identity Epoch for Oracle Phase 6."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar, Generic, Dict, Optional
from collections import deque
from threading import Thread, Condition, RLock, Event
from datetime import datetime, timezone
import time

T = TypeVar('T')

@dataclass(frozen=True)
class IdentityEpoch(Generic[T]):
    identity_epoch: int
    input_version: int
    output_version: int
    source_ts: float
    gateway_received_ts: float
    calculated_at: float
    payload: T

class CanonicalLiveState:
    def __init__(self):
        self._lock = RLock()
        self.fast_state: dict[str, Any] = {}
        self.slow_state: dict[str, Any] = {}
        self.latest_epoch: int = 0
        self.event_revision: int = 0
        self.observers = []

    def update_fast(self, epoch: IdentityEpoch):
        with self._lock:
            if epoch.identity_epoch < self.latest_epoch:
                return # Reject older epoch
            if epoch.identity_epoch > self.latest_epoch:
                self.latest_epoch = epoch.identity_epoch
            if isinstance(epoch.payload, dict):
                self.fast_state.update(epoch.payload)
            self.event_revision += 1
            self._notify()

    def update_slow(self, epoch: IdentityEpoch):
        with self._lock:
            if epoch.identity_epoch < self.latest_epoch:
                return # Reject older epoch
            if epoch.identity_epoch > self.latest_epoch:
                self.latest_epoch = epoch.identity_epoch
            if isinstance(epoch.payload, dict):
                self.slow_state.update(epoch.payload)
            self.event_revision += 1
            self._notify()

    def _notify(self):
        snapshot = self.snapshot()
        for observer in self.observers:
            try:
                observer(snapshot)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f'Lane error: {e}')
                
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "fast_state": dict(self.fast_state),
                "slow_state": dict(self.slow_state),
                "latest_epoch": self.latest_epoch,
                "event_revision": self.event_revision
            }

class AsyncLaneProcessor:
    def __init__(self, name: str, processor: Callable[[Any], Any], on_result: Callable[[IdentityEpoch], None]):
        self.name = name
        self.processor = processor
        self.on_result = on_result
        self._queue = deque(maxlen=100)
        self._pending_tasks = 0
        self._lock = RLock()
        self._cond = Condition(self._lock)
        self._stop = Event()
        self._thread = Thread(target=self._run, name=f"oracle-lane-{name}", daemon=True)

    def start(self):
        self._stop.clear()
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self):
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def enqueue(self, epoch: IdentityEpoch):
        with self._cond:
            if self._queue and self._queue[-1].identity_epoch == epoch.identity_epoch:
                self._queue[-1] = epoch
            else:
                self._pending_tasks += 1
                self._queue.append(epoch)
            self._cond.notify_all()

    def wait_until_idle(self, timeout=None):
        with self._cond:
            self._cond.wait_for(lambda: self._pending_tasks == 0, timeout=timeout)

    def execute_all_pending(self):
        """For synchronous testing environments where start() is not called."""
        while True:
            with self._cond:
                if not self._queue:
                    break
                epoch = self._queue.popleft()
            try:
                result = self.processor(epoch.payload)
                processed = IdentityEpoch(
                    identity_epoch=epoch.identity_epoch,
                    input_version=epoch.input_version,
                    output_version=epoch.output_version + 1,
                    source_ts=epoch.source_ts,
                    gateway_received_ts=epoch.gateway_received_ts,
                    calculated_at=time.time(),
                    payload=result
                )
                self.on_result(processed)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f'Lane error: {e}')
            finally:
                with self._cond:
                    self._pending_tasks -= 1
                    self._cond.notify_all()
    def _run(self):
        while not self._stop.is_set():
            with self._cond:
                while not self._queue and not self._stop.is_set():
                    self._cond.wait(timeout=0.1)
                if not self._queue:
                    continue
                epoch = self._queue.popleft()
            
            try:
                result = self.processor(epoch.payload)
                processed = IdentityEpoch(
                    identity_epoch=epoch.identity_epoch,
                    input_version=epoch.input_version,
                    output_version=epoch.output_version + 1,
                    source_ts=epoch.source_ts,
                    gateway_received_ts=epoch.gateway_received_ts,
                    calculated_at=time.time(),
                    payload=result
                )
                self.on_result(processed)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f'Lane error: {e}')
            finally:
                with self._cond:
                    self._pending_tasks -= 1
                    self._cond.notify_all()
