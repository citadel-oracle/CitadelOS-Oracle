"""E5A Test for Reference Risk:Reward Calculation & Abstention."""

import pytest
from src.eye.oracle_projection.trade_plan import TradePlanBuilder
from src.eye.oracle_projection.contracts import TradePlanStatus, EntryGeometryStatus, StructuralStopStatus, NaturalTargetStatus


def test_reference_rr_derived_after_entry_sl_target():
    builder = TradePlanBuilder()

    entry = {
        "entry_status": EntryGeometryStatus.ACTIVE,
        "entry_low": 24580.0,
        "entry_high": 24590.0,
        "entry_reference": 24585.0,
        "entry_geometry_type": "FVG_RETEST_BAND",
        "source_event_keys": ["EVT:FVG:1"],
    }

    stop = {
        "status": StructuralStopStatus.ACTIVE,
        "sl_price": 24535.0,
        "sl_type": "SWEEP_EXTREME_INVALIDATION",
        "distance_from_entry": 50.0,
        "source_event_key": "EVT:SWEEP:1",
    }

    targets = [
        {"price": 24685.0, "target_type": "OPPOSING_SWING_HIGH", "distance": 100.0, "source_event_keys": ["EVT:SWING:1"], "timeframe": "15m", "rank": 1, "rank_reason": "NEAREST_SWING_HIGH"},
    ]

    plan = builder.build_trade_plan(entry, stop, targets)

    assert plan.status == TradePlanStatus.ACTIVE
    assert plan.risk_points == 50.0
    assert plan.reward_to_t1 == 100.0
    assert plan.rr_mid == 2.0  # 100 / 50 = 2.0
    assert plan.rr_conservative == 1.727  # (24685 - 24590) / (24590 - 24535) = 95 / 55 = 1.727



def test_missing_component_abstains_rr():
    builder = TradePlanBuilder()
    plan = builder.build_trade_plan(None, None, [])

    assert plan.status == TradePlanStatus.RR_NOT_ESTABLISHED
    assert plan.risk_points is None
    assert plan.rr_mid is None
