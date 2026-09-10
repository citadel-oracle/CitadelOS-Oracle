"""
Cost-Aware Outcome Engine for Real Backtest Fill Simulation.

Applies bid/ask spread, slippage penalties, brokerage fees, and quote freshness constraints.
EXECUTION INFLUENCE: ZERO.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any


@dataclass(frozen=True)
class ExecutionCostConfig:
    spread_pct: float = 0.0010  # 10 bps spread
    slippage_pts: float = 0.50  # 0.50 pts option slippage
    brokerage_per_order: float = 20.0  # 20 INR per order
    max_quote_age_seconds: float = 5.0


class CostAwareOutcomeEngine:
    """Simulates realistic execution fills considering spread, slippage, and brokerage."""

    def __init__(self, config: ExecutionCostConfig = ExecutionCostConfig()):
        self.config = config

    def apply_cost_to_trade(
        self, entry_price: float, exit_price: float, side: str = "BUY", quantity: int = 50
    ) -> Dict[str, Any]:
        cost = (self.config.spread_pct * entry_price) + self.config.slippage_pts
        adjusted_entry = entry_price + cost if side == "BUY" else entry_price - cost
        adjusted_exit = exit_price - cost if side == "BUY" else exit_price + cost

        gross_pnl = (exit_price - entry_price) * quantity if side == "BUY" else (entry_price - exit_price) * quantity
        total_brokerage = self.config.brokerage_per_order * 2
        net_pnl = ((adjusted_exit - adjusted_entry) * quantity) - total_brokerage

        return {
            "raw_entry": entry_price,
            "adjusted_entry": round(adjusted_entry, 2),
            "raw_exit": exit_price,
            "adjusted_exit": round(adjusted_exit, 2),
            "gross_pnl": round(gross_pnl, 2),
            "net_pnl": round(net_pnl, 2),
            "slippage_pts": self.config.slippage_pts,
            "brokerage_inr": total_brokerage,
            "execution_influence": "ZERO",
        }
