"""
Deterministic Exit Simulator for CITADEL.
"""

from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional
from src.risk_engine.contracts import ExitDecision, ExitAction, RiskPlan, TargetStep
from src.risk_engine.exit_policies import ExitPolicyRegistry


class DeterministicExitSimulator:
    def __init__(self, slippage_points: float = 0.5, spread_points: float = 1.0):
        self.slippage_points = slippage_points
        self.spread_points = spread_points
        self._exit_policy = ExitPolicyRegistry()

    def simulate_trade_exit(
        self,
        plan: RiskPlan,
        candles: List[Dict[str, Any]],
        start_index: int = 0,
    ) -> Dict[str, Any]:
        """
        Simulates exit progression chronologically without look-ahead.

        Handles same-bar stop/target ambiguity conservatively (stop hit first).
        """
        if plan.is_skipped:
            return {
                "plan_id": plan.plan_id,
                "strategy_id": plan.strategy_id,
                "status": "SKIPPED",
                "skip_reason": plan.skip_reason.value,
                "skip_details": plan.skip_details,
                "decisions": [],
                "final_outcome": "SKIPPED",
                "realized_r": 0.0,
                "mfe": 0.0,
                "mae": 0.0,
            }

        entry_price = plan.entry_price
        current_stop = plan.effective_stop
        side = plan.side.upper()
        initial_risk = abs(entry_price - current_stop)
        if initial_risk <= 0:
            initial_risk = 1.0

        mfe = 0.0
        mae = 0.0
        decisions: List[ExitDecision] = []
        final_outcome = "NEITHER"
        realized_r = 0.0

        for idx, candle in enumerate(candles[start_index:], start=1):
            high = float(candle.get("high", entry_price))
            low = float(candle.get("low", entry_price))
            close = float(candle.get("close", entry_price))

            # MFE / MAE tracking
            if side == "LONG":
                bar_mfe = max(0.0, high - entry_price)
                bar_mae = max(0.0, entry_price - low)
            else:
                bar_mfe = max(0.0, entry_price - low)
                bar_mae = max(0.0, high - entry_price)

            mfe = max(mfe, bar_mfe)
            mae = max(mae, bar_mae)

            # Same-bar ambiguity check: If both stop & target are touched on same bar, assume STOP hit first conservatively!
            target_touched = False
            if plan.target_ladder:
                first_target = plan.target_ladder[0].target_price
                if (side == "LONG" and high >= first_target) or (side == "SHORT" and low <= first_target):
                    target_touched = True

            stop_touched = False
            if (side == "LONG" and low <= current_stop) or (side == "SHORT" and high >= current_stop):
                stop_touched = True

            if stop_touched and target_touched:
                # Conservative resolution: STOP HIT FIRST
                exit_p = current_stop - self.slippage_points if side == "LONG" else current_stop + self.slippage_points
                dec = ExitDecision(
                    decision_id=f"dec_{uuid.uuid4().hex[:8]}",
                    plan_id=plan.plan_id,
                    strategy_id=plan.strategy_id,
                    action=ExitAction.FULL_EXIT,
                    exit_price=exit_p,
                    reason="Same-bar stop/target ambiguity resolved conservatively to STOP",
                    evidence={"same_bar_ambiguity": True, "bar": idx},
                )
                decisions.append(dec)
                final_outcome = "STOP_FIRST"
                realized_r = (exit_p - entry_price) / initial_risk if side == "LONG" else (entry_price - exit_p) / initial_risk
                break

            # Standard evaluation
            dec = self._exit_policy.evaluate_exit(
                plan=plan,
                current_price=close,
                high=high,
                low=low,
                current_stop=current_stop,
                bars_held=idx,
            )

            if dec.action != ExitAction.HOLD:
                decisions.append(dec)
                if dec.new_stop_price:
                    # Enforce monotonic stop movement
                    if side == "LONG":
                        current_stop = max(current_stop, dec.new_stop_price)
                    else:
                        current_stop = min(current_stop, dec.new_stop_price)

                if dec.action in (ExitAction.FULL_EXIT, ExitAction.TIME_EXIT, ExitAction.DATA_QUALITY_EXIT, ExitAction.DECAY_EXIT, ExitAction.NO_PROGRESS_EXIT):
                    exit_p = dec.exit_price or close
                    reason_str = dec.reason.upper()
                    if "STRUCTURAL_TARGET" in reason_str or "FIXED_R" in reason_str or "HYBRID_PARTIAL" in reason_str:
                        final_outcome = "TARGET_FIRST"
                    elif "STOP" in reason_str:
                        final_outcome = "STOP_FIRST"
                    elif "TIME" in reason_str:
                        final_outcome = "TIME_EXIT"
                    elif "DECAY" in reason_str or "LIFECYCLE" in reason_str:
                        final_outcome = "DECAY_EXIT"
                    else:
                        final_outcome = "LIFECYCLE_EXIT"
                    realized_r = (exit_p - entry_price) / initial_risk if side == "LONG" else (entry_price - exit_p) / initial_risk
                    break

        return {
            "plan_id": plan.plan_id,
            "strategy_id": plan.strategy_id,
            "status": "COMPLETED",
            "decisions": [d.to_dict() for d in decisions],
            "final_outcome": final_outcome,
            "realized_r": round(realized_r, 4),
            "mfe": round(mfe, 2),
            "mae": round(mae, 2),
            "mfe_r": round(mfe / initial_risk, 4),
            "mae_r": round(mae / initial_risk, 4),
        }
