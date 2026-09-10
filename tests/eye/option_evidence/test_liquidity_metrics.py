"""E4A Liquidity & Orderbook Metrics Tests."""

import pytest
from src.eye.option_evidence.liquidity import calculate_liquidity_metrics


def test_liquidity_metrics_calculation():
    l_metrics = calculate_liquidity_metrics(
        open_interest=100000,
        previous_open_interest=90000,
        volume=25000,
        bid_quantity=400,
        ask_quantity=200,
    )
    assert l_metrics.oi_change == 10000
    assert l_metrics.oi_change_pct == 11.11
    assert l_metrics.total_top_depth_quantity == 600
    assert l_metrics.depth_imbalance_ratio > 0  # Bid heavy
