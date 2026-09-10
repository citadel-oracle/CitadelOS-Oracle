"""
Versioned Risk & Exit Contracts for CITADEL.

UNIT SEPARATION RULE (enforced by UnitSafeOptionContext):
  underlying_price           — NIFTY spot / futures index level (~24_000 range)
  option_premium_entry       — option LTP in premium points (~5–500 range)
  option_premium_stop        — stop expressed in premium points
  option_premium_targets     — target ladder in premium points

Never subtract an underlying index level from an option premium.
If premium translation inputs are unavailable, set translation_confidence = "UNAVAILABLE"
and the service will skip with OPTION_PREMIUM_UNAVAILABLE.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional


class ExitAction(str, Enum):
    HOLD                = "HOLD"
    PARTIAL_EXIT        = "PARTIAL_EXIT"
    MOVE_STOP           = "MOVE_STOP"
    FULL_EXIT           = "FULL_EXIT"
    INVALIDATE          = "INVALIDATE"
    TIME_EXIT           = "TIME_EXIT"
    DECAY_EXIT          = "DECAY_EXIT"
    DATA_QUALITY_EXIT   = "DATA_QUALITY_EXIT"
    NO_PROGRESS_EXIT    = "NO_PROGRESS_EXIT"


class SkipReason(str, Enum):
    NONE                         = "NONE"
    SPREAD_TOO_WIDE              = "SPREAD_TOO_WIDE"
    STOP_UNCALCULABLE            = "STOP_UNCALCULABLE"
    MISSING_STRUCTURAL_INVALIDATION = "MISSING_STRUCTURAL_INVALIDATION"
    STOP_EXCEEDS_RISK_CAP        = "STOP_EXCEEDS_RISK_CAP"
    REWARD_RISK_BELOW_THRESHOLD  = "REWARD_RISK_BELOW_THRESHOLD"
    CONTRACT_STALE_OR_MISSING    = "CONTRACT_STALE_OR_MISSING"
    DATA_QUALITY_DEGRADED        = "DATA_QUALITY_DEGRADED"
    EXPIRY_DECAY_UNACCEPTABLE    = "EXPIRY_DECAY_UNACCEPTABLE"
    ENTRY_EXTENDED               = "ENTRY_EXTENDED"
    OPTION_PREMIUM_UNAVAILABLE   = "OPTION_PREMIUM_UNAVAILABLE"  # underlying-domain strategy
    RISK_ENGINE_DISABLED         = "RISK_ENGINE_DISABLED"
    DUPLICATE_CANDIDATE          = "DUPLICATE_CANDIDATE"


# ─────────────────────────────────────────────────────────────────────────────
# Unit-safe option context
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class UnitSafeOptionContext:
    """
    All pricing inputs, fully domain-separated.
    Never mix underlying_price and option_premium_* in arithmetic.
    """
    # Underlying (index level domain) — contextual only, never used as stop
    underlying_price: Optional[float]               # NIFTY spot at evaluation time
    underlying_structural_invalidation: Optional[float]  # e.g., order block low on spot

    # Option premium domain — all arithmetic must stay in premium points
    option_symbol: Optional[str]                    # e.g., "NIFTY26AUG24400PE"
    option_type: Optional[str]                      # "CE" or "PE"
    option_strike: Optional[float]                  # e.g., 24400.0
    option_expiry: Optional[str]                    # e.g., "2026-08-04"
    option_premium_entry: Optional[float]           # LTP at candidate signal (premium pts)
    option_premium_stop: Optional[float]            # strategy-native stop (premium pts)
    option_premium_target: Optional[float]          # strategy-native target (premium pts) or None
    option_lot_size: Optional[int]                  # e.g., 25 for NIFTY
    option_source_timestamp: Optional[str]          # ISO timestamp of premium observation

    # Translation metadata
    translation_method: str = "STRATEGY_NATIVE_PREMIUM"
    # STRATEGY_NATIVE_PREMIUM — entry/stop/target taken directly from strategy output (premium pts)
    # DELTA_APPROXIMATION     — not implemented; would require Greek inputs
    # UNAVAILABLE             — underlying-domain strategy; no premium translation possible
    translation_confidence: str = "HIGH"
    # HIGH       — directly from option LTP (TrendCatcher, BullPulse)
    # MEDIUM     — strategy-internal calculation (PullbackMaster, BreakoutMain)
    # UNAVAILABLE — underlying-domain strategy (pullback-master-pine-v5)

    def is_premium_available(self) -> bool:
        return (
            self.translation_confidence != "UNAVAILABLE"
            and self.option_premium_entry is not None
            and self.option_premium_entry > 0
        )


# ─────────────────────────────────────────────────────────────────────────────
# Target step in premium points
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TargetStep:
    target_price: float          # premium points
    exit_ratio: float            # e.g., 0.5 for 50%
    move_stop_to: Optional[float] = None  # premium points, or None
    description: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Immutable Risk Plan
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RiskPlan:
    plan_id: str
    strategy_id: str
    deployment_id: str                    # exact deployment lane ID
    instrument: str                       # "NIFTY"
    option_context: Optional[UnitSafeOptionContext]   # None only if no option involved
    # Convenience aliases kept for backward compatibility (mirror option_context values)
    option_symbol: Optional[str]
    side: str                             # "LONG" — all option strategies are long premium
    entry_price: float                    # option premium points (from option_context)
    structural_invalidation: Optional[float]  # premium stop from strategy (option_context.option_premium_stop)
    noise_spread_floor: float             # UNVALIDATED_DEFAULT — shadow only
    volatility_buffer: float              # UNVALIDATED_DEFAULT — shadow only
    effective_stop: float                 # computed by LayeredStopEngine in premium pts
    maximum_risk_cap: float               # UNVALIDATED_DEFAULT — shadow only
    position_size: int
    target_ladder: List[TargetStep]
    trailing_policy: str
    time_decay_policy: str
    lifecycle_exit_policy: str
    is_skipped: bool = False
    skip_reason: SkipReason = SkipReason.NONE
    skip_details: str = ""
    provenance: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = "2.0.0"
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def to_dict(self) -> Dict[str, Any]:
        oc = self.option_context
        return {
            "plan_id": self.plan_id,
            "strategy_id": self.strategy_id,
            "deployment_id": self.deployment_id,
            "instrument": self.instrument,
            "option_symbol": self.option_symbol,
            "side": self.side,
            "entry_price": self.entry_price,
            "structural_invalidation": self.structural_invalidation,
            "noise_spread_floor": self.noise_spread_floor,
            "volatility_buffer": self.volatility_buffer,
            "effective_stop": self.effective_stop,
            "maximum_risk_cap": self.maximum_risk_cap,
            "position_size": self.position_size,
            "target_ladder": [
                {
                    "target_price": t.target_price,
                    "exit_ratio": t.exit_ratio,
                    "move_stop_to": t.move_stop_to,
                    "description": t.description,
                }
                for t in self.target_ladder
            ],
            "trailing_policy": self.trailing_policy,
            "time_decay_policy": self.time_decay_policy,
            "lifecycle_exit_policy": self.lifecycle_exit_policy,
            "is_skipped": self.is_skipped,
            "skip_reason": self.skip_reason.value,
            "skip_details": self.skip_details,
            "provenance": self.provenance,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            # Unit-safe option context detail
            "option_context": {
                "underlying_price": oc.underlying_price if oc else None,
                "underlying_structural_invalidation": oc.underlying_structural_invalidation if oc else None,
                "option_symbol": oc.option_symbol if oc else None,
                "option_type": oc.option_type if oc else None,
                "option_strike": oc.option_strike if oc else None,
                "option_expiry": oc.option_expiry if oc else None,
                "option_premium_entry": oc.option_premium_entry if oc else None,
                "option_premium_stop": oc.option_premium_stop if oc else None,
                "option_premium_target": oc.option_premium_target if oc else None,
                "option_lot_size": oc.option_lot_size if oc else None,
                "translation_method": oc.translation_method if oc else None,
                "translation_confidence": oc.translation_confidence if oc else None,
            } if oc else None,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Exit Decision
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ExitDecision:
    decision_id: str
    plan_id: str
    strategy_id: str
    action: ExitAction
    exit_price: Optional[float] = None     # premium points
    exit_ratio: float = 1.0
    new_stop_price: Optional[float] = None  # premium points
    reason: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "plan_id": self.plan_id,
            "strategy_id": self.strategy_id,
            "action": self.action.value,
            "exit_price": self.exit_price,
            "exit_ratio": self.exit_ratio,
            "new_stop_price": self.new_stop_price,
            "reason": self.reason,
            "evidence": self.evidence,
            "timestamp": self.timestamp,
        }
