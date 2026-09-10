"""E5A Test for Natural Target Direction & R:R Manufacturing Rejection."""

import pytest
from src.eye.oracle_projection.natural_targets import NaturalTargetRanker
from src.eye.oracle_projection.contracts import NaturalTargetStatus


def test_natural_targets_long_direction_ahead_of_price():
    ranker = NaturalTargetRanker()

    entry_price = 24580.0
    direction = "BULLISH"

    # Candidate structural levels ahead of price
    candidates = [
        {"price": 24650.0, "target_type": "OPPOSING_SWING_HIGH", "timeframe": "15m", "event_key": "EVT:SWING:10"},
        {"price": 24700.0, "target_type": "BUY_SIDE_LIQUIDITY_POOL", "timeframe": "1H", "event_key": "EVT:LIQ:11"},
        {"price": 24500.0, "target_type": "INVALID_BELOW_LONG_ENTRY", "timeframe": "5m", "event_key": "EVT:SWING:09"},
    ]

    targets = ranker.rank_targets(entry_price, direction, candidates)

    assert len(targets) == 2
    assert targets[0].price == 24650.0
    assert targets[0].target_type == "OPPOSING_SWING_HIGH"
    assert targets[0].rank == 1

    assert targets[1].price == 24700.0
    assert targets[1].rank == 2


def test_no_natural_target_abstains():
    ranker = NaturalTargetRanker()
    targets = ranker.rank_targets(24580.0, "BULLISH", [])
    assert len(targets) == 0
