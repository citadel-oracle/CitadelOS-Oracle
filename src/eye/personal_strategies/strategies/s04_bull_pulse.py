"""S04 adapter over the certified Strategy Lab Bull Pulse engine."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from src.eye.personal_strategies.contracts import PersonalStrategyId, PersonalStrategySignal, StrategyLifecycleState
from src.strategy_lab.strategies.bull_pulse.strategy import BullPulseStrategyEngine


class S04Evaluator:
    """Thin EYE projection adapter; Bull Pulse semantics remain source-native."""

    def __init__(self, engine: Optional[BullPulseStrategyEngine] = None):
        self.engine = engine or BullPulseStrategyEngine()
        self.flash_epoch = 0
        self._last_state: Optional[StrategyLifecycleState] = None

    def serialize_state(self) -> str:
        return self.engine.serialize()

    def restore_state(self, payload: str) -> None:
        self.engine = BullPulseStrategyEngine.deserialize(payload)

    def evaluate(self, option_contract: Optional[str] = None, timestamp_str: str = "10:30:00", *, context: Optional[Mapping[str, Any]] = None) -> PersonalStrategySignal:
        if not isinstance(context, Mapping):
            return self._signal(StrategyLifecycleState.MISSING_DATA, option_contract, 0, [], ["CANONICAL_BULL_PULSE_CONTEXT"], "WAIT_FOR_COMPLETED_CONTEXT", timestamp_str, blocker="S04_CANONICAL_CONTEXT_UNAVAILABLE")
        result = self.engine.evaluate(context)
        status = str(result.get("status") or "UNAVAILABLE")
        state = {
            "ENTRY_CANDIDATE": StrategyLifecycleState.DETECTED,
            "HOLD": StrategyLifecycleState.MANAGING,
            "EXIT_CANDIDATE": StrategyLifecycleState.EXITED,
            "WAIT": StrategyLifecycleState.SCANNING,
            "SESSION_COMPLETE": StrategyLifecycleState.EXITED,
            "UNAVAILABLE": StrategyLifecycleState.MISSING_DATA,
        }.get(status, StrategyLifecycleState.MISSING_DATA)
        contract = result.get("option_contract") if isinstance(result.get("option_contract"), Mapping) else None
        preferred = (contract or {}).get("security_id") or (contract or {}).get("trading_symbol") or option_contract
        raw_state = result.get("state") if isinstance(result.get("state"), Mapping) else {}
        entry = result.get("entry")
        sl = result.get("sl")
        return self._signal(
            state, str(preferred) if preferred else None,
            3 if state in {StrategyLifecycleState.DETECTED, StrategyLifecycleState.MANAGING} else 0,
            [str(result.get("reason") or status)] if state not in {StrategyLifecycleState.MISSING_DATA, StrategyLifecycleState.SCANNING} else [],
            [str(result.get("reason") or status)] if state in {StrategyLifecycleState.MISSING_DATA, StrategyLifecycleState.SCANNING} else [],
            "RISK_AND_ANALYZER_VERIFICATION" if state == StrategyLifecycleState.DETECTED else str(result.get("reason") or "WAIT"),
            timestamp_str, structural_sl=float(sl) if isinstance(sl, (int, float)) else None,
            entry_band={"low": float(entry), "high": float(entry)} if isinstance(entry, (int, float)) else None,
            targets={"native_status": status, "native_state": raw_state},
            blocker=str(result.get("reason")) if state == StrategyLifecycleState.MISSING_DATA else None,
        )

    def _signal(self, state: StrategyLifecycleState, contract: Optional[str], match_count: int, satisfied: list[str], missing: list[str], next_event: str, timestamp: str, *, structural_sl: Optional[float] = None, entry_band: Optional[dict[str, float]] = None, targets: Optional[dict[str, Any]] = None, blocker: Optional[str] = None) -> PersonalStrategySignal:
        if self._last_state != state:
            self.flash_epoch += 1
            self._last_state = state
        return PersonalStrategySignal(
            signal_id=f"SIG:S04:{contract or 'NONE'}:{timestamp}", strategy_id=PersonalStrategyId.S04,
            strategy_name="NIFTY BULL PULSE", short_label="BULL PULSE", strategy_version="1.1",
            state=state, direction="BUY_CE", match_count=match_count, match_total=3,
            satisfied_conditions=satisfied, missing_conditions=missing, next_required_event=next_event,
            contract_status="RESOLVED" if contract else "UNRESOLVED", preferred_contract=contract,
            geometry_status="NATIVE" if structural_sl is not None else "ESTABLISHING", entry_band=entry_band,
            structural_sl=structural_sl, informational_targets=targets or {}, risk_status="PENDING" if not blocker else "BLOCKED",
            blocker=blocker, execution_status="FAIL_CLOSED", event_timestamp=timestamp, source_timestamp=timestamp,
            freshness=0.0, cycle_id=f"S04:{getattr(self.engine.state, 'session_date', None) or 'SESSION'}",
            flash_epoch=self.flash_epoch, raw_reason=None, execution_exit_authority=state == StrategyLifecycleState.MANAGING,
        )
