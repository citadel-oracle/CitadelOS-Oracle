"""Focused unit tests for Phase E6C Oracle Live State & Frontend Truth Closure."""

pytest_plugins = ["anyio"]

import pytest
from unittest.mock import MagicMock
import json
from time import monotonic

from src.api.control_status_api import ControlStatusAPI
from src.api.v2_integration import V2DashboardIntegration
from src.eye.position.supervisor import PositionSupervisor
from src.eye.position.risk import RiskDisciplineEngine
from src.eye.position.contracts import PositionState, GuardianState, RiskDecisionType


def test_serialized_v2_dashboard_reuses_cached_oracle_and_eye_projection():
    calls = []

    def workspace():
        calls.append("read")
        return {"chart_state": {"timeframe": "5m"}, "sync_state": "LIVE"}

    integration = V2DashboardIntegration(oracle_live_workspace=workspace)
    integration._serialized_template = json.dumps(
        {
            "feeds": {
                "oracle": {"data": {"live_workspace": workspace()}},
                "eye_oracle_projection": {"data": {"status": "SCANNING"}},
            },
            "polling": {},
        },
        separators=(",", ":"),
    ).encode()
    calls.clear()
    integration._last_projection_at = monotonic()
    integration._last_refresh_status = "READY"
    integration._initial_snapshot_ready.set()

    body, _ = integration.serialized_dashboard()

    assert calls == []
    assert b"LIVE" in body
    assert b"SCANNING" in body


def test_v2_rebuild_reads_oracle_live_workspace_once_for_chart_and_oracle_feed():
    calls = []

    def workspace():
        calls.append("read")
        return {"chart_state": {"timeframe": "3m"}, "sync_state": "LIVE"}

    integration = V2DashboardIntegration(
        snapshot=lambda: {"status": "OPEN"},
        oracle=lambda _symbol: {},
        argus=lambda _symbol: {},
        kronos_alpha=lambda: {}, chronos2=lambda: {}, athena=lambda: {}, hermes=lambda: {},
        risk_status=lambda: {}, kill_switch=lambda: {}, paper_status=lambda: {},
        personal_oracle=lambda: {}, readiness=lambda: {}, next_session_plan=lambda: {},
        order_ledger=lambda: {}, paper_trading=lambda: {},
        oracle_live_workspace=workspace,
    )

    dashboard = integration.dashboard("NIFTY")

    assert calls == ["read"]
    assert dashboard["feeds"]["oracle"]["data"]["live_workspace"]["sync_state"] == "LIVE"


def test_frontend_broker_connected_when_openalgo_connected(monkeypatch):
    mock_client = MagicMock()
    mock_client.get_analyzer_status.return_value = {"status": "success", "data": {"mode": "analyze", "analyze_mode": True}}
    monkeypatch.setattr("src.broker.openalgo_client.OpenAlgoClient", lambda: mock_client)

    api = ControlStatusAPI()
    summary = api.risk_summary()
    assert summary.get("openalgo_connected") is True
    assert summary.get("openalgo_mode") == "analyze"


def test_no_stale_broker_disconnected_fallback():
    engine = RiskDisciplineEngine()
    summary = engine.get_risk_summary(active_positions=[], daily_closed_pnl=0.0, daily_trade_count=0, analyzer_mode=True)
    assert summary["openalgo_reachable"] is True
    assert summary["dhan_connected"] is True
    assert summary["analyzer_connected"] is True


def test_frontend_position_fill_matches_tradebook():
    mock_client = MagicMock()
    mock_client.get_analyzer_status.return_value = {"status": "success", "data": {"mode": "analyze"}}
    mock_client.place_order.return_value = {"status": "success", "orderid": "26080700001111", "price": 180.0}
    mock_client.get_trades.side_effect = [
        {"data": []},
        {"data": [{"orderid": "26080700001111", "price": 180.0}]},
    ]

    sup = PositionSupervisor(openalgo_client=mock_client)
    pos = sup.open_analyzer_position(
        decision_id="DEC:FILL_TEST",
        setup_key="SETUP:FILL_TEST",
        setup_record_id="EVT:FILL_TEST",
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
        idempotency_key="KEY:FILL_TEST",
    )
    assert pos.actual_fill == 180.0
    assert pos.openalgo_order_id == "26080700001111"


def test_position_supervisor_ingests_fill_without_manual_assignment():
    mock_client = MagicMock()
    mock_client.get_analyzer_status.return_value = {"status": "success", "data": {"mode": "analyze"}}
    mock_client.place_order.return_value = {"status": "success", "orderid": "26080799998888"}
    mock_client.get_trades.side_effect = [
        {"data": []},
        {"data": [{"orderid": "26080799998888", "average_price": 181.5}]},
    ]

    sup = PositionSupervisor(openalgo_client=mock_client)
    pos = sup.open_analyzer_position(
        decision_id="DEC:AUTO_FILL",
        setup_key="SETUP:AUTO_FILL",
        setup_record_id="EVT:AUTO_FILL",
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
        idempotency_key="KEY:AUTO_FILL",
    )
    assert pos.openalgo_order_id == "26080799998888"
    assert pos.actual_fill == 181.5


def test_frontend_realized_pnl_matches_position_supervisor():
    mock_client = MagicMock()
    mock_client.get_analyzer_status.return_value = {"status": "success", "data": {"mode": "analyze"}}
    mock_client.place_order.side_effect = [
        {"status": "success", "orderid": "26080711112222"},
        {"status": "success", "orderid": "26080711112223"},
    ]
    mock_client.get_trades.side_effect = [
        {"data": []},
        {"data": [{"orderid": "26080711112222", "price": 180.0}]},
        {"data": [{"orderid": "26080711112223", "price": 195.0}]},
    ]

    sup = PositionSupervisor(openalgo_client=mock_client)
    pos = sup.open_analyzer_position(
        decision_id="DEC:PNL_TEST",
        setup_key="SETUP:PNL_TEST",
        setup_record_id="EVT:PNL_TEST",
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
        idempotency_key="KEY:PNL_TEST",
    )
    assert pos is not None
    closed = sup.close_analyzer_position(pos.position_id, close_price=195.0, timestamp_str="09:35:00", exit_reason="TARGET_T1")
    assert closed is not None
    assert closed.realized_pnl == 975.0


def test_guardian_state_updates_from_backend():
    pos = PositionState(
        position_id="POS:TEST",
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
        product="NRML",
        expected_entry=180.0,
        actual_fill=180.0,
        fill_time="09:30:00",
        structural_sl=24720.0,
        invalidation_level=24720.0,
        t1=24500.0,
        guardian_state=GuardianState.CLOSED,
        closed_at="09:35:00",
        exit_reason="TARGET_T1",
        realized_pnl=975.0,
    )
    pdict = pos.to_dict()
    assert pdict["guardian_state"] == "CLOSED"
    assert pdict["exit_reason"] == "TARGET_T1"


def test_quality_gate_not_defined_remains_fail_closed():
    engine = RiskDisciplineEngine()
    summary = engine.get_risk_summary(active_positions=[], daily_closed_pnl=0.0, daily_trade_count=0, analyzer_mode=True)
    assert summary["quality_evidence_gate"] == "NOT_DEFINED"


def test_risk_unapproved_policy_not_reported_as_available():
    engine = RiskDisciplineEngine()
    summary = engine.get_risk_summary(active_positions=[], daily_closed_pnl=0.0, daily_trade_count=0, analyzer_mode=True)
    assert summary["risk_policy_approved"] is False


def test_connected_broker_not_rendered_as_broker_disconnected(monkeypatch):
    mock_client = MagicMock()
    mock_client.get_analyzer_status.return_value = {"status": "success", "data": {"mode": "analyze", "analyze_mode": True}}
    monkeypatch.setattr("src.broker.openalgo_client.OpenAlgoClient", lambda: mock_client)

    api = ControlStatusAPI()
    summary = api.risk_summary()
    assert summary.get("openalgo_connected") is True
    assert summary.get("openalgo_mode") == "analyze"
    assert summary.get("broker_session_status") == "AUTHENTICATED"
    # Current connectivity must NOT report raw BROKER_DISCONNECTED as active current broker status
    assert summary.get("current_broker_status") == "CONNECTED"


def test_historical_broker_disconnect_reason_separate_from_current_connectivity(monkeypatch):
    mock_client = MagicMock()
    mock_client.get_analyzer_status.return_value = {"status": "success", "data": {"mode": "analyze", "analyze_mode": True}}
    monkeypatch.setattr("src.broker.openalgo_client.OpenAlgoClient", lambda: mock_client)

    mock_store = MagicMock()
    mock_proj = MagicMock()
    mock_proj.active = True
    mock_proj.state = "ACTIVE"
    mock_proj.reason = "BROKER_DISCONNECTED"
    mock_proj.activated_at = "2026-07-24T14:19:31"
    mock_store.projection.return_value = mock_proj

    api = ControlStatusAPI(risk_store=mock_store)
    summary = api.risk_summary()

    assert summary["openalgo_connected"] is True
    assert summary["current_broker_status"] == "CONNECTED"
    assert summary["kill_switch_active"] is True
    assert summary["kill_switch_reason_currently_applicable"] is False
    assert summary["kill_switch_reason"] == "HISTORICAL_BROKER_DISCONNECT_RESET_REQUIRED"


def test_manual_kill_switch_not_auto_cleared(monkeypatch):
    mock_client = MagicMock()
    mock_client.get_analyzer_status.return_value = {"status": "success", "data": {"mode": "analyze", "analyze_mode": True}}
    monkeypatch.setattr("src.broker.openalgo_client.OpenAlgoClient", lambda: mock_client)

    mock_store = MagicMock()
    mock_proj = MagicMock()
    mock_proj.active = True
    mock_proj.state = "ACTIVE"
    mock_proj.reason = "MANUAL_OPERATOR_SHUTDOWN"
    mock_proj.activated_at = "2026-08-07T10:00:00"
    mock_store.projection.return_value = mock_proj

    api = ControlStatusAPI(risk_store=mock_store)
    summary = api.risk_summary()

    # Manual kill switch remains active and reason remains currently applicable
    assert summary["kill_switch_active"] is True
    assert summary["kill_switch_reason"] == "MANUAL_OPERATOR_SHUTDOWN"
    assert summary["kill_switch_reason_currently_applicable"] is True


def test_unrelated_risk_kill_switch_not_auto_cleared(monkeypatch):
    mock_client = MagicMock()
    mock_client.get_analyzer_status.return_value = {"status": "success", "data": {"mode": "analyze", "analyze_mode": True}}
    monkeypatch.setattr("src.broker.openalgo_client.OpenAlgoClient", lambda: mock_client)

    mock_store = MagicMock()
    mock_proj = MagicMock()
    mock_proj.active = True
    mock_proj.state = "ACTIVE"
    mock_proj.reason = "DAILY_LOSS_LIMIT_EXCEEDED"
    mock_proj.activated_at = "2026-08-07T11:00:00"
    mock_store.projection.return_value = mock_proj

    api = ControlStatusAPI(risk_store=mock_store)
    summary = api.risk_summary()

    assert summary["kill_switch_active"] is True
    assert summary["kill_switch_reason"] == "DAILY_LOSS_LIMIT_EXCEEDED"
    assert summary["kill_switch_reason_currently_applicable"] is True
