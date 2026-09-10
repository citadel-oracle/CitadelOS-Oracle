"""Read-only compatibility facade for Personal Strategy projections.

Live strategy evaluation is owned by ``DependencyRouter``.  This facade exists
for legacy callers and deliberately refuses to synthesize bars, contracts,
quotes, pivots, or provider availability.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from src.eye.personal_strategies.contracts import PersonalStrategyId, PersonalStrategySignal, StrategyLifecycleState
from src.eye.personal_strategies.registry import PersonalStrategyRegistry
from src.eye.personal_strategies.strategies.s01_bb_rsi_momentum import S01Evaluator
from src.eye.personal_strategies.strategies.s02_nifty_volatile import S02Evaluator
from src.eye.personal_strategies.strategies.s03_trend_catcher import S03Evaluator
from src.eye.personal_strategies.strategies.s04_bull_pulse import S04Evaluator
from src.eye.personal_strategies.strategies.s05_bb_cpr_breakout import S05Evaluator
from src.eye.personal_strategies.strategies.s06_opening_momentum_recovery import S06Evaluator


class PersonalStrategyEngine:
    """Compatibility-only evaluator over supplied canonical contexts."""

    _instance: Optional["PersonalStrategyEngine"] = None

    @classmethod
    def get_instance(cls) -> "PersonalStrategyEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.registry = PersonalStrategyRegistry.get_instance()
        self.s01_evaluator = S01Evaluator()
        self.s02_evaluator = S02Evaluator()
        self.s03_evaluator = S03Evaluator()
        self.s04_evaluator = S04Evaluator()
        self.s05_ce_evaluator = S05Evaluator(option_type="CE")
        self.s05_pe_evaluator = S05Evaluator(option_type="PE")
        self.s06_evaluator = S06Evaluator()
        self.last_signals: dict[str, PersonalStrategySignal] = {}
        self.primary_signal: Optional[PersonalStrategySignal] = None

    def evaluate_all(self, *, contexts: Optional[Mapping[str, Any]] = None, timestamp_str: str = "") -> list[PersonalStrategySignal]:
        """Evaluate only supplied canonical contexts; unavailable remains explicit."""
        values = contexts if isinstance(contexts, Mapping) else {}
        timestamp = timestamp_str or str(values.get("timestamp") or "")
        signals = [
            self._missing(PersonalStrategyId.S01, "BUY_CE", timestamp, "S01_ROUTED_BY_EYE_KERNEL"),
            self.s02_evaluator.evaluate(timestamp_str=timestamp, context=values.get("S02")),
            self.s03_evaluator.evaluate(timestamp_str=timestamp, context=values.get("S03")),
            self.s04_evaluator.evaluate(timestamp_str=timestamp, context=values.get("S04")),
            self._missing(PersonalStrategyId.S05, "BUY_CE", timestamp, "S05_ROUTED_BY_EYE_KERNEL"),
            self._missing(PersonalStrategyId.S05, "BUY_PE", timestamp, "S05_ROUTED_BY_EYE_KERNEL"),
            self.s06_evaluator.evaluate(timestamp_str=timestamp, context=values.get("S06")),
        ]
        for signal in signals:
            key = signal.strategy_id.value if hasattr(signal.strategy_id, "value") else str(signal.strategy_id)
            self.last_signals[key] = signal
        self.primary_signal = self._select_primary_signal(signals)
        return signals

    @staticmethod
    def _missing(strategy_id: PersonalStrategyId, direction: str, timestamp: str, reason: str) -> PersonalStrategySignal:
        return PersonalStrategySignal(
            signal_id=f"SIG:{strategy_id.value}:UNAVAILABLE:{timestamp}", strategy_id=strategy_id,
            strategy_name=strategy_id.value, short_label=strategy_id.value.split("_")[0], strategy_version="1.0",
            state=StrategyLifecycleState.MISSING_DATA, direction=direction, match_count=0, match_total=0,
            satisfied_conditions=[], missing_conditions=[reason], next_required_event="WAIT_FOR_EYE_KERNEL",
            contract_status="UNRESOLVED", preferred_contract=None, geometry_status="UNAVAILABLE", entry_band=None,
            structural_sl=None, informational_targets={}, risk_status="BLOCKED", blocker=reason,
            execution_status="FAIL_CLOSED", event_timestamp=timestamp, source_timestamp=timestamp, freshness=0.0,
            cycle_id=f"{strategy_id.value}:UNAVAILABLE", execution_exit_authority=False,
        )

    @staticmethod
    def _select_primary_signal(signals: list[PersonalStrategySignal]) -> PersonalStrategySignal:
        priority = {
            StrategyLifecycleState.MANAGING: 0, StrategyLifecycleState.DETECTED: 1,
            StrategyLifecycleState.CONFIRMED: 2, StrategyLifecycleState.PARTIAL: 3,
            StrategyLifecycleState.SCANNING: 4, StrategyLifecycleState.MISSING_DATA: 5,
            StrategyLifecycleState.BLOCKED: 6, StrategyLifecycleState.EXITED: 7,
        }
        return min(signals, key=lambda signal: priority.get(signal.state, 99))

    def get_signal_bus_summary(self) -> dict[str, Any]:
        return {
            "primary_signal": self.primary_signal.to_dict() if self.primary_signal else None,
            "all_signals": [signal.to_dict() for signal in self.last_signals.values()],
            "total_registered_strategies": len(self.registry.strategies),
            "active_evaluated_strategies": len(self.last_signals),
            "s07_runtime_evaluator_exists": False,
        }
