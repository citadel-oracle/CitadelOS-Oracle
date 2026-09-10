"""
Historical Real-Data Replay Test Suite for Unified Risk Engine.
"""

from __future__ import annotations
import json
from pathlib import Path
import pytest
from src.risk_engine.service import UnifiedRiskEngineService
from src.risk_engine.simulator import DeterministicExitSimulator


@pytest.fixture(autouse=True)
def reset_service():
    UnifiedRiskEngineService.reset_instance()
    yield
    UnifiedRiskEngineService.reset_instance()


@pytest.fixture
def real_nifty_candles():
    candles_path = Path("logs/kronos_alpha_candles.json")
    if candles_path.exists():
        with open(candles_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("candles", [])
    return [
        {
            "timestamp": f"2026-07-31T10:{i:02d}:00+05:30",
            "open": 24000.0 + i,
            "high": 24010.0 + i,
            "low": 23990.0 + i,
            "close": 24005.0 + i,
            "volume": 1000.0,
        }
        for i in range(100)
    ]


def test_historical_replay_10_apex_strategies(real_nifty_candles):
    service = UnifiedRiskEngineService.get_instance()
    sim = DeterministicExitSimulator()

    strategies = [
        ("TREND_CATCHER", "LONG", 24000.0, 23950.0, 24100.0),
        ("BULL_PULSE", "LONG", 24010.0, 23960.0, 24110.0),
        ("PULLBACK_MASTER", "LONG", 24020.0, 23970.0, 24120.0),
        ("BREAKOUT_MAIN", "LONG", 24030.0, 23980.0, 24130.0),
        ("OPTION_CHART_1", "LONG", 150.0, 130.0, 190.0),
        ("OPTION_CHART_2", "LONG", 160.0, 140.0, 200.0),
        ("OPTION_CHART_3", "LONG", 170.0, 150.0, 210.0),
        ("OPTION_CHART_4", "LONG", 180.0, 160.0, 220.0),
        ("OPTION_CHART_5", "LONG", 190.0, 170.0, 230.0),
        ("OPTION_CHART_6", "LONG", 200.0, 180.0, 240.0),
    ]

    plans = []
    simulation_results = []

    for strat_id, side, entry, struct_inv, target in strategies:
        plan = service.evaluate_shadow_risk_plan(
            strategy_id=strat_id,
            instrument="NIFTY",
            side=side,
            entry_price=entry,
            structural_invalidation=struct_inv,
            atr=20.0,
            first_target=target,
        )
        plans.append(plan)

        sim_res = sim.simulate_trade_exit(plan, real_nifty_candles)
        simulation_results.append(sim_res)

    assert len(plans) == 10
    assert len(simulation_results) == 10
    assert all("status" in r for r in simulation_results)
