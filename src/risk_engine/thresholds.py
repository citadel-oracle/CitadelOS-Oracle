"""
CITADEL Risk Engine — Threshold Governance Registry.

Every parameter is declared with its governance class:
  - LOCKED_STRATEGY_RULE : derived from real strategy Pine source or verified live rule
  - UNVALIDATED_DEFAULT  : placeholder pending live calibration — disabled from decision use
  - DISABLED             : feature not yet calibrated; explicitly excluded from risk decisions

NO governance value should be used as production policy unless its class is
LOCKED_STRATEGY_RULE and the associated calibration evidence is cited.
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class GovernanceClass(str, Enum):
    LOCKED_STRATEGY_RULE = "LOCKED_STRATEGY_RULE"   # approved, calibrated, from real strategy
    UNVALIDATED_DEFAULT  = "UNVALIDATED_DEFAULT"     # placeholder; NOT production-safe
    DISABLED             = "DISABLED"                # feature off; value ignored in runtime


@dataclass(frozen=True)
class ThresholdEntry:
    name: str
    value: Any
    governance: GovernanceClass
    unit: str
    source: str
    calibration_note: str


# ─────────────────────────────────────────────────────────────────────────────
# Threshold Registry
# ─────────────────────────────────────────────────────────────────────────────
THRESHOLD_REGISTRY: list[ThresholdEntry] = [

    # ── Stop Engine ──────────────────────────────────────────────────────────

    ThresholdEntry(
        name="atr_volatility_multiplier",
        value=0.5,
        governance=GovernanceClass.UNVALIDATED_DEFAULT,
        unit="multiplier",
        source="risk_engine/stop_engine.py",
        calibration_note="Not calibrated against live NIFTY option premium volatility. "
                         "Must not gate real entries.",
    ),
    ThresholdEntry(
        name="noise_spread_floor_premium",
        value=5.0,
        governance=GovernanceClass.UNVALIDATED_DEFAULT,
        unit="option_premium_points",
        source="risk_engine/service.py",
        calibration_note="Flat Rs 5 floor is a placeholder. Real bid/ask spread varies "
                         "0.5–15 pts intraday. Require live spread observation before using.",
    ),
    ThresholdEntry(
        name="max_risk_pct_per_trade",
        value=2.0,
        governance=GovernanceClass.UNVALIDATED_DEFAULT,
        unit="percent_of_entry_premium",
        source="risk_engine/service.py",
        calibration_note="2% cap is a placeholder. TrendCatcher/BullPulse use fixed Rs "
                         "point stops, not percentage. Require per-strategy mapping.",
    ),

    # ── Quality Gates ─────────────────────────────────────────────────────────

    ThresholdEntry(
        name="spread_too_wide_pct",
        value=None,
        governance=GovernanceClass.DISABLED,
        unit="percent_of_premium",
        source="risk_engine/quality_gates.py",
        calibration_note="Disabled: no live bid/ask feed. Cannot gate without real spread data.",
    ),
    ThresholdEntry(
        name="min_reward_risk_ratio",
        value=None,
        governance=GovernanceClass.DISABLED,
        unit="ratio",
        source="risk_engine/quality_gates.py",
        calibration_note="Disabled: TrendCatcher and BullPulse have no defined target. "
                         "R/R gate only applicable to PullbackMaster (rr_target=4.0) and "
                         "BreakoutMain. Require per-deployment mapping.",
    ),
    ThresholdEntry(
        name="entry_extension_pct",
        value=None,
        governance=GovernanceClass.DISABLED,
        unit="percent_of_premium_from_reference",
        source="risk_engine/quality_gates.py",
        calibration_note="Disabled: 3% was invented default. TrendCatcher uses 40% "
                         "momentum trigger. BullPulse uses 10%. Extension gate would "
                         "conflict with strategy entry logic.",
    ),

    # ── Exit Policies ────────────────────────────────────────────────────────

    ThresholdEntry(
        name="max_hold_bars_tc_bp",
        value=None,
        governance=GovernanceClass.DISABLED,
        unit="bars",
        source="risk_engine/exit_policies.py",
        calibration_note="Disabled: TrendCatcher exits at 15:15 IST; BullPulse at 15:00 IST. "
                         "Time exits are managed by strategy, not bar count.",
    ),
    ThresholdEntry(
        name="max_hold_bars_pb_bo",
        value=None,
        governance=GovernanceClass.DISABLED,
        unit="bars",
        source="risk_engine/exit_policies.py",
        calibration_note="Disabled: 75-bar default was invented. PullbackMaster uses "
                         "1515-1530 square-off session. Require per-strategy mapping.",
    ),

    # ── Locked strategy parameters (from Pine source) ─────────────────────────

    ThresholdEntry(
        name="tc_leg_stop_loss_value",
        value=15.0,
        governance=GovernanceClass.LOCKED_STRATEGY_RULE,
        unit="option_premium_points",
        source="strategy_lab/strategies/trend_catcher/strategy.py:config.leg_stop_loss_value",
        calibration_note="TrendCatcher stops 15 pts below theoretical entry. "
                         "10-for-10 trailing applies above. From verified Pine source.",
    ),
    ThresholdEntry(
        name="tc_overall_stop_loss_value",
        value=1000.0,
        governance=GovernanceClass.LOCKED_STRATEGY_RULE,
        unit="INR_pnl",
        source="strategy_lab/strategies/trend_catcher/strategy.py:config.overall_stop_loss_value",
        calibration_note="TrendCatcher max loss Rs 1000 per day. From verified Pine source.",
    ),
    ThresholdEntry(
        name="bp_leg_stop_loss_pct",
        value=20.0,
        governance=GovernanceClass.LOCKED_STRATEGY_RULE,
        unit="percent_of_entry_premium",
        source="strategy_lab/strategies/bull_pulse/strategy.py:config.leg_stop_loss_pct",
        calibration_note="BullPulse stops 20% below fill premium. From verified Pine source.",
    ),
    ThresholdEntry(
        name="bp_overall_stop_loss_value",
        value=1200.0,
        governance=GovernanceClass.LOCKED_STRATEGY_RULE,
        unit="INR_pnl",
        source="strategy_lab/strategies/bull_pulse/strategy.py:config.overall_stop_loss_value",
        calibration_note="BullPulse max loss Rs 1200 per day. From verified Pine source.",
    ),
    ThresholdEntry(
        name="pb_rr_target",
        value=4.0,
        governance=GovernanceClass.LOCKED_STRATEGY_RULE,
        unit="ratio",
        source="strategy_lab/strategies/pullback_master/deployment.py:parameters.default_fixed_rr",
        calibration_note="PullbackMaster targets 4R. From verified Pine source.",
    ),
    ThresholdEntry(
        name="tc_exit_time_ist",
        value="15:15",
        governance=GovernanceClass.LOCKED_STRATEGY_RULE,
        unit="HH:MM_IST",
        source="strategy_lab/strategies/trend_catcher/strategy.py:config.exit_time",
        calibration_note="TrendCatcher forced square-off at 15:15 IST.",
    ),
    ThresholdEntry(
        name="bp_exit_time_ist",
        value="15:00",
        governance=GovernanceClass.LOCKED_STRATEGY_RULE,
        unit="HH:MM_IST",
        source="strategy_lab/strategies/bull_pulse/strategy.py:config.exit_time",
        calibration_note="BullPulse forced square-off at 15:00 IST.",
    ),

    # ── ATR multipliers ───────────────────────────────────────────────────────

    ThresholdEntry(
        name="pb_supertrend_factor",
        value=2.8,
        governance=GovernanceClass.LOCKED_STRATEGY_RULE,
        unit="multiplier",
        source="strategy_lab/strategies/pullback_master/strategy.py:PullbackMasterConfig.supertrend_factor",
        calibration_note="PullbackMaster Supertrend trailing: factor=2.8, ATR period=8.",
    ),
    ThresholdEntry(
        name="bo_supertrend_factor",
        value=3.0,
        governance=GovernanceClass.LOCKED_STRATEGY_RULE,
        unit="multiplier",
        source="strategy_lab/strategies/breakout_main/strategy.py:BreakoutMainConfig.supertrend_factor",
        calibration_note="BreakoutMain Supertrend trailing: factor=3.0, ATR period=10.",
    ),
]


def get_threshold(name: str) -> ThresholdEntry | None:
    for t in THRESHOLD_REGISTRY:
        if t.name == name:
            return t
    return None


def locked_thresholds() -> list[ThresholdEntry]:
    return [t for t in THRESHOLD_REGISTRY if t.governance == GovernanceClass.LOCKED_STRATEGY_RULE]


def unvalidated_thresholds() -> list[ThresholdEntry]:
    return [t for t in THRESHOLD_REGISTRY if t.governance == GovernanceClass.UNVALIDATED_DEFAULT]


def disabled_thresholds() -> list[ThresholdEntry]:
    return [t for t in THRESHOLD_REGISTRY if t.governance == GovernanceClass.DISABLED]
