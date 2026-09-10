"""Liquidity & Orderbook Metrics for Eye Engine Phase E4A."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LiquidityMetrics:
    open_interest: Optional[int]
    previous_open_interest: Optional[int]
    oi_change: Optional[int]
    oi_change_pct: Optional[float]
    volume: Optional[int]
    bid_depth_quantity: Optional[int]
    ask_depth_quantity: Optional[int]
    total_top_depth_quantity: Optional[int]
    depth_imbalance_ratio: Optional[float]


def calculate_liquidity_metrics(
    open_interest: Optional[int] = None,
    previous_open_interest: Optional[int] = None,
    volume: Optional[int] = None,
    bid_quantity: Optional[int] = None,
    ask_quantity: Optional[int] = None,
) -> LiquidityMetrics:
    """Calculate market liquidity, depth imbalance, and OI change metrics."""
    oi_change = None
    oi_change_pct = None

    if open_interest is not None and previous_open_interest is not None:
        oi_change = open_interest - previous_open_interest
        if previous_open_interest > 0:
            oi_change_pct = round((oi_change / previous_open_interest) * 100.0, 2)

    total_depth = None
    imbalance = None

    if bid_quantity is not None and ask_quantity is not None:
        total_depth = bid_quantity + ask_quantity
        if total_depth > 0:
            imbalance = round((bid_quantity - ask_quantity) / total_depth, 4)

    return LiquidityMetrics(
        open_interest=open_interest,
        previous_open_interest=previous_open_interest,
        oi_change=oi_change,
        oi_change_pct=oi_change_pct,
        volume=volume,
        bid_depth_quantity=bid_quantity,
        ask_depth_quantity=ask_quantity,
        total_top_depth_quantity=total_depth,
        depth_imbalance_ratio=imbalance,
    )
