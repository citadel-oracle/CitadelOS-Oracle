"""
CITADEL Risk Engine — Authoritative Strategy Inventory.

Derived exclusively from option_deployments.OPTION_CHART_DEPLOYMENTS and the
pullback-master-pine-v5 underlying deployment.  Never invented.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class DeploymentLane:
    deployment_id: str
    strategy_class: str        # PULLBACK / BREAKOUT / TREND_CATCHER / BULL_PULSE
    option_side: str           # CE or PE
    timeframe: str             # 1m or 3m
    underlying: str            # NIFTY
    mode: str                  # SHADOW / PAPER / OFF
    premium_domain: bool       # True — all entry/stop/target are option-premium points
    underlying_domain: bool    # False — no underlying index levels used as stops
    risk_engine_enabled: bool  # per-lane shadow flag (default ON for SHADOW/PAPER)
    note: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Canonical 12-lane inventory sourced from option_deployments.py
# Plus 1 underlying lane (pullback-master-pine-v5 runs on 5m NIFTY spot bars)
# ─────────────────────────────────────────────────────────────────────────────
AUTHORITATIVE_LANES: List[DeploymentLane] = [
    # Pullback Master — option chart lanes
    DeploymentLane("PB_NIFTY_CE_1M", "PULLBACK", "CE", "1m", "NIFTY", "PAPER",  True, False, True),
    DeploymentLane("PB_NIFTY_CE_3M", "PULLBACK", "CE", "3m", "NIFTY", "PAPER",  True, False, True),
    DeploymentLane("PB_NIFTY_PE_1M", "PULLBACK", "PE", "1m", "NIFTY", "PAPER",  True, False, True),
    DeploymentLane("PB_NIFTY_PE_3M", "PULLBACK", "PE", "3m", "NIFTY", "PAPER",  True, False, True),
    # Breakout Main — option chart lanes
    DeploymentLane("BO_NIFTY_CE_1M", "BREAKOUT", "CE", "1m", "NIFTY", "PAPER",  True, False, True),
    DeploymentLane("BO_NIFTY_CE_3M", "BREAKOUT", "CE", "3m", "NIFTY", "PAPER",  True, False, True),
    DeploymentLane("BO_NIFTY_PE_1M", "BREAKOUT", "PE", "1m", "NIFTY", "PAPER",  True, False, True),
    DeploymentLane("BO_NIFTY_PE_3M", "BREAKOUT", "PE", "3m", "NIFTY", "PAPER",  True, False, True),
    # Trend Catcher — 1m SHADOW, 3m OFF
    DeploymentLane("TC_NIFTY_PE_1M", "TREND_CATCHER", "PE", "1m", "NIFTY", "SHADOW", True, False, True),
    DeploymentLane("TC_NIFTY_PE_3M", "TREND_CATCHER", "PE", "3m", "NIFTY", "OFF",    True, False, False,
                   note="MODE=OFF — no shadow evaluation"),
    # Bull Pulse — 1m SHADOW, 3m OFF
    DeploymentLane("BP_NIFTY_CE_1M", "BULL_PULSE",    "CE", "1m", "NIFTY", "SHADOW", True, False, True),
    DeploymentLane("BP_NIFTY_CE_3M", "BULL_PULSE",    "CE", "3m", "NIFTY", "OFF",    True, False, False,
                   note="MODE=OFF — no shadow evaluation"),
    # Underlying strategy (5m NIFTY spot bars) — premium not available, skip with explicit reason
    DeploymentLane(
        "pullback-master-pine-v5", "PULLBACK", "CE", "5m", "NIFTY", "PAPER",
        premium_domain=False,   # operates on underlying OHLCV bars
        underlying_domain=True,
        risk_engine_enabled=True,
        note="Underlying bar strategy — option premium translation unavailable at evaluation; skipped with OPTION_PREMIUM_UNAVAILABLE",
    ),
]

_BY_ID: Dict[str, DeploymentLane] = {lane.deployment_id: lane for lane in AUTHORITATIVE_LANES}


def get_lane(deployment_id: str) -> Optional[DeploymentLane]:
    return _BY_ID.get(deployment_id)


def all_lanes() -> List[DeploymentLane]:
    return list(AUTHORITATIVE_LANES)


def enabled_lanes() -> List[DeploymentLane]:
    return [lane for lane in AUTHORITATIVE_LANES if lane.risk_engine_enabled]
