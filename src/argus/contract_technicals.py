"""Latest-wins adapter for slow, presentation-only contract technicals."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from threading import Lock, Thread
from time import perf_counter
from typing import Any, Callable, Mapping


class LatestContractTechnicalsProvider:
    """Keep Dhan history retrieval outside the ARGUS producer hot path.

    Raw/history evidence remains owned by the existing OSE provider.  This
    adapter only coalesces redundant presentation requests while that provider
    is busy and publishes the latest completed result atomically.
    """

    def __init__(self, provider: Callable[[Mapping[str, Any], Any], dict[str, Any]]):
        self._provider = provider
        self._lock = Lock()
        self._cache: dict[str, dict[str, Any]] = {}
        self._latest: dict[str, tuple[str, dict[str, Any], Any]] = {}
        self._threads: dict[str, Thread] = {}
        self._submitted = 0
        self._completed = 0
        self._coalesced = 0
        self._failures = 0
        self._last_latency_ms: float | None = None

    @staticmethod
    def _key(contract: Mapping[str, Any], observed_at: Any) -> tuple[str, str]:
        side = str(contract.get("side") or contract.get("option_type") or "").upper()
        security_id = str(contract.get("security_id") or "")
        try:
            observed = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
            boundary = observed.replace(
                minute=(observed.minute // 5) * 5, second=0, microsecond=0
            ).isoformat()
        except (TypeError, ValueError):
            boundary = str(observed_at)
        return side, f"{side}:{security_id}:{boundary}"

    def __call__(self, contract: Mapping[str, Any], observed_at: Any) -> dict[str, Any]:
        side, key = self._key(contract, observed_at)
        if side not in {"CE", "PE"}:
            return {
                "status": "UNAVAILABLE",
                "reason": "SELECTED_CONTRACT_IDENTITY_UNAVAILABLE",
            }
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                result = deepcopy(cached)
                premium = contract.get("premium")
                if premium is not None:
                    result["current_premium"] = premium
                result.setdefault("performance", {})["async_cache_hit"] = True
                return result

            previous = self._latest.get(side)
            if previous is not None and previous[0] != key:
                self._coalesced += 1
            self._latest[side] = (key, deepcopy(dict(contract)), observed_at)
            thread = self._threads.get(side)
            if thread is None or not thread.is_alive():
                thread = Thread(
                    target=self._run,
                    args=(side,),
                    name=f"argus-contract-technicals-{side.lower()}",
                    daemon=True,
                )
                self._threads[side] = thread
                self._submitted += 1
                thread.start()
        return {
            "status": "UNAVAILABLE",
            "reason": "SELECTED_CONTRACT_TECHNICALS_WARMING",
            "security_id": str(contract.get("security_id") or "") or None,
            "side": side,
            "freshness": "UNAVAILABLE",
            "action_locked": True,
        }

    def _run(self, side: str) -> None:
        while True:
            with self._lock:
                request = self._latest.get(side)
            if request is None:
                return
            key, contract, observed_at = request
            started = perf_counter()
            try:
                result = self._provider(contract, observed_at)
            except Exception as error:
                result = {
                    "status": "UNAVAILABLE",
                    "reason": f"SELECTED_CONTRACT_TECHNICALS_UNAVAILABLE:{type(error).__name__}",
                    "security_id": str(contract.get("security_id") or "") or None,
                    "side": side,
                    "action_locked": True,
                }
                with self._lock:
                    self._failures += 1
            latency_ms = (perf_counter() - started) * 1000.0
            with self._lock:
                self._cache[key] = deepcopy(result)
                while len(self._cache) > 16:
                    self._cache.pop(next(iter(self._cache)))
                self._completed += 1
                self._last_latency_ms = latency_ms
                latest = self._latest.get(side)
                if latest is not None and latest[0] == key:
                    self._latest.pop(side, None)
                    return
                self._submitted += 1

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "queue_depth": len(self._latest),
                "submitted": self._submitted,
                "completed": self._completed,
                "coalesced_revision_count": self._coalesced,
                "failures": self._failures,
                "last_latency_ms": (
                    round(self._last_latency_ms, 3)
                    if self._last_latency_ms is not None
                    else None
                ),
                "max_workers": 2,
            }
