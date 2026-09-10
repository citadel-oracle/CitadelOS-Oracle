"""S02 — NIFTY Volatile staged, futures-authoritative state machine.

The evaluator deliberately consumes a completed, canonical futures context.  It
does not build bars, resolve contracts, or infer an outcome from a quote.  This
keeps the S02 recovery sequence deterministic and prevents a later candle from
rewriting the branch selected when the Stage-1 loss was confirmed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

from src.eye.personal_strategies.contracts import (
    PersonalStrategyId,
    PersonalStrategySignal,
    StrategyLifecycleState,
)


@dataclass
class S02State:
    session_date: Optional[str] = None
    stage: str = "SCANNING"
    cycle_id: Optional[str] = None
    branch: Optional[str] = None
    stage1_contract: Optional[str] = None
    stage2_contract: Optional[str] = None
    stage4_contract: Optional[str] = None
    last_decision_candle_id: Optional[str] = None
    terminal_reason: Optional[str] = None


class S02Evaluator:
    """Evaluate S02 from supplied completed futures/contract evidence only."""

    SESSION_START = "09:15"
    SESSION_END = "15:25"

    def __init__(self, state: Optional[S02State] = None):
        self.state = state or S02State()
        self.flash_epoch = 0

    def serialize_state(self) -> dict[str, Any]:
        return asdict(self.state)

    def restore_state(self, value: Mapping[str, Any]) -> None:
        self.state = S02State(**dict(value))

    def evaluate(
        self,
        option_contract: Optional[str] = None,
        timestamp_str: str = "09:30:00",
        *,
        context: Optional[Mapping[str, Any]] = None,
    ) -> PersonalStrategySignal:
        """Return the one eligible S02 stage for a completed canonical event.

        ``option_contract`` remains accepted for source compatibility but is not
        used as a fallback.  All tradable contracts must arrive in ``context``
        from the shared OptionUniverseService/canonical resolver.
        """
        if not isinstance(context, Mapping):
            return self._signal(
                StrategyLifecycleState.MISSING_DATA, "BUY_PE", option_contract,
                0, [], ["CANONICAL_FUTURES_CONTEXT"], "WAIT_FOR_COMPLETED_FUTURES_CANDLE",
                timestamp_str, blocker="S02_FUTURES_CONTEXT_UNAVAILABLE",
            )

        timestamp = str(context.get("timestamp") or timestamp_str)
        time_of_day = self._time_of_day(timestamp)
        if time_of_day is None:
            return self._signal(StrategyLifecycleState.MISSING_DATA, "BUY_PE", None, 0, [], ["COMPLETED_CANDLE_TIMESTAMP"], "WAIT_FOR_COMPLETED_FUTURES_CANDLE", timestamp, blocker="S02_TIMESTAMP_INVALID")
        session_date = self._session_date(timestamp)
        if self.state.session_date != session_date:
            self.state = S02State(session_date=session_date)
        if not (self.SESSION_START <= time_of_day <= self.SESSION_END):
            return self._signal(StrategyLifecycleState.BLOCKED, "BUY_PE", None, 0, [], ["SESSION_09_15_TO_15_25"], "SESSION_WINDOW", timestamp, blocker="S02_OUTSIDE_SESSION")

        if context.get("fresh") is not True or context.get("completed") is not True:
            return self._signal(StrategyLifecycleState.MISSING_DATA, "BUY_PE", None, 0, [], ["FRESH_COMPLETED_FUTURES_CANDLE"], "WAIT_FOR_FRESH_COMPLETED_CANDLE", timestamp, blocker="S02_FUTURES_FRESHNESS_UNAVAILABLE")

        daily_pnl = context.get("daily_pnl")
        if isinstance(daily_pnl, (int, float)) and not isinstance(daily_pnl, bool):
            if daily_pnl <= -3800 or daily_pnl >= 3500:
                self.state.terminal_reason = "DAILY_PNL_LIMIT"
                return self._signal(StrategyLifecycleState.BLOCKED, "BUY_PE", None, 0, [], ["DAILY_PNL_WITHIN_LIMIT"], "SESSION_LIMIT_BLOCKED", timestamp, blocker="S02_DAILY_PNL_LIMIT")

        futures = context.get("futures")
        contracts = context.get("nearest_200_contracts")
        if not isinstance(futures, Mapping) or not isinstance(contracts, Mapping):
            return self._signal(StrategyLifecycleState.MISSING_DATA, "BUY_PE", None, 0, [], ["FUTURES_FEATURES", "NEAREST_200_CONTRACTS"], "WAIT_FOR_CANONICAL_CONTEXT", timestamp, blocker="S02_CANONICAL_CONTEXT_INCOMPLETE")

        # A Stage-1 loss is authoritative only when tied to this exact completed
        # decision candle.  The branch is set once, atomically, and never changed.
        stage1_outcome = context.get("stage1_outcome")
        if self.state.stage == "STAGE1_ACTIVE" and isinstance(stage1_outcome, Mapping):
            if str(stage1_outcome.get("result") or "").upper() == "LOSS":
                candle_id = str(stage1_outcome.get("decision_candle_id") or "")
                if not candle_id or candle_id != str(context.get("decision_candle_id") or ""):
                    return self._signal(StrategyLifecycleState.MISSING_DATA, "BUY_PE", self.state.stage1_contract, 1, ["STAGE1_LOSS"], ["SAME_COMPLETED_DECISION_CANDLE"], "WAIT_FOR_STAGE1_LOSS_CANDLE", timestamp, blocker="S02_STAGE1_LOSS_CANDLE_MISMATCH")
                if self.state.last_decision_candle_id != candle_id:
                    self.state.last_decision_candle_id = candle_id
                    # The branch belongs to the completed NIFTY Futures candle,
                    # not to an outcome annotation.  This prevents a later or
                    # unrelated S1 cross from changing the loss-cycle choice.
                    fresh_cross_below_s1 = bool(futures.get("fresh_cross_below_daily_cpr_s1"))
                    self.state.branch = "STAGE4" if fresh_cross_below_s1 else "STAGE2"
                    self.state.stage = f"{self.state.branch}_ACTIVE"
                    chosen = self._contract(contracts, "PE" if self.state.branch == "STAGE4" else "CE")
                    if self.state.branch == "STAGE4":
                        self.state.stage4_contract = chosen
                    else:
                        self.state.stage2_contract = chosen
                    return self._stage_signal(self.state.branch, chosen, timestamp)

        if self.state.stage == "STAGE2_ACTIVE":
            stage2_outcome = context.get("stage2_outcome")
            if isinstance(stage2_outcome, Mapping) and str(stage2_outcome.get("result") or "").upper() == "LOSS":
                if bool(futures.get("fresh_cross_above_3m_supertrend_10_2")):
                    self.state.stage = "STAGE3_ACTIVE"
                    contract = self._contract(contracts, "CE")
                    return self._stage_signal("STAGE3", contract, timestamp)
                return self._signal(StrategyLifecycleState.PARTIAL, "BUY_CE", self.state.stage2_contract, 1, ["STAGE2_CE_LOSS"], ["FRESH_3M_SUPERTREND_CROSS_ABOVE"], "WAIT_FOR_3M_ST_CROSS_ABOVE", timestamp)
            return self._stage_signal("STAGE2", self.state.stage2_contract, timestamp, managing=True)

        if self.state.stage == "STAGE4_ACTIVE":
            return self._stage_signal("STAGE4", self.state.stage4_contract, timestamp, managing=True)

        if self.state.stage == "STAGE3_ACTIVE":
            if bool(futures.get("fresh_cross_below_3m_supertrend_10_2")):
                self.state.stage = "EXITED"
                self.state.terminal_reason = "STAGE3_3M_SUPERTREND_CROSS_BELOW"
                return self._signal(StrategyLifecycleState.EXITED, "BUY_CE", self._contract(contracts, "CE"), 1, ["STAGE3_EXIT_CROSS_BELOW"], [], "SESSION_COMPLETE", timestamp)
            return self._stage_signal("STAGE3", self._contract(contracts, "CE"), timestamp, managing=True)

        if self.state.stage == "EXITED":
            return self._signal(StrategyLifecycleState.EXITED, "BUY_CE", None, 0, [self.state.terminal_reason or "TERMINAL"], [], "SESSION_COMPLETE", timestamp)

        requirements = {
            "close": futures.get("close"),
            "bb_middle_5m": futures.get("bb_middle_5m"),
            "supertrend_15m_10_2": futures.get("supertrend_15m_10_2"),
            "daily_cpr_s1": futures.get("daily_cpr_s1"),
        }
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in requirements.values()):
            return self._signal(StrategyLifecycleState.MISSING_DATA, "BUY_PE", None, 0, [], [key for key, value in requirements.items() if not isinstance(value, (int, float)) or isinstance(value, bool)], "WAIT_FOR_FUTURES_FEATURES", timestamp, blocker="S02_FUTURES_FEATURES_UNAVAILABLE")
        close = float(requirements["close"])
        predicates = [
            close < float(requirements["bb_middle_5m"]),
            close < float(requirements["supertrend_15m_10_2"]),
            close < float(requirements["daily_cpr_s1"]),
        ]
        contract = self._contract(contracts, "PE")
        if contract is None:
            return self._signal(StrategyLifecycleState.MISSING_DATA, "BUY_PE", None, sum(predicates), ["FUTURES_STAGE1_PREDICATES"], ["CURRENT_WEEK_PE_NEAREST_200"], "WAIT_FOR_CONTRACT", timestamp, blocker="S02_NEAREST_200_PE_UNAVAILABLE")
        if all(predicates):
            self.state.stage = "STAGE1_ACTIVE"
            self.state.cycle_id = f"S02:{session_date}:{context.get('decision_candle_id') or timestamp}"
            self.state.stage1_contract = contract
            return self._stage_signal("STAGE1", contract, timestamp)
        return self._signal(StrategyLifecycleState.PARTIAL if any(predicates) else StrategyLifecycleState.SCANNING, "BUY_PE", contract, sum(predicates), [label for label, ok in zip(["CLOSE_BELOW_5M_BB_MIDDLE", "CLOSE_BELOW_15M_ST_10_2", "CLOSE_BELOW_DAILY_CPR_S1"], predicates) if ok], [label for label, ok in zip(["CLOSE_BELOW_5M_BB_MIDDLE", "CLOSE_BELOW_15M_ST_10_2", "CLOSE_BELOW_DAILY_CPR_S1"], predicates) if not ok], "WAIT_FOR_STAGE1_ALIGNMENT", timestamp)

    @staticmethod
    def _contract(contracts: Mapping[str, Any], side: str) -> Optional[str]:
        value = contracts.get(side)
        if isinstance(value, Mapping):
            candidate = value.get("security_id") or value.get("contract") or value.get("trading_symbol")
            return str(candidate) if candidate else None
        return str(value) if value else None

    def _stage_signal(self, stage: str, contract: Optional[str], timestamp: str, managing: bool = False) -> PersonalStrategySignal:
        if not contract:
            return self._signal(StrategyLifecycleState.MISSING_DATA, "BUY_PE" if stage in {"STAGE1", "STAGE4"} else "BUY_CE", None, 0, [], ["AUTHORIZED_NEAREST_200_CONTRACT"], "WAIT_FOR_CONTRACT", timestamp, blocker="S02_CONTRACT_UNAVAILABLE")
        config = {
            "STAGE1": ("BUY_PE", 1, 15.0, 30.0, {}),
            "STAGE2": ("BUY_CE", 2, 15.0, 25.0, {"trailing_trigger": 10.0, "trailing_step": 10.0}),
            "STAGE3": ("BUY_CE", 2, 15.0, None, {"exit": "FUTURES_3M_ST_10_2_CROSS_BELOW"}),
            "STAGE4": ("BUY_PE", 2, 15.0, 25.0, {"trailing_trigger": 15.0, "trailing_step": 15.0}),
        }[stage]
        direction, lots, sl, target, extra = config
        state = StrategyLifecycleState.MANAGING if managing else StrategyLifecycleState.DETECTED
        return self._signal(state, direction, contract, 4, [stage, "FUTURES_AUTHORITY", "CURRENT_WEEK_NEAREST_200", "BRANCH_LOCKED"], [], "GUARDIAN_MANAGEMENT" if managing else "RISK_AND_ANALYZER_VERIFICATION", timestamp, entry_band=None, structural_sl=sl, targets={"target_points": target, "lots": lots, **extra})

    def _signal(self, state: StrategyLifecycleState, direction: str, contract: Optional[str], match_count: int, satisfied: list[str], missing: list[str], next_event: str, timestamp: str, *, blocker: Optional[str] = None, entry_band: Optional[dict[str, float]] = None, structural_sl: Optional[float] = None, targets: Optional[dict[str, Any]] = None) -> PersonalStrategySignal:
        if getattr(self, "_last_state", None) != state:
            self.flash_epoch += 1
            self._last_state = state
        cycle = self.state.cycle_id or f"S02:{self.state.session_date or 'UNKNOWN'}"
        return PersonalStrategySignal(
            signal_id=f"SIG:{cycle}:{self.state.stage}:{timestamp}", strategy_id=PersonalStrategyId.S02,
            strategy_name="NIFTY VOLATILE", short_label="NIFTY VOLATILE", strategy_version="1.1",
            state=state, direction=direction, match_count=match_count, match_total=4,
            satisfied_conditions=satisfied, missing_conditions=missing, next_required_event=next_event,
            contract_status="RESOLVED" if contract else "UNRESOLVED", preferred_contract=contract,
            geometry_status="CANONICAL" if structural_sl is not None else "ESTABLISHING", entry_band=entry_band,
            structural_sl=structural_sl, informational_targets=targets or {},
            risk_status="BLOCKED" if blocker else "PENDING", blocker=blocker,
            execution_status="FAIL_CLOSED", event_timestamp=timestamp, source_timestamp=timestamp,
            freshness=0.0, cycle_id=cycle, flash_epoch=self.flash_epoch,
            raw_reason=self.state.branch or self.state.stage, execution_exit_authority=state == StrategyLifecycleState.MANAGING,
        )

    @staticmethod
    def _time_of_day(value: str) -> Optional[str]:
        try:
            if "T" in value:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Kolkata")).strftime("%H:%M")
            return value[-8:-3]
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _session_date(value: str) -> str:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
        except (TypeError, ValueError):
            return "SESSION"
