"""
Entry Skip & Quality Gates for CITADEL Risk Operating System.

Governance labels per threshold:
  spread gate          — DISABLED (no live bid/ask feed)
  R/R gate             — DISABLED (TrendCatcher/BullPulse have no target; only PB/BO may use)
  extension gate       — DISABLED (conflicts with strategy entry trigger logic)
  stop validity gate   — LOCKED (structural: stop must be calculable)
  data quality gate    — LOCKED (operational safety)
  contract validity    — LOCKED (operational safety)
"""

from __future__ import annotations
from typing import Optional, Tuple
from src.risk_engine.contracts import SkipReason


class QualityGateEvaluator:
    def __init__(
        self,
        # DISABLED gates — set to None to explicitly disable
        max_spread_points: Optional[float] = None,       # DISABLED: no live bid/ask feed
        min_reward_risk_ratio: Optional[float] = None,   # DISABLED: TC/BP have no target
        max_entry_extension_pct: Optional[float] = None, # DISABLED: conflicts with strategy triggers
    ):
        # Explicitly marked disabled — storing them for transparency in audits
        self._max_spread_points = max_spread_points           # DISABLED
        self._min_reward_risk_ratio = min_reward_risk_ratio   # DISABLED
        self._max_entry_extension_pct = max_entry_extension_pct  # DISABLED

    def evaluate_entry_quality(
        self,
        entry_price: float,
        side: str,
        effective_stop: float,
        first_target: Optional[float],
        spread: float = 0.0,
        structural_level: Optional[float] = None,
        data_quality_ok: bool = True,
        is_contract_valid: bool = True,
    ) -> Tuple[bool, SkipReason, str]:
        """
        Evaluates trade entry quality against mandatory risk gates.

        Only LOCKED gates are enforced:
          - Data quality
          - Contract validity
          - Stop calculability (stop must exist and be positive)

        DISABLED gates (spread, R/R, extension) are explicitly bypassed.

        Returns: (is_approved, skip_reason, details)
        """
        # 1. Data Quality Gate — LOCKED_STRATEGY_RULE (operational safety)
        if not data_quality_ok:
            return False, SkipReason.DATA_QUALITY_DEGRADED, "Data quality degraded or missing ticks"

        # 2. Contract Validity Gate — LOCKED (operational safety)
        if not is_contract_valid:
            return False, SkipReason.CONTRACT_STALE_OR_MISSING, "Contract stale, missing or expired"

        # 3. Spread Gate — DISABLED (no live bid/ask feed available)
        #    Would need real-time bid/ask observations per option series.
        #    Passing spread=0.0 in all shadow paths; gate is bypassed.
        #    (Retained for future activation when bid/ask feed is wired.)
        if self._max_spread_points is not None and spread > self._max_spread_points:
            return False, SkipReason.SPREAD_TOO_WIDE, (
                f"[UNVALIDATED_DEFAULT] Spread ({spread:.1f} pts) > max ({self._max_spread_points:.1f} pts)"
            )

        # 4. Stop Validity Gate — LOCKED (structural necessity)
        if effective_stop <= 0:
            return False, SkipReason.STOP_UNCALCULABLE, "Effective stop price is invalid or non-positive"

        stop_dist = abs(entry_price - effective_stop)
        if stop_dist == 0:
            return False, SkipReason.STOP_UNCALCULABLE, "Effective stop distance is zero"

        # 5. Reward/Risk Gate — DISABLED for TrendCatcher/BullPulse (no defined target).
        #    May be re-enabled per deployment with LOCKED_STRATEGY_RULE (PullbackMaster rr=4.0).
        if self._min_reward_risk_ratio is not None and first_target and first_target > 0:
            reward_dist = abs(first_target - entry_price)
            rr_ratio = reward_dist / stop_dist
            if rr_ratio < self._min_reward_risk_ratio:
                return (
                    False,
                    SkipReason.REWARD_RISK_BELOW_THRESHOLD,
                    f"[UNVALIDATED_DEFAULT] R/R {rr_ratio:.2f} < min {self._min_reward_risk_ratio:.2f}",
                )

        # 6. Extension Gate — DISABLED (conflicts with TC 40% / BP 10% momentum triggers)
        if self._max_entry_extension_pct is not None and structural_level and structural_level > 0:
            extension = abs(entry_price - structural_level) / structural_level
            if extension > self._max_entry_extension_pct:
                return (
                    False,
                    SkipReason.ENTRY_EXTENDED,
                    f"[UNVALIDATED_DEFAULT] Entry extended {extension*100:.1f}% > max {self._max_entry_extension_pct*100:.1f}%",
                )

        return True, SkipReason.NONE, "Entry passes active quality gates"
