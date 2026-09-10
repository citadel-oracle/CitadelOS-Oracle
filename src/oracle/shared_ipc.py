"""Small shared-memory primitives with one lock per process boundary.

``multiprocessing.Value`` and ``multiprocessing.Event`` each allocate their
own named semaphore on macOS.  The isolated Oracle gateways need several
small counters/flags, so allocating one synchronization primitive per scalar
consumes a material fraction of the launchd soft file-descriptor limit before
either child starts.  These slots retain the familiar ``value``/Event API but
share one synchronized array and therefore one lock.
"""

from __future__ import annotations

import time
from typing import Any


class SharedIntSlot:
    """One signed 64-bit value inside a process-shared synchronized array."""

    def __init__(self, storage: Any, index: int) -> None:
        self._storage = storage
        self._index = int(index)

    @property
    def value(self) -> int:
        return int(self._storage[self._index])

    @value.setter
    def value(self, value: int) -> None:
        self._storage[self._index] = int(value)

    def get_lock(self) -> Any:
        return self._storage.get_lock()


class SharedFlag(SharedIntSlot):
    """Event-compatible flag without a dedicated semaphore/condition pair."""

    def set(self) -> None:
        self.value = 1

    def clear(self) -> None:
        self.value = 0

    def is_set(self) -> bool:
        return bool(self.value)

    def wait(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
        while not self.is_set():
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                time.sleep(min(0.01, remaining))
            else:
                time.sleep(0.01)
        return True


def shared_int_slots(context: Any, count: int) -> tuple[Any, tuple[SharedIntSlot, ...]]:
    """Allocate ``count`` integer slots backed by exactly one shared lock."""

    storage = context.Array("q", [0] * int(count), lock=True)
    return storage, tuple(SharedIntSlot(storage, index) for index in range(int(count)))
