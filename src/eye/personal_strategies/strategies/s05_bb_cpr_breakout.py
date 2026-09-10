"""S05 — OTM1 Option Premium BB-CPR Breakout Evaluator."""

from typing import List, Dict, Any, Optional
from src.eye.personal_strategies.contracts import (
    PersonalStrategyId,
    StrategyLifecycleState,
    PersonalStrategySignal,
)
from src.eye.personal_strategies.indicators import (
    compute_bollinger_bands,
    compute_ema,
    compute_traditional_pivots,
)


class S05Evaluator:
    """Evaluator for S05 — OTM1 OPTION PREMIUM BB–CPR BREAKOUT."""

    def __init__(self, option_type: str = "CE"):
        self.option_type = option_type.upper()
        self.rearm_satisfied: bool = True
        self.flash_epoch: int = 0
        self.last_state: StrategyLifecycleState = StrategyLifecycleState.SCANNING

    def evaluate(
        self,
        option_contract: str,
        bars_3m: List[Dict[str, float]],
        bars_5m: List[Dict[str, float]],
        daily_prev_high: float,
        daily_prev_low: float,
        daily_prev_close: float,
        timestamp_str: str,
        current_quote: float,
        active_position: Optional[Dict[str, Any]] = None,
    ) -> PersonalStrategySignal:
        if len(bars_3m) < 21:
            return self._build_signal(
                state=StrategyLifecycleState.MISSING_DATA,
                contract=option_contract,
                match_count=0,
                satisfied=[],
                missing=["INSUFFICIENT_3M_BARS"],
                next_event="WAIT_FOR_21_BARS",
                timestamp_str=timestamp_str,
            )

        closes_3m = [b["close"] for b in bars_3m]
        curr_close_3m = closes_3m[-1]
        prev_close_3m = closes_3m[-2]

        bb_list = compute_bollinger_bands(closes_3m, period=20, num_std=2.0)
        curr_bb = bb_list[-1]

        pivots = compute_traditional_pivots(daily_prev_high, daily_prev_low, daily_prev_close)
        r1 = pivots["R1"]

        if not curr_bb or not r1:
            return self._build_signal(
                state=StrategyLifecycleState.MISSING_DATA,
                contract=option_contract,
                match_count=0,
                satisfied=[],
                missing=["INDICATOR_COMPUTATION_FAILED"],
                next_event="WAIT_FOR_PIVOTS",
                timestamp_str=timestamp_str,
            )

        # Active Position Check
        if active_position and active_position.get("setup_key") == f"SETUP:S05_{self.option_type}":
            pos_state = active_position.get("guardian_state")
            if pos_state == "CLOSED":
                return self._build_signal(
                    state=StrategyLifecycleState.EXITED,
                    contract=option_contract,
                    match_count=2,
                    satisfied=["POSITION_CLOSED"],
                    missing=[],
                    next_event="REARM_INSIDE_BB_AND_LE_R1",
                    timestamp_str=timestamp_str,
                    raw_reason=active_position.get("exit_reason", "EXITED"),
                )
            return self._build_signal(
                state=StrategyLifecycleState.MANAGING,
                contract=option_contract,
                match_count=2,
                satisfied=["POSITION_ACTIVE"],
                missing=[],
                next_event="GUARDIAN_MONITORING",
                timestamp_str=timestamp_str,
            )

        # Rearm Check
        if not self.rearm_satisfied:
            if curr_close_3m <= curr_bb["upper"] and curr_close_3m <= r1:
                self.rearm_satisfied = True
            else:
                return self._build_signal(
                    state=StrategyLifecycleState.REARMING,
                    contract=option_contract,
                    match_count=0,
                    satisfied=[],
                    missing=["COMPLETED_3M_CLOSE_LE_UPPER_BB_AND_LE_R1"],
                    next_event="REARM_REQUIREMENT",
                    timestamp_str=timestamp_str,
                )

        # Predicate 1: Completed 3m Premium Close > Upper BB
        cond_bb = curr_close_3m > curr_bb["upper"]

        # Predicate 2: Completed 3m Premium Close Crosses Above Daily R1
        cond_r1_cross = prev_close_3m <= r1 and curr_close_3m > r1

        satisfied = []
        missing = []

        if cond_bb:
            satisfied.append("Premium Close > Upper BB")
        else:
            missing.append("Premium Close > Upper BB")

        if cond_r1_cross:
            satisfied.append("Premium Close Crosses Above Daily R1")
        else:
            missing.append("COMPLETED 3M CLOSE CROSS ABOVE R1")

        match_count = len(satisfied)

        if match_count == 2:
            sl_price = round(curr_close_3m - 20.0, 2)
            self.rearm_satisfied = False

            return self._build_signal(
                state=StrategyLifecycleState.DETECTED,
                contract=option_contract,
                match_count=2,
                satisfied=satisfied,
                missing=[],
                next_event="EXECUTION_VERIFICATION",
                timestamp_str=timestamp_str,
                sl_price=sl_price,
                entry_reference=curr_close_3m,
            )

        if match_count == 1:
            return self._build_signal(
                state=StrategyLifecycleState.PARTIAL,
                contract=option_contract,
                match_count=1,
                satisfied=satisfied,
                missing=missing,
                next_event=missing[0],
                timestamp_str=timestamp_str,
            )

        return self._build_signal(
            state=StrategyLifecycleState.SCANNING,
            contract=option_contract,
            match_count=0,
            satisfied=[],
            missing=missing,
            next_event="WAIT_FOR_CPR_R1_BREAKOUT",
            timestamp_str=timestamp_str,
        )

    def _build_signal(
        self,
        state: StrategyLifecycleState,
        contract: str,
        match_count: int,
        satisfied: List[str],
        missing: List[str],
        next_event: str,
        timestamp_str: str,
        sl_price: Optional[float] = None,
        entry_reference: Optional[float] = None,
        blocker: Optional[str] = None,
        raw_reason: Optional[str] = None,
    ) -> PersonalStrategySignal:
        if state != self.last_state:
            self.flash_epoch += 1
            self.last_state = state

        direction = "BUY_CE" if self.option_type == "CE" else "BUY_PE"
        reference = float(entry_reference) if isinstance(entry_reference, (int, float)) else None

        return PersonalStrategySignal(
            signal_id=f"SIG:S05:{self.option_type}:{contract}:{timestamp_str}",
            strategy_id=PersonalStrategyId.S05,
            strategy_name="OTM1 OPTION PREMIUM BB–CPR BREAKOUT",
            short_label="BB–CPR BREAKOUT",
            strategy_version="1.0",
            state=state,
            direction=direction,
            match_count=match_count,
            match_total=2,
            satisfied_conditions=satisfied,
            missing_conditions=missing,
            next_required_event=next_event,
            contract_status="RESOLVED",
            preferred_contract=contract,
            geometry_status="DETERMINISTIC" if sl_price else "ESTABLISHING",
            entry_band={"low": reference, "high": reference} if reference is not None and sl_price is not None else None,
            structural_sl=sl_price,
            informational_targets={"STRUCTURAL_EXIT": sl_price} if sl_price is not None else {},
            risk_status="PENDING" if not blocker else "BLOCKED",
            blocker=blocker,
            execution_status="FAIL_CLOSED",
            event_timestamp=timestamp_str,
            source_timestamp=timestamp_str,
            freshness=0.0,
            cycle_id=f"CYCLE:S05:{self.option_type}:{contract}",
            flash_epoch=self.flash_epoch,
            raw_reason=raw_reason,
            execution_exit_authority=True,
        )
