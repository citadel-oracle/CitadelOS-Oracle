"""Single EYE strategy router: canonical events in, immutable projections out."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

from src.eye.kernel.domain import MarketEvent, MarketEventType, StrategyLifecycleState as KernelLifecycleState, StrategyManifest
from src.eye.personal_strategies.contracts import StrategyLifecycleState
from src.eye.personal_strategies.strategies.s01_bb_rsi_momentum import S01Evaluator
from src.eye.personal_strategies.strategies.s02_nifty_volatile import S02Evaluator
from src.eye.personal_strategies.strategies.s03_trend_catcher import S03Evaluator
from src.eye.personal_strategies.strategies.s04_bull_pulse import S04Evaluator
from src.eye.personal_strategies.strategies.s05_bb_cpr_breakout import S05Evaluator
from src.eye.personal_strategies.strategies.s06_opening_momentum_recovery import S06Evaluator
from src.strategy_lab.storage import _atomic_write


class StrategyStateStore:
    """Small atomic, restart-safe state document; tests may keep it in memory."""

    def __init__(self, path: Optional[str | Path] = None):
        self.path = Path(path) if path else None
        self._states: dict[str, dict[str, Any]] = {}
        if self.path:
            self._restore()

    def _restore(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            values = raw.get("states") if isinstance(raw, Mapping) else None
            if isinstance(values, Mapping):
                self._states = {str(k): dict(v) for k, v in values.items() if isinstance(v, Mapping)}
        except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
            self._states = {}

    def _persist(self) -> None:
        if self.path:
            _atomic_write(self.path, {"schema_version": 1, "states": self._states})

    def get_state(self, strategy_id: str) -> dict[str, Any]:
        key = str(strategy_id)
        if key not in self._states:
            self._states[key] = {
                "strategy_id": key, "cycle_id": None, "authority_state": "SCANNING",
                "locked_contract": None, "trigger_time": None, "rearm_state": True,
                "active_management_state": None, "source_revision": 0,
            }
        return self._states[key]

    def update_state(self, strategy_id: str, updates: Mapping[str, Any]) -> None:
        self.get_state(strategy_id).update(dict(updates))
        self._persist()


class StrategyRegistry:
    """Registry holding the six source-resolvable personal strategies."""

    def __init__(self):
        self.s01 = S01Evaluator()
        self.s02 = S02Evaluator()
        self.s03 = S03Evaluator()
        self.s04 = S04Evaluator()
        self.s05_ce = S05Evaluator(option_type="CE")
        self.s05_pe = S05Evaluator(option_type="PE")
        self.s06 = S06Evaluator()
        self.manifests = {
            "S01": StrategyManifest("S01", True, "LIVE_SHADOW_READY", ["NIFTY"], [3], ["BB20", "RSI14"], [MarketEventType.BAR_CLOSED], []),
            "S02": StrategyManifest("S02", True, "LIVE_SHADOW_READY", ["NIFTY_FUT"], [5, 15], ["CPR", "BB", "Supertrend"], [MarketEventType.BAR_CLOSED], []),
            "S03": StrategyManifest("S03", True, "LIVE_SHADOW_READY", ["NIFTY"], [1, 5], ["NATIVE_TREND_CATCHER"], [MarketEventType.BAR_CLOSED], ["09:35", "09:45"]),
            "S04": StrategyManifest("S04", True, "LIVE_SHADOW_READY", ["NIFTY"], [1, 5], ["NATIVE_BULL_PULSE"], [MarketEventType.BAR_CLOSED], ["10:30"]),
            "S05": StrategyManifest("S05", True, "LIVE_SHADOW_READY", ["NIFTY"], [3, 5], ["BB20", "CPR", "EMA15"], [MarketEventType.BAR_CLOSED], []),
            "S06": StrategyManifest("S06", True, "LIVE_SHADOW_READY", ["NIFTY"], [1], ["ARGUS_PROBABLE_FLOW", "ATR14"], [MarketEventType.BAR_CLOSED], []),
        }


class DependencyRouter:
    """Routes only completed canonical events and never derives market evidence."""

    def __init__(self, kernel, *, state_path: Optional[str | Path] = None):
        self.kernel = kernel
        self.state_store = StrategyStateStore(state_path)
        self.evaluation_count = 0
        self.kernel.bus.subscribe(MarketEventType.BAR_CLOSED, self._on_bar_closed)
        self.kernel.bus.subscribe(MarketEventType.SCHEDULED_CLOCK, self._on_clock)
        self._restore_evaluator_state()

    def _restore_evaluator_state(self) -> None:
        for sid, evaluator in (("S02", self.kernel.strategy_registry.s02), ("S03", self.kernel.strategy_registry.s03), ("S04", self.kernel.strategy_registry.s04), ("S06", self.kernel.strategy_registry.s06)):
            payload = self.get_evaluator_payload(sid)
            if payload is None:
                continue
            try:
                evaluator.restore_state(payload)
            except (TypeError, ValueError, KeyError, json.JSONDecodeError):
                # A malformed persisted evaluator state must not activate a trade.
                self.state_store.update_state(sid, {"authority_state": "MISSING_DATA", "restore_error": "STATE_RESTORE_FAILED"})

    def get_evaluator_payload(self, sid: str) -> Any:
        return self.state_store.get_state(sid).get("evaluator_state")

    def _on_bar_closed(self, event: MarketEvent) -> None:
        if event.payload.get("completed") is False:
            return
        contexts = event.payload.get("strategy_contexts")
        if isinstance(contexts, Mapping):
            self._evaluate_contextual(contexts, event)
        bar = event.payload.get("bar")
        if isinstance(bar, Mapping) and bar.get("bootstrap") is True:
            return
        # Existing S01/S05 path remains through the one shared bar service.  It
        # never injects default quotes or pivots when canonical inputs are absent.
        tf = event.payload.get("timeframe")
        if tf == 3:
            self._evaluate_s01(event)
            self._evaluate_s05(event)
        elif tf == 5:
            self._evaluate_s05(event)

    def _on_clock(self, event: MarketEvent) -> None:
        # Clock events do not invent contexts.  They only prompt a fresh
        # completed-candle evaluation supplied by the scanner on its next event.
        return

    def _evaluate_contextual(self, contexts: Mapping[str, Any], event: MarketEvent) -> None:
        routing = (
            ("S02", self.kernel.strategy_registry.s02),
            ("S03", self.kernel.strategy_registry.s03),
            ("S04", self.kernel.strategy_registry.s04),
            ("S06", self.kernel.strategy_registry.s06),
        )
        for sid, evaluator in routing:
            context = contexts.get(sid)
            if not isinstance(context, Mapping):
                continue
            signal = evaluator.evaluate(context=context, timestamp_str=self._ts_to_str(event.source_timestamp))
            self._persist_and_emit(sid, evaluator, signal, event)

    def _evaluate_s01(self, event: MarketEvent) -> None:
        bar = event.payload.get("bar")
        if not isinstance(bar, Mapping) or str(bar.get("option_type") or "").upper() != "CE":
            return
        state = self.state_store.get_state("S01")
        contract = state.get("locked_contract") or str(event.security_id or "")
        if not contract:
            return
        bars_3m = self.kernel.bar_service.get_bars(contract, 3, limit=30)
        bars_1m = self.kernel.bar_service.get_bars(contract, 1, limit=1)
        if not bars_3m or not bars_1m:
            return
        evaluator = self.kernel.strategy_registry.s01
        evaluator.cycle_locked_contract = contract
        evaluator.rearm_satisfied = bool(state.get("rearm_state", True))
        signal = evaluator.evaluate(contract, bars_3m, self._ts_to_str(event.source_timestamp), bars_1m[-1]["close"], state.get("active_management_state"))
        self.state_store.update_state("S01", {"rearm_state": evaluator.rearm_satisfied, "locked_contract": evaluator.cycle_locked_contract, "authority_state": signal.state.value})
        self._emit_signal(signal, event)

    def _evaluate_s05(self, event: MarketEvent) -> None:
        bar = event.payload.get("bar")
        if not isinstance(bar, Mapping):
            return
        side = str(bar.get("option_type") or "").upper()
        if side not in {"CE", "PE"}:
            return
        evaluator = self.kernel.strategy_registry.s05_ce if side == "CE" else self.kernel.strategy_registry.s05_pe
        sid = f"S05_{side}"
        state = self.state_store.get_state(sid)
        contract = state.get("locked_contract") or str(event.security_id or "")
        if not contract:
            return
        bars_3m = self.kernel.bar_service.get_bars(contract, 3, limit=30)
        bars_5m = self.kernel.bar_service.get_bars(contract, 5, limit=30)
        bars_1m = self.kernel.bar_service.get_bars(contract, 1, limit=1)
        high, low, close = self.kernel.feature_store.get_prev_day_stats(contract)
        if not bars_3m or not bars_5m or not bars_1m or None in (high, low, close):
            return
        evaluator.rearm_satisfied = bool(state.get("rearm_state", True))
        signal = evaluator.evaluate(contract, bars_3m, bars_5m, high, low, close, self._ts_to_str(event.source_timestamp), bars_1m[-1]["close"], state.get("active_management_state"))
        self.state_store.update_state(sid, {"rearm_state": evaluator.rearm_satisfied, "locked_contract": contract, "authority_state": signal.state.value})
        self._emit_signal(signal, event)

    def _persist_and_emit(self, sid: str, evaluator: Any, signal: Any, event: MarketEvent) -> None:
        serializable = evaluator.serialize_state() if hasattr(evaluator, "serialize_state") else None
        self.state_store.update_state(sid, {
            "authority_state": signal.state.value,
            "cycle_id": signal.cycle_id,
            "locked_contract": signal.preferred_contract,
            "source_revision": event.source_revision or 0,
            "evaluator_state": serializable,
        })
        self._emit_signal(signal, event)

    @staticmethod
    def _ts_to_str(ts: float) -> str:
        return datetime.fromtimestamp(float(ts), tz=ZoneInfo("Asia/Kolkata")).strftime("%H:%M:%S")

    def _emit_signal(self, sig: Any, event: MarketEvent) -> None:
        from src.eye.oracle_projection.runtime_state import EyeRuntimeState
        runtime = EyeRuntimeState.get_instance()
        sid = sig.strategy_id.value if hasattr(sig.strategy_id, "value") else str(sig.strategy_id)
        runtime.set_strategy_signal(sid, sig.to_dict(), source_timestamp=event.source_timestamp, source_revision=event.source_revision or 0)
        self.evaluation_count += 1
        self.kernel.bus.publish(MarketEvent(
            event_id=f"SIG:{sid}:{sig.cycle_id}:{event.source_revision or 0}:{event.source_timestamp}",
            event_type=MarketEventType.STRATEGY_EVENT,
            source_timestamp=event.source_timestamp,
            ingest_timestamp=event.ingest_timestamp,
            security_id=sid,
            source="DependencyRouter",
            payload={"signal": sig.to_dict()}, source_revision=event.source_revision,
        ))
