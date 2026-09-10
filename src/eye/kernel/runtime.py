"""One persistent, UI-independent EYE scanner over existing canonical caches."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any, Callable, Mapping, Optional

from src.eye.kernel.core import EyeKernel
from src.eye.kernel.domain import MarketEvent, MarketEventType
from src.eye.kernel.services import BarService, FeatureStore, OptionUniverseService
from src.eye.kernel.strategy_bus import DependencyRouter, StrategyRegistry


class EyeRuntime:
    """Single EYE kernel owner.  It accepts only normalized canonical contexts."""

    def __init__(self, *, state_path: Optional[str | Path] = None, kernel: Optional[EyeKernel] = None):
        self.kernel = kernel or EyeKernel()
        self.bar_service = BarService(self.kernel.bus)
        self.feature_store = FeatureStore(self.kernel.bus, self.bar_service)
        self.option_universe = OptionUniverseService(self.kernel.bus)
        self.strategy_registry = StrategyRegistry()
        self.kernel.register_components(None, self.bar_service, self.feature_store, self.option_universe, self.strategy_registry)
        self.dependency_router = DependencyRouter(self.kernel, state_path=state_path)
        self.kernel.dependency_router = self.dependency_router

    def start(self) -> None:
        self.kernel.start()

    def stop(self) -> None:
        self.kernel.stop()

    def get_kernel(self) -> EyeKernel:
        return self.kernel

    def hydrate_option_history(self, candles: list[Mapping[str, Any]]) -> int:
        """Prime the shared BarService from existing completed option history.

        Hydration is deliberately marked bootstrap-only: it builds indicator
        history but cannot emit a historical entry decision into the live
        strategy/Oracle projection.
        """
        self._seed_previous_session_stats(candles)
        accepted = 0
        for candle in candles:
            if self.ingest_option_candle(candle, bootstrap=True):
                accepted += 1
        self.kernel.process_cycle()
        return accepted

    def _seed_previous_session_stats(self, candles: list[Mapping[str, Any]]) -> None:
        """Derive prior-session H/L/C only from supplied completed cache rows."""
        by_contract: dict[str, list[tuple[datetime, Mapping[str, Any]]]] = defaultdict(list)
        for candle in candles:
            if not isinstance(candle, Mapping):
                continue
            contract = str(candle.get("contract") or "")
            chart_contract = candle.get("chart_contract") if isinstance(candle.get("chart_contract"), Mapping) else {}
            contract = contract or str(chart_contract.get("security_id") or "")
            try:
                timestamp = datetime.fromtimestamp(self._timestamp(candle["timestamp"]), tz=timezone.utc)
                float(candle["high"]), float(candle["low"]), float(candle["close"])
            except (KeyError, TypeError, ValueError):
                continue
            if contract:
                by_contract[contract].append((timestamp, candle))
        for contract, rows in by_contract.items():
            current_day = max(timestamp.date() for timestamp, _ in rows)
            prior_days = [timestamp.date() for timestamp, _ in rows if timestamp.date() < current_day]
            if not prior_days:
                continue
            previous_day = max(prior_days)
            previous = [candle for timestamp, candle in rows if timestamp.date() == previous_day]
            if not previous:
                continue
            try:
                high = max(float(candle["high"]) for candle in previous)
                low = min(float(candle["low"]) for candle in previous)
                close = float(max(previous, key=lambda candle: self._timestamp(candle["timestamp"]))["close"])
            except (KeyError, TypeError, ValueError):
                continue
            self.feature_store.set_prev_day_stats(contract, high, low, close)

    def ingest_option_candle(self, candle: Mapping[str, Any], *, bootstrap: bool = False) -> bool:
        """Route one existing canonical completed option candle through EYE.

        This is a read-only fan-out of the existing option-chart cache; it
        never resolves contracts, fetches Dhan, or derives a substitute price.
        """
        if not isinstance(candle, Mapping) or not (candle.get("closed") is True or candle.get("is_closed") is True):
            return False
        contract = str(candle.get("contract") or "")
        chart_contract = candle.get("chart_contract") if isinstance(candle.get("chart_contract"), Mapping) else {}
        if not contract:
            contract = str(chart_contract.get("security_id") or "")
        side = str(chart_contract.get("option_type") or candle.get("option_type") or "").upper()
        if not contract or side not in {"CE", "PE"}:
            return False
        try:
            opened_at = self._timestamp(candle["timestamp"])
            close = float(candle["close"])
            high = float(candle["high"])
            low = float(candle["low"])
            open_price = float(candle["open"])
            volume = float(candle.get("volume") or 0.0)
        except (KeyError, TypeError, ValueError):
            return False
        source_timestamp = self._timestamp(candle.get("candle_closed_at") or candle["timestamp"])
        ingest_timestamp = self._timestamp(candle.get("received_at") or candle.get("candle_closed_at") or candle["timestamp"])
        event_id = f"EYE:OPTION_1M:{contract}:{int(opened_at)}"
        return self.kernel.bus.publish(MarketEvent(
            event_id=event_id,
            event_type=MarketEventType.TICK,
            source_timestamp=source_timestamp,
            ingest_timestamp=ingest_timestamp,
            security_id=contract,
            source="CANONICAL_OPTION_CHART_CACHE",
            payload={"bar": {
                "time": int(opened_at), "open": open_price, "high": high,
                "low": low, "close": close, "volume": volume,
                "option_type": side, "bootstrap": bool(bootstrap),
                "source_timestamp": source_timestamp, "ingest_timestamp": ingest_timestamp,
            }},
            source_revision=int(opened_at),
        ))

    @staticmethod
    def _timestamp(value: Any) -> float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()


class PersistentEyeScanner:
    """Consumes one existing completed-candle context; it owns no feed or UI state."""

    def __init__(
        self,
        runtime: EyeRuntime,
        *,
        context_provider: Callable[[], Mapping[str, Any]],
        strategy_context_factory: Optional[Callable[[Mapping[str, Any]], Mapping[str, Any]]] = None,
        poll_seconds: float = 1.0,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.runtime = runtime
        self.context_provider = context_provider
        self.strategy_context_factory = strategy_context_factory or self._default_strategy_contexts
        self.poll_seconds = max(0.25, float(poll_seconds))
        self.now = now
        self._last_candle_id: Optional[str] = None
        self._stop = Event()
        self._thread: Optional[Thread] = None
        self._lock = Lock()
        self._stats = {"cycles": 0, "evaluations": 0, "duplicate_candles": 0, "last_error": None, "last_candle_id": None, "last_event_at": None, "max_cycle_ms": 0.0}

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self.runtime.start()
            self._stop.clear()
            self._thread = Thread(target=self._run, name="citadel-eye-scanner", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self.runtime.stop()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(self.poll_seconds)

    def run_once(self) -> dict[str, Any]:
        started = monotonic()
        self._stats["cycles"] += 1
        try:
            context = self.context_provider()
            if not isinstance(context, Mapping) or context.get("closed") is not True:
                self._stats["last_error"] = str((context or {}).get("reason") or "COMPLETED_CANDLE_CONTEXT_UNAVAILABLE") if isinstance(context, Mapping) else "COMPLETED_CANDLE_CONTEXT_UNAVAILABLE"
                return self.status()
            candle_id = str(context.get("candle_id") or "")
            if not candle_id:
                self._stats["last_error"] = "CANDLE_ID_UNAVAILABLE"
                return self.status()
            if candle_id == self._last_candle_id:
                self._stats["duplicate_candles"] += 1
                return self.status()
            timestamp = self._timestamp(context.get("timestamp"))
            contexts = self.strategy_context_factory(deepcopy(dict(context)))
            if not isinstance(contexts, Mapping):
                self._stats["last_error"] = "STRATEGY_CONTEXT_FACTORY_INVALID"
                return self.status()
            published = self.runtime.kernel.bus.publish(MarketEvent(
                event_id=f"EYE:COMPLETED:{candle_id}", event_type=MarketEventType.BAR_CLOSED,
                source_timestamp=timestamp, ingest_timestamp=self.now().timestamp(), security_id=str(context.get("symbol") or "NIFTY"),
                source="CANONICAL_COMPLETED_CANDLE", payload={"timeframe": self._minutes(context.get("timeframe")), "bar": dict(context.get("bar") or {}), "completed": True, "strategy_contexts": dict(contexts)},
                source_revision=int((context.get("bar") or {}).get("index") or 0),
            ))
            if published:
                before = self.runtime.dependency_router.evaluation_count
                self.runtime.kernel.process_cycle()
                self._stats["evaluations"] += self.runtime.dependency_router.evaluation_count - before
                self._last_candle_id = candle_id
                self._stats["last_candle_id"] = candle_id
                self._stats["last_event_at"] = self.now().isoformat()
            self._stats["last_error"] = None
        except Exception as error:  # scanner must fail closed and keep prior projection intact
            self._stats["last_error"] = f"{type(error).__name__}:{error}"
        finally:
            self._stats["max_cycle_ms"] = max(self._stats["max_cycle_ms"], round((monotonic() - started) * 1000.0, 3))
        return self.status()

    @staticmethod
    def _timestamp(value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()

    @staticmethod
    def _minutes(value: Any) -> int:
        text = str(value or "5m").lower()
        return int(text[:-1]) if text.endswith("m") and text[:-1].isdigit() else 5

    @staticmethod
    def _default_strategy_contexts(context: Mapping[str, Any]) -> Mapping[str, Any]:
        """Forward a published canonical strategy envelope, or fail closed.

        The scanner is allowed to consume an envelope a canonical producer has
        already published with the completed candle.  It must not manufacture
        the futures/flow inputs S02 and S06 require from an unrelated bar.
        """
        timestamp = context.get("timestamp")
        unavailable = {
            "timestamp": timestamp,
            "fresh": False,
            "completed": False,
            "unavailable_reason": "CANONICAL_SOURCE_NOT_PUBLISHED",
        }
        supplied = context.get("strategy_contexts")
        if isinstance(supplied, Mapping):
            return {
                strategy_id: (
                    deepcopy(dict(supplied[strategy_id]))
                    if isinstance(supplied.get(strategy_id), Mapping)
                    else dict(unavailable)
                )
                for strategy_id in ("S02", "S03", "S04", "S06")
            }
        return {
            "S02": dict(unavailable),
            "S03": context,
            "S04": context,
            "S06": dict(unavailable),
        }

    def status(self) -> dict[str, Any]:
        return {
            "status": "RUNNING" if self._thread and self._thread.is_alive() else "STOPPED",
            **dict(self._stats),
            "queue_depth": len(self.runtime.kernel.bus._event_queue),
            "event_bus": self.runtime.kernel.bus.telemetry(),
            "execution_influence": "ZERO",
            "paper_only": True,
            "live_trading_enabled": False,
            "broker_submission": False,
        }
