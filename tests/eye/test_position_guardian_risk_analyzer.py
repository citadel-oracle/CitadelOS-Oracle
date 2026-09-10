"""Unit & Integration Tests for CITADEL Phase E6A Position, Guardian, Risk & OpenAlgo Analyzer."""

import pytest
from unittest.mock import MagicMock
from src.eye.position.contracts import PositionState, GuardianState, RiskDecisionType
from src.eye.position.risk import RiskDisciplineEngine
from src.eye.position.supervisor import PositionSupervisor
from src.eye.position.guardian import GuardianEngine


def test_analyzer_disabled_blocks_order():
    risk = RiskDisciplineEngine()
    setup_decision = {
        "trade_plan": {
            "status": "ACTIVE",
            "entry_geometry": {"entry_reference": 24550.0},
            "structural_stop": {"sl_price": 24540.0},
            "natural_targets": [{"price": 24570.0}],
        }
    }
    result = risk.evaluate_pre_trade_risk(
        setup_decision=setup_decision,
        active_positions=[],
        daily_closed_pnl=0.0,
        daily_trade_count=0,
        analyzer_mode=False,
    )
    assert result.decision == RiskDecisionType.BLOCK
    assert result.reason_code == "ANALYZER_MODE_FALSE"


def test_invalid_geometry_blocks_order():
    risk = RiskDisciplineEngine()
    setup_decision = {
        "trade_plan": {
            "status": "RR_NOT_ESTABLISHED",
            "entry_geometry": {},
            "structural_stop": {},
            "natural_targets": [],
        }
    }
    result = risk.evaluate_pre_trade_risk(
        setup_decision=setup_decision,
        active_positions=[],
        daily_closed_pnl=0.0,
        daily_trade_count=0,
        analyzer_mode=True,
    )
    assert result.decision == RiskDecisionType.BLOCK
    assert result.reason_code == "INVALID_GEOMETRY"


@pytest.mark.parametrize("lot_size", [50, 65])
def test_risk_requires_resolved_contract_lot_size(lot_size):
    risk = RiskDisciplineEngine()
    setup = {
        "trade_plan": {
            "status": "ACTIVE",
            "entry_geometry": {"entry_reference": 180.0},
            "structural_stop": {"sl_price": 165.0},
            "natural_targets": [{"price": 210.0}],
        }
    }
    missing = risk.evaluate_pre_trade_risk(setup, [], 0.0, 0, True)
    assert missing.decision == RiskDecisionType.BLOCK
    assert missing.reason_code == "LOT_SIZE_UNAVAILABLE"

    approved = risk.evaluate_pre_trade_risk({**setup, "contract": {"lot_size": lot_size}}, [], 0.0, 0, True)
    assert approved.decision == RiskDecisionType.ALLOW
    assert approved.allowed_quantity == lot_size
    assert approved.estimated_risk_amount == 15.0 * lot_size


def test_idempotency_prevents_duplicate_orders():
    mock_client = MagicMock()
    mock_client.get_analyzer_status.return_value = {"status": "success", "data": {"mode": "analyze"}}
    mock_client.place_order.return_value = {"status": "success", "orderid": "SB-1001"}
    mock_client.get_trades.return_value = {"data": [{"orderid": "SB-1001", "price": 180.0}]}

    sup = PositionSupervisor(openalgo_client=mock_client)
    idem_key = sup.generate_idempotency_key("EVT:101", "REV:1", "NIFTY11AUG2624700PE", "09:30:00")

    pos1 = sup.open_analyzer_position(
        decision_id="DEC:1",
        setup_key="SETUP:1",
        setup_record_id="EVT:101",
        underlying="NIFTY",
        exact_contract="NIFTY11AUG2624700PE",
        exchange="NFO",
        expiry="2026-08-11",
        strike=24700.0,
        option_type="PE",
        side="BUY",
        quantity=650,
        ref_entry=180.0,
        sl_price=170.0,
        t1=200.0,
        t2=210.0,
        t3=None,
        timestamp_str="09:30:00",
        idempotency_key=idem_key,
    )
    assert pos1 is not None
    assert pos1.openalgo_order_id == "SB-1001"

    # Second submission with same idempotency key
    pos2 = sup.open_analyzer_position(
        decision_id="DEC:1",
        setup_key="SETUP:1",
        setup_record_id="EVT:101",
        underlying="NIFTY",
        exact_contract="NIFTY11AUG2624700PE",
        exchange="NFO",
        expiry="2026-08-11",
        strike=24700.0,
        option_type="PE",
        side="BUY",
        quantity=650,
        ref_entry=180.0,
        sl_price=170.0,
        t1=200.0,
        t2=210.0,
        t3=None,
        timestamp_str="09:30:00",
        idempotency_key=idem_key,
    )
    assert pos2 is None
    assert mock_client.place_order.call_count == 1


def test_guardian_target_exit():
    mock_client = MagicMock()
    mock_client.get_analyzer_status.return_value = {"status": "success", "data": {"mode": "analyze"}}
    mock_client.place_order.return_value = {"status": "success", "orderid": "SB-1002"}
    mock_client.get_trades.return_value = {"data": [{"orderid": "SB-1002", "price": 180.0}, {"orderid": "SB-1002", "price": 195.0}]}

    sup = PositionSupervisor(openalgo_client=mock_client)
    pos = sup.open_analyzer_position(
        decision_id="DEC:2",
        setup_key="SETUP:2",
        setup_record_id="EVT:102",
        underlying="NIFTY",
        exact_contract="NIFTY11AUG2624700PE",
        exchange="NFO",
        expiry="2026-08-11",
        strike=24700.0,
        option_type="PE",
        side="BUY",
        quantity=650,
        ref_entry=180.0,
        sl_price=24720.0,
        t1=24600.0,  # Underlying target
        t2=None,
        t3=None,
        timestamp_str="09:30:00",
        idempotency_key="KEY:2",
    )

    guardian = GuardianEngine(supervisor=sup)
    # Simulate high reaching target 24605.0 for BULLISH or low reaching 24590.0 for BEARISH
    closed = guardian.evaluate_active_positions(
        current_underlying_bar={"low": 24580.0, "high": 24610.0, "close": 24590.0},
        current_option_bar={"close": 195.0},
        timestamp_str="09:35:00",
    )
    assert len(closed) == 1
    assert closed[0].exit_reason == "TARGET_T1"
    assert closed[0].guardian_state == GuardianState.CLOSED


def test_opening_sell_option_order_prohibited():
    mock_client = MagicMock()
    sup = PositionSupervisor(openalgo_client=mock_client)
    with pytest.raises(ValueError, match="Safety Violation: CITADEL is Option-Buying Only"):
        sup.open_analyzer_position(
            decision_id="DEC:3",
            setup_key="SETUP:3",
            setup_record_id="EVT:103",
            underlying="NIFTY",
            exact_contract="NIFTY11AUG2624700PE",
            exchange="NFO",
            expiry="2026-08-11",
            strike=24700.0,
            option_type="PE",
            side="SELL",  # Opening SELL prohibited
            quantity=650,
            ref_entry=180.0,
            sl_price=170.0,
            t1=200.0,
            t2=None,
            t3=None,
            timestamp_str="09:30:00",
            idempotency_key="KEY:3",
        )


def test_reconciliation_never_invents_position_geometry(tmp_path):
    mock_client = MagicMock()
    mock_client.get_analyzer_status.return_value = {
        "status": "success", "data": {"mode": "analyze"}
    }
    mock_client.get_positions.return_value = {
        "data": [{"symbol": "NIFTY11AUG2624700PE", "quantity": 65}]
    }
    supervisor = PositionSupervisor(
        openalgo_client=mock_client,
        state_path=tmp_path / "positions.json",
    )
    assert supervisor.get_active_positions() == []
    assert supervisor.reconciliation_required == [{
        "symbol": "NIFTY11AUG2624700PE",
        "quantity": 65,
        "reason": "EXTERNAL_POSITION_WITHOUT_EYE_PROVENANCE",
    }]


def test_known_position_and_idempotency_recover_without_resubmission(tmp_path):
    state_path = tmp_path / "positions.json"
    first_client = MagicMock()
    first_client.get_analyzer_status.return_value = {
        "status": "success", "data": {"mode": "analyze"}
    }
    first_client.get_positions.return_value = {"data": []}
    first_client.get_trades.side_effect = [
        {"data": []},
        {"data": [{"orderid": "SB-RECOVER", "price": 180.0}]},
    ]
    first_client.place_order.return_value = {
        "status": "success", "orderid": "SB-RECOVER"
    }
    first = PositionSupervisor(openalgo_client=first_client, state_path=state_path)
    position = first.open_analyzer_position(
        decision_id="DEC:RECOVER", setup_key="SETUP:RECOVER",
        setup_record_id="EVT:RECOVER", underlying="NIFTY",
        exact_contract="NIFTY11AUG2624700PE", exchange="NFO",
        expiry="2026-08-11", strike=24700.0, option_type="PE", side="BUY",
        quantity=65, ref_entry=180.0, sl_price=170.0, t1=200.0,
        t2=None, t3=None, timestamp_str="09:30:00", idempotency_key="RECOVER:1",
    )
    assert position is not None

    restarted_client = MagicMock()
    restarted_client.get_analyzer_status.return_value = {
        "status": "success", "data": {"mode": "analyze"}
    }
    restarted_client.get_positions.return_value = {
        "data": [{"symbol": "NIFTY11AUG2624700PE", "quantity": 65}]
    }
    restarted_client.get_trades.return_value = {"data": []}
    restarted = PositionSupervisor(
        openalgo_client=restarted_client, state_path=state_path
    )
    assert [row.position_id for row in restarted.get_active_positions()] == [
        "POS:DEC:RECOVER:NIFTY11AUG2624700PE"
    ]
    assert restarted.has_decision_been_submitted("RECOVER:1")
