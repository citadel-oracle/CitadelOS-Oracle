"""Focused unit tests for Oracle Development trade execution, sizing ceilings, and stop-loss logic."""

import pytest
import tempfile
from pathlib import Path

from src.oracle_development.trade_planner_dev import OracleDevTradePlanner
from src.oracle_development.mission_dev import OracleDevMissionService
from src.oracle_development.paper_autopilot_dev import OracleDevPaperAutopilot


def test_conviction_sizing_ceilings():
    """Asserts sizing floors to correct limits depending on aligned factors."""
    planner = OracleDevTradePlanner()
    
    # 1. Highest grade all elements aligned, score >= 85 -> max 10 lots
    scores = {"total_score": 90.0, "risk_approved": True, "guardian_ready": True}
    assert planner.compute_conviction_ceiling(scores, pa_aligned=True, vob_aligned=True, deriv_aligned=True) == 10
    
    # 2. PA + VOB + Derivatives aligned -> max 5 lots
    scores = {"total_score": 80.0}
    assert planner.compute_conviction_ceiling(scores, pa_aligned=True, vob_aligned=True, deriv_aligned=True) == 5
    
    # 3. PA + VOB aligned -> max 3 lots
    scores = {"total_score": 75.0}
    assert planner.compute_conviction_ceiling(scores, pa_aligned=True, vob_aligned=True, deriv_aligned=False) == 3
    
    # 4. PA only or VOB only -> max 1 lot
    scores = {"total_score": 60.0}
    assert planner.compute_conviction_ceiling(scores, pa_aligned=True, vob_aligned=False, deriv_aligned=False) == 1
    assert planner.compute_conviction_ceiling(scores, pa_aligned=False, vob_aligned=True, deriv_aligned=False) == 1
    
    # 5. Non-aligned -> 0 lots
    assert planner.compute_conviction_ceiling(scores, pa_aligned=False, vob_aligned=False, deriv_aligned=False) == 0


def test_risk_governor_override_scaling():
    """Asserts that risk parameters can override sizing to scale down, but never scale up."""
    planner = OracleDevTradePlanner()
    
    # Setup conviction details (aligned: PA + VOB + Derivatives = 5 lots ceiling)
    scores = {"total_score": 80.0}
    
    # Sizing when risk governor does not restrict (capital size supports 20 lots)
    plan_unrestricted = planner.plan_trade(
        setup_family="PA+VOB Pullback",
        direction="CALL",
        entry_price=24000.0,
        structural_sl_price=23950.0,
        scores=scores,
        pa_aligned=True,
        vob_aligned=True,
        deriv_aligned=True,
        capital_lots=20
    )
    
    # Sizing must equal the conviction ceiling of 5 lots (conviction scaled it down)
    assert plan_unrestricted["approved_lots"] == 5
    
    # Sizing when risk governor restricts to 2 lots (due to risk limits/capital)
    plan_restricted = planner.plan_trade(
        setup_family="PA+VOB Pullback",
        direction="CALL",
        entry_price=24000.0,
        structural_sl_price=23950.0,
        scores=scores,
        pa_aligned=True,
        vob_aligned=True,
        deriv_aligned=True,
        capital_lots=2
    )
    
    # Sizing must equal 2 lots (risk governor scaled it down)
    assert plan_restricted["approved_lots"] == 2


def test_timeframe_close_stop_loss():
    """Asserts that Stop Losses only trigger on completed candle closes and wicks are ignored."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        missions = OracleDevMissionService(tmp_root)
        autopilot = OracleDevPaperAutopilot(tmp_root, missions, None)
        
        # Start a 3m lane mission
        mission = missions.start(
            symbol="NIFTY",
            timeframe="3m",
            parent_setup_family="VOB Pullback",
            trade_creator="VOB",
            direction="CALL",
            reference_time="2026-07-27T16:00:00Z"
        )
        
        # Set a plan with structural SL of 23950
        plan = {
            "entry_price": 24000.0,
            "structural_sl": 23950.0,
            "target_price": 24100.0
        }
        missions.plan(mission["mission_id"], plan)
        
        # Place virtual order
        contract = {"security_id": "12345", "symbol": "NIFTY-CE-24000", "lot_size": 75}
        autopilot.execute_paper_order("3m", mission["mission_id"], contract, "CALL", 1, 100.0)
        
        # Case 1: Intrabar wick breach (low is 23940, but close is 23980 > SL 23950)
        spot_candles_wick = [
            {"time": 1785148800, "open": 24000.0, "high": 24010.0, "low": 23940.0, "close": 23980.0}
        ]
        option_candles = {"ATM_CE": [{"close": 90.0}]}
        
        autopilot.update_lane_candles("3m", spot_candles_wick, spot_candles_wick, option_candles)
        
        # Position must remain open (intrabar wick breach ignored)
        lane_status = autopilot.get_lane_status("3m")
        assert lane_status["position"] is not None
        assert lane_status["position"]["status"] == "OPEN"
        
        # Case 2: Candle close breach (close is 23930 < SL 23950)
        spot_candles_close = [
            {"time": 1785148980, "open": 23980.0, "high": 23990.0, "low": 23900.0, "close": 23930.0}
        ]
        autopilot.update_lane_candles("3m", spot_candles_close, spot_candles_close, option_candles)
        
        # Position must be closed (timeframe candle close verified breach)
        lane_status_after = autopilot.get_lane_status("3m")
        assert lane_status_after["position"] is None
        assert lane_status_after["state"] == "CLOSED"
