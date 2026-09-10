"""S01 — OTM1 CE Premium BB-RSI Momentum Breakout Evaluator."""

from typing import List, Dict, Any, Optional
from src.eye.personal_strategies.contracts import (
    PersonalStrategyId,
    StrategyLifecycleState,
    PersonalStrategySignal,
)
from src.eye.personal_strategies.indicators import (
    compute_rsi,
    compute_bollinger_bands,
)


class S01Evaluator:
    """Evaluator for S01 — OTM1 CE PREMIUM BB–RSI MOMENTUM BREAKOUT."""

    def __init__(self):
        self.cycle_locked_contract: Optional[str] = None
        self.rearm_satisfied: bool = True
        self.flash_epoch: int = 0
        self.last_state: StrategyLifecycleState = StrategyLifecycleState.SCANNING

    def evaluate(
        self,
        option_contract: str,
        bars_3m: List[Dict[str, float]],
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

        closes = [b["close"] for b in bars_3m]
        lows = [b["low"] for b in bars_3m]

        bb_list = compute_bollinger_bands(closes, period=20, num_std=2.0)
        rsi_list = compute_rsi(closes, period=14)

        curr_close = closes[-1]
        curr_low = lows[-1]
        curr_bb = bb_list[-1]
        curr_rsi = rsi_list[-1]
        prev_rsi = rsi_list[-2]

        if not curr_bb or curr_rsi is None or prev_rsi is None:
            return self._build_signal(
                state=StrategyLifecycleState.MISSING_DATA,
                contract=option_contract,
                match_count=0,
                satisfied=[],
                missing=["INDICATOR_COMPUTATION_FAILED"],
                next_event="WAIT_FOR_INDICATOR",
                timestamp_str=timestamp_str,
            )

        # Check Active Managing / Exited
        if active_position and active_position.get("setup_key") == "SETUP:S01":
            pos_state = active_position.get("guardian_state")
            if pos_state == "CLOSED":
                return self._build_signal(
                    state=StrategyLifecycleState.EXITED,
                    contract=option_contract,
                    match_count=2,
                    satisfied=["POSITION_CLOSED"],
                    missing=[],
                    next_event="REARM_INSIDE_BB",
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

        # Check Rearm State
        if not self.rearm_satisfied:
            if curr_close <= curr_bb["upper"] and curr_rsi <= 65.0:
                self.rearm_satisfied = True
            else:
                return self._build_signal(
                    state=StrategyLifecycleState.REARMING,
                    contract=option_contract,
                    match_count=0,
                    satisfied=[],
                    missing=["COMPLETED_3M_CLOSE_INSIDE_UPPER_BB_AND_RSI_LE_65"],
                    next_event="REARM_REQUIREMENT",
                    timestamp_str=timestamp_str,
                )

        # Predicate 1: Premium Close > Upper BB(20,2)
        cond_bb = curr_close > curr_bb["upper"]

        # Predicate 2: RSI(14) crosses above 65
        cond_rsi_cross = prev_rsi <= 65.0 and curr_rsi > 65.0

        satisfied = []
        missing = []

        if cond_bb:
            satisfied.append("Premium Close > Upper BB(20,2)")
        else:
            missing.append("Premium Close > Upper BB(20,2)")

        if cond_rsi_cross:
            satisfied.append("RSI(14) Crosses Above 65")
        else:
            missing.append("COMPLETED 3M RSI CROSS > 65")

        match_count = len(satisfied)

        if match_count == 2:
            # Entry confirmed on completed bar
            sl_price = round(curr_low - 0.05, 2)
            risk_pts = round(curr_close - sl_price, 2)

            if risk_pts > 30.0:
                return self._build_signal(
                    state=StrategyLifecycleState.BLOCKED,
                    contract=option_contract,
                    match_count=2,
                    satisfied=satisfied,
                    missing=[],
                    next_event="RISK_GT_30_BLOCKED",
                    timestamp_str=timestamp_str,
                    sl_price=sl_price,
                    blocker="STRUCTURAL_RISK_GT_30",
                    raw_reason="Structural risk exceeds 30 premium points limit.",
                )

            # Contract Lock
            self.cycle_locked_contract = option_contract
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
                entry_reference=curr_close,
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
            next_event="WAIT_FOR_BREAKOUT",
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

        reference = float(entry_reference) if isinstance(entry_reference, (int, float)) else None
        risk_pts = round(abs(reference - sl_price), 2) if reference is not None and sl_price is not None else None
        info_targets = (
            {
                "T1_1R": round(reference + risk_pts, 2),
                "T2_2R": round(reference + (2 * risk_pts), 2),
                "T3_3R": round(reference + (3 * risk_pts), 2),
            }
            if reference is not None and risk_pts is not None
            else {}
        )

        return PersonalStrategySignal(
            signal_id=f"SIG:S01:{contract}:{timestamp_str}",
            strategy_id=PersonalStrategyId.S01,
            strategy_name="OTM1 CE PREMIUM BB–RSI MOMENTUM BREAKOUT",
            short_label="BB–RSI MOMENTUM",
            strategy_version="1.0",
            state=state,
            direction="BUY_CE",
            match_count=match_count,
            match_total=2,
            satisfied_conditions=satisfied,
            missing_conditions=missing,
            next_required_event=next_event,
            contract_status="LOCKED" if self.cycle_locked_contract else "RESOLVED",
            preferred_contract=contract,
            geometry_status="DETERMINISTIC" if sl_price else "ESTABLISHING",
            entry_band={"low": reference, "high": reference} if reference is not None and sl_price is not None else None,
            structural_sl=sl_price,
            informational_targets=info_targets,
            risk_status="PENDING" if not blocker else "BLOCKED",
            blocker=blocker,
            execution_status="FAIL_CLOSED",
            event_timestamp=timestamp_str,
            source_timestamp=timestamp_str,
            freshness=0.0,
            cycle_id=f"CYCLE:S01:{contract}",
            flash_epoch=self.flash_epoch,
            raw_reason=raw_reason,
            execution_exit_authority=False,
        )
