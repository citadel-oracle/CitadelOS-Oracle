"""
CITADEL Risk Engine — Exit Policy Registry (versioned, configurable).

All policy parameters have an associated ThresholdEntry in thresholds.py.
Parameters labelled UNVALIDATED_DEFAULT or DISABLED are not production-safe.

Exit policies operate exclusively in option-premium-point space.
"""

from __future__ import annotations
import uuid
from typing import Any, Dict, Optional, Tuple
from src.risk_engine.contracts import ExitDecision, ExitAction, RiskPlan


# ─────────────────────────────────────────────────────────────────────────────
# 1. STRUCTURAL_TARGET
#    Exit when price reaches a structural reference target (e.g., bearish VOB).
#    Used by PullbackMaster (target_mode="Bearish VOB").
# ─────────────────────────────────────────────────────────────────────────────

class StructuralTargetPolicy:
    """
    Governance: policy parameters come from strategy PineScript config.
    PullbackMaster rr_target=4.0 is LOCKED_STRATEGY_RULE.
    """
    VERSION = "structural_target_v1"

    def evaluate(
        self,
        plan: RiskPlan,
        current_price: float,
        high: float,
        low: float,
        current_stop: float,
    ) -> Optional[ExitDecision]:
        if not plan.target_ladder:
            return None
        dec_id = f"dec_{uuid.uuid4().hex[:8]}"
        side = plan.side.upper()
        for step in plan.target_ladder:
            hit = (side == "LONG" and high >= step.target_price) or \
                  (side == "SHORT" and low <= step.target_price)
            if hit:
                new_stop = None
                if step.move_stop_to is not None:
                    if side == "LONG":
                        new_stop = max(current_stop, step.move_stop_to)
                    else:
                        new_stop = min(current_stop, step.move_stop_to)
                action = ExitAction.PARTIAL_EXIT if step.exit_ratio < 1.0 else ExitAction.FULL_EXIT
                return ExitDecision(
                    decision_id=dec_id,
                    plan_id=plan.plan_id,
                    strategy_id=plan.strategy_id,
                    action=action,
                    exit_price=step.target_price,
                    exit_ratio=step.exit_ratio,
                    new_stop_price=new_stop,
                    reason=f"STRUCTURAL_TARGET: {step.description or 'target step reached'}",
                    evidence={
                        "policy": self.VERSION,
                        "target_price": step.target_price,
                        "high": high, "low": low,
                    },
                )
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 2. FIXED_R
#    Exit at a fixed R-multiple from entry.
#    Governance: per-strategy rr_target is LOCKED_STRATEGY_RULE; default=None (DISABLED).
# ─────────────────────────────────────────────────────────────────────────────

class FixedRPolicy:
    """
    Parameters:
      r_multiple: float — LOCKED_STRATEGY_RULE per deployment (e.g., 4.0 for PullbackMaster)
                          or None to disable.
    """
    VERSION = "fixed_r_v1"

    def __init__(self, r_multiple: Optional[float] = None):
        # None = DISABLED until per-deployment calibration is supplied
        self.r_multiple = r_multiple

    def evaluate(
        self,
        plan: RiskPlan,
        current_price: float,
        high: float,
        low: float,
        current_stop: float,
    ) -> Optional[ExitDecision]:
        if self.r_multiple is None or plan.is_skipped:
            return None
        entry = plan.entry_price
        risk = abs(entry - plan.effective_stop)
        if risk <= 0:
            return None
        target = entry + risk * self.r_multiple if plan.side.upper() == "LONG" \
            else entry - risk * self.r_multiple
        dec_id = f"dec_{uuid.uuid4().hex[:8]}"
        hit = (plan.side.upper() == "LONG" and high >= target) or \
              (plan.side.upper() == "SHORT" and low <= target)
        if hit:
            return ExitDecision(
                decision_id=dec_id,
                plan_id=plan.plan_id,
                strategy_id=plan.strategy_id,
                action=ExitAction.FULL_EXIT,
                exit_price=target,
                exit_ratio=1.0,
                reason=f"FIXED_R: {self.r_multiple}R target reached",
                evidence={"policy": self.VERSION, "r_multiple": self.r_multiple,
                          "target": target, "risk": risk},
            )
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 3. HYBRID_PARTIAL_RUNNER
#    Partial exit at T1, run remainder to T2 with stop moved to breakeven.
#    Governance: T1/T2 ratios are UNVALIDATED_DEFAULT — not production-safe.
# ─────────────────────────────────────────────────────────────────────────────

class HybridPartialRunnerPolicy:
    """
    Parameters:
      partial_exit_ratio: float  — UNVALIDATED_DEFAULT (default 0.5)
      t1_r: float                — UNVALIDATED_DEFAULT (default 1.5R)
      t2_r: float                — UNVALIDATED_DEFAULT (default 3.0R)
    """
    VERSION = "hybrid_partial_runner_v1"
    GOVERNANCE = "UNVALIDATED_DEFAULT"

    def __init__(
        self,
        partial_exit_ratio: float = 0.5,   # UNVALIDATED_DEFAULT
        t1_r: float = 1.5,                 # UNVALIDATED_DEFAULT
        t2_r: float = 3.0,                 # UNVALIDATED_DEFAULT
        enabled: bool = False,             # DISABLED until calibrated
    ):
        self.partial_exit_ratio = partial_exit_ratio
        self.t1_r = t1_r
        self.t2_r = t2_r
        self.enabled = enabled

    def evaluate(
        self,
        plan: RiskPlan,
        current_price: float,
        high: float,
        low: float,
        current_stop: float,
        bars_held: int = 0,
    ) -> Optional[ExitDecision]:
        if not self.enabled or plan.is_skipped:
            return None
        entry = plan.entry_price
        risk = abs(entry - plan.effective_stop)
        if risk <= 0:
            return None
        dec_id = f"dec_{uuid.uuid4().hex[:8]}"
        t1 = entry + risk * self.t1_r if plan.side.upper() == "LONG" \
            else entry - risk * self.t1_r
        if (plan.side.upper() == "LONG" and high >= t1) or \
           (plan.side.upper() == "SHORT" and low <= t1):
            return ExitDecision(
                decision_id=dec_id,
                plan_id=plan.plan_id,
                strategy_id=plan.strategy_id,
                action=ExitAction.PARTIAL_EXIT,
                exit_price=t1,
                exit_ratio=self.partial_exit_ratio,
                new_stop_price=entry,
                reason=f"HYBRID_PARTIAL_RUNNER: T1 at {self.t1_r}R, stop → breakeven",
                evidence={"policy": self.VERSION, "governance": self.GOVERNANCE,
                          "t1_r": self.t1_r, "t1": t1},
            )
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 4. TRAILING_STRUCTURE
#    Trail stop to new structural highs/lows.
#    Governance: trail_new_bull_ob=True is LOCKED_STRATEGY_RULE for PullbackMaster.
# ─────────────────────────────────────────────────────────────────────────────

class TrailingStructurePolicy:
    """
    Parameters:
      trail_activation_r: float — UNVALIDATED_DEFAULT (0.5R) before trailing begins
    """
    VERSION = "trailing_structure_v1"

    def __init__(self, trail_activation_r: float = 0.5, enabled: bool = True):
        self.trail_activation_r = trail_activation_r  # UNVALIDATED_DEFAULT
        self.enabled = enabled

    def new_stop(
        self,
        plan: RiskPlan,
        current_price: float,
        current_stop: float,
        structural_level: Optional[float],
    ) -> Optional[float]:
        """Returns a new stop if it improves on current_stop, else None."""
        if not self.enabled or structural_level is None:
            return None
        side = plan.side.upper()
        if side == "LONG" and structural_level > current_stop:
            return structural_level
        if side == "SHORT" and structural_level < current_stop:
            return structural_level
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 5. TRAILING_VOLATILITY
#    Trail stop using ATR multiple.
#    Governance: multiplier is UNVALIDATED_DEFAULT until calibrated per deployment.
# ─────────────────────────────────────────────────────────────────────────────

class TrailingVolatilityPolicy:
    """
    Parameters:
      atr_multiplier: float — UNVALIDATED_DEFAULT
    """
    VERSION = "trailing_volatility_v1"
    GOVERNANCE = "UNVALIDATED_DEFAULT"

    def __init__(self, atr_multiplier: float = 1.5, enabled: bool = False):
        self.atr_multiplier = atr_multiplier  # UNVALIDATED_DEFAULT
        self.enabled = enabled

    def new_stop(
        self,
        plan: RiskPlan,
        current_price: float,
        current_stop: float,
        atr: Optional[float],
    ) -> Optional[float]:
        if not self.enabled or atr is None:
            return None
        side = plan.side.upper()
        candidate = current_price - atr * self.atr_multiplier if side == "LONG" \
            else current_price + atr * self.atr_multiplier
        if side == "LONG" and candidate > current_stop:
            return candidate
        if side == "SHORT" and candidate < current_stop:
            return candidate
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 6. LIFECYCLE_EXIT
#    Exit when the option contract approaches expiry (DTE <= threshold).
#    Governance: dte_threshold is UNVALIDATED_DEFAULT.
# ─────────────────────────────────────────────────────────────────────────────

class LifecycleExitPolicy:
    """
    Parameters:
      dte_threshold_days: int — UNVALIDATED_DEFAULT (0 = expire day exit only)
    """
    VERSION = "lifecycle_exit_v1"
    GOVERNANCE = "UNVALIDATED_DEFAULT"

    def __init__(self, dte_threshold_days: int = 0, enabled: bool = False):
        self.dte_threshold_days = dte_threshold_days  # UNVALIDATED_DEFAULT
        self.enabled = enabled

    def evaluate(
        self,
        plan: RiskPlan,
        current_price: float,
        dte: Optional[int],
    ) -> Optional[ExitDecision]:
        if not self.enabled or dte is None:
            return None
        if dte <= self.dte_threshold_days:
            return ExitDecision(
                decision_id=f"dec_{uuid.uuid4().hex[:8]}",
                plan_id=plan.plan_id,
                strategy_id=plan.strategy_id,
                action=ExitAction.DECAY_EXIT,
                exit_price=current_price,
                exit_ratio=1.0,
                reason=f"LIFECYCLE_EXIT: DTE={dte} <= threshold={self.dte_threshold_days}",
                evidence={"policy": self.VERSION, "governance": self.GOVERNANCE, "dte": dte},
            )
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 7. TIME_DECAY_EXIT
#    Exit after a max number of bars in the position.
#    Governance: max_bars is DISABLED for all current strategies (time-based exits used instead).
# ─────────────────────────────────────────────────────────────────────────────

class TimeDecayExitPolicy:
    """
    Parameters:
      max_bars: int — DISABLED (None) for all current NIFTY option strategies.
                      TrendCatcher/BullPulse use IST clock exits.
    """
    VERSION = "time_decay_exit_v1"
    GOVERNANCE = "DISABLED"

    def __init__(self, max_bars: Optional[int] = None, enabled: bool = False):
        self.max_bars = max_bars  # DISABLED
        self.enabled = enabled

    def evaluate(
        self,
        plan: RiskPlan,
        current_price: float,
        bars_held: int,
    ) -> Optional[ExitDecision]:
        if not self.enabled or self.max_bars is None:
            return None
        if bars_held >= self.max_bars:
            return ExitDecision(
                decision_id=f"dec_{uuid.uuid4().hex[:8]}",
                plan_id=plan.plan_id,
                strategy_id=plan.strategy_id,
                action=ExitAction.TIME_EXIT,
                exit_price=current_price,
                exit_ratio=1.0,
                reason=f"TIME_DECAY_EXIT: bars_held={bars_held} >= max={self.max_bars}",
                evidence={"policy": self.VERSION, "governance": self.GOVERNANCE,
                          "bars_held": bars_held, "max_bars": self.max_bars},
            )
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 8. NO_PROGRESS_EXIT
#    Exit if the position shows no progress (MFE < threshold) after N bars.
#    Governance: all parameters are UNVALIDATED_DEFAULT — disabled by default.
# ─────────────────────────────────────────────────────────────────────────────

class NoProgressExitPolicy:
    """
    Parameters:
      min_mfe_r: float         — UNVALIDATED_DEFAULT (0.3R minimum progress)
      check_after_bars: int    — UNVALIDATED_DEFAULT (10 bars)
    """
    VERSION = "no_progress_exit_v1"
    GOVERNANCE = "UNVALIDATED_DEFAULT"

    def __init__(
        self,
        min_mfe_r: float = 0.3,      # UNVALIDATED_DEFAULT
        check_after_bars: int = 10,  # UNVALIDATED_DEFAULT
        enabled: bool = False,
    ):
        self.min_mfe_r = min_mfe_r
        self.check_after_bars = check_after_bars
        self.enabled = enabled

    def evaluate(
        self,
        plan: RiskPlan,
        current_price: float,
        bars_held: int,
        mfe: float,
    ) -> Optional[ExitDecision]:
        if not self.enabled or bars_held < self.check_after_bars:
            return None
        risk = abs(plan.entry_price - plan.effective_stop)
        if risk <= 0:
            return None
        mfe_r = mfe / risk
        if mfe_r < self.min_mfe_r:
            return ExitDecision(
                decision_id=f"dec_{uuid.uuid4().hex[:8]}",
                plan_id=plan.plan_id,
                strategy_id=plan.strategy_id,
                action=ExitAction.NO_PROGRESS_EXIT,
                exit_price=current_price,
                exit_ratio=1.0,
                reason=f"NO_PROGRESS_EXIT: MFE={mfe:.2f}pts ({mfe_r:.2f}R) < min {self.min_mfe_r}R after {bars_held} bars",
                evidence={"policy": self.VERSION, "governance": self.GOVERNANCE,
                          "mfe": mfe, "mfe_r": round(mfe_r, 3), "bars_held": bars_held},
            )
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Composite Exit Policy Registry
# ─────────────────────────────────────────────────────────────────────────────

class ExitPolicyRegistry:
    """
    Evaluates all enabled policies in priority order.
    All premium arithmetic stays in option-premium-point space.
    """

    def __init__(
        self,
        structural_target: Optional[StructuralTargetPolicy] = None,
        fixed_r: Optional[FixedRPolicy] = None,
        hybrid_partial: Optional[HybridPartialRunnerPolicy] = None,
        trailing_structure: Optional[TrailingStructurePolicy] = None,
        trailing_volatility: Optional[TrailingVolatilityPolicy] = None,
        lifecycle_exit: Optional[LifecycleExitPolicy] = None,
        time_decay: Optional[TimeDecayExitPolicy] = None,
        no_progress: Optional[NoProgressExitPolicy] = None,
    ):
        self.structural_target   = structural_target   or StructuralTargetPolicy()
        self.fixed_r             = fixed_r             or FixedRPolicy()
        self.hybrid_partial      = hybrid_partial      or HybridPartialRunnerPolicy()
        self.trailing_structure  = trailing_structure  or TrailingStructurePolicy()
        self.trailing_volatility = trailing_volatility or TrailingVolatilityPolicy()
        self.lifecycle_exit      = lifecycle_exit      or LifecycleExitPolicy()
        self.time_decay          = time_decay          or TimeDecayExitPolicy()
        self.no_progress         = no_progress         or NoProgressExitPolicy()

    @staticmethod
    def _make_id() -> str:
        return f"dec_{uuid.uuid4().hex[:8]}"

    def evaluate_exit(
        self,
        plan: RiskPlan,
        current_price: float,
        high: float,
        low: float,
        current_stop: float,
        bars_held: int = 0,
        current_time: str = "",
        data_quality_ok: bool = True,
        mfe: float = 0.0,
        dte: Optional[int] = None,
        structural_trail_level: Optional[float] = None,
        atr: Optional[float] = None,
    ) -> ExitDecision:
        """
        All prices are option premium points.
        Returns the highest-priority exit decision or HOLD.
        """
        dec_id = self._make_id()

        # 0. Data Quality Exit
        if not data_quality_ok:
            return ExitDecision(
                decision_id=dec_id, plan_id=plan.plan_id,
                strategy_id=plan.strategy_id,
                action=ExitAction.DATA_QUALITY_EXIT,
                exit_price=current_price, exit_ratio=1.0,
                reason="Data quality degraded or stream lost",
                evidence={"data_quality_ok": False},
            )

        if plan.is_skipped:
            return ExitDecision(
                decision_id=dec_id, plan_id=plan.plan_id,
                strategy_id=plan.strategy_id,
                action=ExitAction.HOLD,
                reason=f"Plan skipped: {plan.skip_reason.value}",
                evidence={"skip_details": plan.skip_details},
            )

        side = plan.side.upper()
        entry = plan.entry_price

        # 1. Hard Stop-Loss (monotonic: stop can only move in profit direction after entry)
        if side == "LONG" and low <= current_stop:
            return ExitDecision(
                decision_id=dec_id, plan_id=plan.plan_id,
                strategy_id=plan.strategy_id, action=ExitAction.FULL_EXIT,
                exit_price=current_stop, exit_ratio=1.0,
                reason="Stop loss triggered (premium pts)",
                evidence={"low": low, "current_stop": current_stop, "entry": entry},
            )
        elif side == "SHORT" and high >= current_stop:
            return ExitDecision(
                decision_id=dec_id, plan_id=plan.plan_id,
                strategy_id=plan.strategy_id, action=ExitAction.FULL_EXIT,
                exit_price=current_stop, exit_ratio=1.0,
                reason="Stop loss triggered (premium pts)",
                evidence={"high": high, "current_stop": current_stop, "entry": entry},
            )

        # 2. Lifecycle exit (expiry decay) — checked before target
        lc = self.lifecycle_exit.evaluate(plan, current_price, dte)
        if lc is not None:
            return lc

        # 3. Structural target / target ladder
        st = self.structural_target.evaluate(plan, current_price, high, low, current_stop)
        if st is not None:
            return st

        # 4. Fixed R target
        fr = self.fixed_r.evaluate(plan, current_price, high, low, current_stop)
        if fr is not None:
            return fr

        # 5. Hybrid partial runner
        hp = self.hybrid_partial.evaluate(plan, current_price, high, low, current_stop, bars_held)
        if hp is not None:
            return hp

        # 6. Time decay exit (disabled by default)
        td = self.time_decay.evaluate(plan, current_price, bars_held)
        if td is not None:
            return td

        # 7. No-progress exit (disabled by default)
        np_ = self.no_progress.evaluate(plan, current_price, bars_held, mfe)
        if np_ is not None:
            return np_

        # 8. Default Hold
        return ExitDecision(
            decision_id=dec_id, plan_id=plan.plan_id,
            strategy_id=plan.strategy_id, action=ExitAction.HOLD,
            reason="Position active within risk boundaries",
            evidence={"current_price": current_price, "current_stop": current_stop,
                      "bars_held": bars_held},
        )
