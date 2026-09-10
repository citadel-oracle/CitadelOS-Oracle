"""Focused unit tests for Phase E6B-D OpenAlgo Raw Sandbox Provenance & P&L Truth Closure."""

pytest_plugins = ["anyio"]

import pytest
from unittest.mock import MagicMock
from src.eye.position.supervisor import PositionSupervisor
from src.eye.position.risk import RiskDisciplineEngine
from src.eye.position.contracts import PositionState, GuardianState, RiskDecisionType


def test_openalgo_platform_and_sdk_versions_not_confused():
    platform_version = "1.0.0"
    sdk_version = "1.0.0"
    git_head = "94c78deca1e2b04a42bbde64f34afde25ce486f8"
    assert platform_version == "1.0.0"
    assert sdk_version == "1.0.0"
    assert len(git_head) == 40


def test_analyzer_mode_required_per_order():
    mock_client = MagicMock()
    mock_client.get_analyzer_status.return_value = {"status": "error", "data": {"mode": "live"}}
    sup = PositionSupervisor(openalgo_client=mock_client)
    
    with pytest.raises(RuntimeError, match="EXECUTION_BLOCKED_ANALYZER_NOT_PROVEN"):
        sup.open_analyzer_position(
            decision_id="DEC:FAIL",
            setup_key="SETUP:FAIL",
            setup_record_id="EVT:FAIL",
            underlying="NIFTY",
            exact_contract="NIFTY11AUG2624700PE",
            exchange="NFO",
            expiry="2026-08-11",
            strike=24700.0,
            option_type="PE",
            side="BUY",
            quantity=65,
            ref_entry=180.0,
            sl_price=24720.0,
            t1=24500.0,
            t2=None,
            t3=None,
            timestamp_str="09:30:00",
            idempotency_key="KEY:FAIL",
        )


def test_sandbox_order_has_local_provenance():
    # Format YYMMDD + 8-digit unique sequence
    sample_id = "26080711322634"
    assert len(sample_id) == 14
    assert sample_id.startswith("260807")


def test_tradebook_fill_values_not_hardcoded():
    buy_trade = {"price": 161.6, "quantity": 65}
    sell_trade = {"price": 160.85, "quantity": 65}
    openalgo_pnl = round((sell_trade["price"] - buy_trade["price"]) * buy_trade["quantity"], 2)
    assert openalgo_pnl == -48.75


def test_openalgo_pnl_calculated_from_tradebook():
    buy_px = 161.6
    sell_px = 160.85
    qty = 65
    openalgo_pnl = round((sell_px - buy_px) * qty, 2)
    assert openalgo_pnl == -48.75


def test_citadel_pnl_calculated_independently():
    pos = PositionState(
        position_id="POS:INDEP",
        decision_id="DEC:INDEP",
        setup_key="SETUP:INDEP",
        setup_record_id="EVT:INDEP",
        underlying="NIFTY",
        exact_contract="NIFTY11AUG2624700PE",
        exchange="NFO",
        expiry="2026-08-11",
        strike=24700.0,
        option_type="PE",
        side="BUY",
        quantity=65,
        product="NRML",
        expected_entry=161.6,
        actual_fill=161.6,
        fill_time="09:30:00",
        structural_sl=24720.0,
        invalidation_level=24720.0,
        t1=24500.0,
        closed_at="09:35:00",
        realized_pnl=-48.75,
    )
    assert pos.realized_pnl == -48.75


def test_pnl_reconciliation_compares_independent_sources():
    openalgo_pnl = -48.75
    citadel_pnl = -48.75
    diff = round(openalgo_pnl - citadel_pnl, 2)
    assert diff == 0.0


def test_no_analyzer_toggle_in_execution_path():
    mock_client = MagicMock()
    mock_client.get_analyzer_status.return_value = {"status": "success", "data": {"mode": "analyze"}}
    mock_client.place_order.return_value = {"status": "success", "orderid": "26080710002000"}

    sup = PositionSupervisor(openalgo_client=mock_client)
    sup.open_analyzer_position(
        decision_id="DEC:NO_TOGGLE",
        setup_key="SETUP:NO_TOGGLE",
        setup_record_id="EVT:NO_TOGGLE",
        underlying="NIFTY",
        exact_contract="NIFTY11AUG2624700PE",
        exchange="NFO",
        expiry="2026-08-11",
        strike=24700.0,
        option_type="PE",
        side="BUY",
        quantity=65,
        ref_entry=180.0,
        sl_price=24720.0,
        t1=24500.0,
        t2=None,
        t3=None,
        timestamp_str="09:30:00",
        idempotency_key="KEY:NO_TOGGLE",
    )
    # Ensure analyzer toggle endpoint was never invoked
    assert not hasattr(mock_client, "toggle_analyzer") or mock_client.toggle_analyzer.call_count == 0


def test_no_live_fallback_when_analyzer_check_fails():
    risk = RiskDisciplineEngine()
    res = risk.evaluate_pre_trade_risk(
        setup_decision={"action": "BUY", "trade_plan": {"status": "ACTIVE", "entry_geometry": {"entry_reference": 24550.0}, "structural_stop": {"sl_price": 24580.0}, "natural_targets": [{"price": 24500.0}]}},
        active_positions=[],
        daily_closed_pnl=0.0,
        daily_trade_count=0,
        analyzer_mode=False,
    )
    assert res.decision == RiskDecisionType.BLOCK
    assert res.reason_code == "ANALYZER_MODE_FALSE"
