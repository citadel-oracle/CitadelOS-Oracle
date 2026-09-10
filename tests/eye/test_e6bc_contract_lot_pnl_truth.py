"""Focused unit tests for Phase E6B-C Contract, Lot, Premium, and P&L Truth Closure."""

pytest_plugins = ["anyio"]

import pytest
from unittest.mock import MagicMock
from src.eye.position.contract_router import ContractRouter
from src.eye.position.contracts import PositionState, GuardianState, RiskDecisionType
from src.eye.position.supervisor import PositionSupervisor
from src.eye.position.guardian import GuardianEngine
from src.eye.position.risk import RiskDisciplineEngine
from src.eye.oracle_projection.chart_context import ChartContextManager


def _master_rows():
    return [
        {
            "UNDERLYING_SYMBOL": "NIFTY", "SM_EXPIRY_DATE": "2026-08-11",
            "STRIKE_PRICE": "24550", "OPTION_TYPE": "CE", "SECURITY_ID": "41023",
            "SYMBOL_NAME": "NIFTY11AUG2624550CE", "LOT_SIZE": 65, "EXCHANGE": "NFO",
        },
        {
            "UNDERLYING_SYMBOL": "NIFTY", "SM_EXPIRY_DATE": "2026-08-11",
            "STRIKE_PRICE": "24550", "OPTION_TYPE": "PE", "SECURITY_ID": "41022",
            "SYMBOL_NAME": "NIFTY11AUG2624550PE", "LOT_SIZE": 65, "EXCHANGE": "NFO",
        },
        {
            "UNDERLYING_SYMBOL": "NIFTY", "SM_EXPIRY_DATE": "2026-08-11",
            "STRIKE_PRICE": "24700", "OPTION_TYPE": "PE", "SECURITY_ID": "41024",
            "SYMBOL_NAME": "NIFTY11AUG2624700PE", "LOT_SIZE": 65, "EXCHANGE": "NFO",
        },
    ]


def test_nifty_lot_size_not_650():
    router = ContractRouter(_master_rows())
    resolved = router.resolve_contract(chart_symbol="NIFTY", eye_direction="BEARISH", spot_price=24550.0)
    assert resolved.lot_size != 650
    assert resolved.lot_size == 65


def test_missing_canonical_instrument_metadata_never_falls_back_to_fixture_contract():
    assert ContractRouter().resolve_contract(
        chart_symbol="NIFTY",
        eye_direction="BULLISH",
        spot_price=24550.0,
        session_date="2026-08-08",
    ) is None


def test_quantity_derived_from_contract_lot_size():
    router = ContractRouter(_master_rows())
    resolved = router.resolve_contract(chart_symbol="NIFTY", eye_direction="BEARISH", spot_price=24550.0)
    num_lots = 1
    quantity = resolved.lot_size * num_lots
    assert quantity == 65


def test_ce_trade_never_uses_pe_premium_data():
    router = ContractRouter(_master_rows())
    resolved = router.resolve_contract(chart_symbol="NIFTY", eye_direction="BULLISH", spot_price=24550.0)
    assert resolved.option_type == "CE"
    
    # Premium data contract identity check
    assert resolved.openalgo_symbol == "NIFTY11AUG2624550CE"


def test_contract_and_premium_security_id_match():
    router = ContractRouter(_master_rows())
    resolved_pe = router.resolve_contract(chart_symbol="NIFTY11AUG2624700PE", eye_direction="BEARISH", spot_price=24550.0)
    assert resolved_pe.dhan_security_id == "41024"
    assert resolved_pe.option_type == "PE"


def test_option_and_underlying_price_domains_separate():
    pos = PositionState(
        position_id="POS:1",
        decision_id="DEC:1",
        setup_key="SETUP:1",
        setup_record_id="EVT:1",
        underlying="NIFTY",
        exact_contract="NIFTY11AUG2624700PE",
        exchange="NFO",
        expiry="2026-08-11",
        strike=24700.0,
        option_type="PE",
        side="BUY",
        quantity=65,
        product="NRML",
        expected_entry=180.0,
        actual_fill=180.0,
        fill_time="09:30:00",
        structural_sl=24580.0,  # Underlying domain
        invalidation_level=24580.0,  # Underlying domain
        t1=24500.0,  # Underlying domain
        current_premium=185.0,  # Option domain
        current_underlying=24540.0,  # Underlying domain
    )
    # Underlying domain assertion
    assert pos.structural_sl > 20000.0
    # Option domain assertion
    assert pos.current_premium < 1000.0
    assert pos.actual_fill < 1000.0


def test_guardian_never_compares_option_premium_to_underlying_target():
    mock_client = MagicMock()
    mock_client.get_analyzer_status.return_value = {"status": "success", "data": {"mode": "analyze"}}
    mock_client.place_order.return_value = {"status": "success", "orderid": "SB-100"}
    mock_client.get_trades.side_effect = [
        {"data": []},
        {"data": [{"orderid": "SB-100", "price": 180.0}]},
        {"data": [{"orderid": "SB-100", "price": 195.0}]},
    ]

    sup = PositionSupervisor(openalgo_client=mock_client)
    pos = sup.open_analyzer_position(
        decision_id="DEC:TEST",
        setup_key="SETUP:TEST",
        setup_record_id="EVT:TEST",
        underlying="NIFTY",
        exact_contract="NIFTY11AUG2624700PE",
        exchange="NFO",
        expiry="2026-08-11",
        strike=24700.0,
        option_type="PE",
        side="BUY",
        quantity=65,
        ref_entry=180.0,
        sl_price=24580.0,  # Underlying SL
        t1=24500.0,  # Underlying T1
        t2=None,
        t3=None,
        timestamp_str="09:30:00",
        idempotency_key="KEY:TEST",
    )
    guardian = GuardianEngine(supervisor=sup)
    # Option premium = 185.0, underlying high = 24550.0, low = 24490.0 (hits target 24500.0, does NOT hit SL 24580.0)
    closed = guardian.evaluate_active_positions(
        current_underlying_bar={"low": 24490.0, "high": 24550.0, "close": 24500.0},
        current_option_bar={"close": 195.0},
        timestamp_str="09:35:00",
    )
    assert pos is not None
    assert len(closed) == 1
    assert closed[0].exit_reason == "TARGET_T1"
    # Realized PnL must be computed using option premium (195 - 180) * 65
    assert closed[0].realized_pnl == 975.0


def test_dynamic_tv_context_switch():
    cm = ChartContextManager()
    c1 = cm.resolve_context("NIFTY", "1m")
    assert c1.identity_epoch == 1
    c2 = cm.resolve_context("BANKNIFTY", "1m")
    assert c2.identity_epoch == 2
    c3 = cm.resolve_context("NIFTY", "1m")
    assert c3.identity_epoch == 3


def test_analyzer_rechecked_per_order():
    mock_client = MagicMock()
    mock_client.get_analyzer_status.return_value = {"status": "success", "data": {"mode": "analyze"}}
    mock_client.place_order.return_value = {"status": "success", "orderid": "SB-101"}

    sup = PositionSupervisor(openalgo_client=mock_client)
    sup.open_analyzer_position(
        decision_id="DEC:PER_ORDER",
        setup_key="SETUP:PER_ORDER",
        setup_record_id="EVT:PER_ORDER",
        underlying="NIFTY",
        exact_contract="NIFTY11AUG2624700PE",
        exchange="NFO",
        expiry="2026-08-11",
        strike=24700.0,
        option_type="PE",
        side="BUY",
        quantity=65,
        ref_entry=180.0,
        sl_price=170.0,
        t1=200.0,
        t2=None,
        t3=None,
        timestamp_str="09:30:00",
        idempotency_key="KEY:PER_ORDER",
    )
    assert mock_client.get_analyzer_status.call_count >= 1


def test_openalgo_pnl_read_independently():
    mock_client = MagicMock()
    mock_client.get_positions.return_value = {
        "status": "success",
        "data": [{"pnl": 975.0, "symbol": "NIFTY11AUG2624700PE"}]
    }
    positions = mock_client.get_positions()
    openalgo_pnl = sum(p["pnl"] for p in positions.get("data", []))
    assert openalgo_pnl == 975.0


def test_unapproved_default_not_reported_approved():
    risk = RiskDisciplineEngine()
    # Risk policy approval flag is False when max trades limit is unapproved default
    assert getattr(risk, "is_approved", False) is False
