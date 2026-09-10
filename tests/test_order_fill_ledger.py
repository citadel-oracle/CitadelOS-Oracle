from dataclasses import replace
from decimal import Decimal

import pytest
from app.main import app
from src.order_ledger.accounting import costs, select_reference_price, slippage
from src.order_ledger.models import FillEvent, OrderIntent
from src.order_ledger.service import OrderFillLedgerService
from src.order_ledger.storage import OrderFillStore

pytestmark = pytest.mark.unit


def intent(identifier="intent-1", quantity=50, authorized=50, lot_size=25):
    return OrderIntent(
        intent_id=identifier, created_at="2026-07-13T09:20:00+05:30", symbol="NIFTY",
        instrument_id="123", exchange_segment="NSE_FNO", side="BUY", order_type="LIMIT",
        time_in_force="DAY", requested_quantity=quantity, authorized_quantity=authorized,
        lot_size=lot_size, limit_price=Decimal("100.10"), stop_price=Decimal("90"),
        reference_price=Decimal("100"), reference_price_source="ASK", strategy_id="simple_pullback",
        strategy_version="1", aegis_decision_id="aegis-1", aegis_decision="APPROVE",
        risk_decision_id="risk-1", risk_decision="ALLOW", market_data_timestamp="2026-07-13T09:19:59+05:30",
        session_state="OPEN", kill_switch_state="INACTIVE", live_trading_enabled=False,
    )


def service(tmp_path): return OrderFillLedgerService(OrderFillStore(tmp_path / "ledger.json"), now_provider=lambda: "2026-07-13T09:20:01+05:30")


def progress_to_submitted(svc, item=None):
    item = item or intent(); svc.create_order_intent(item); svc.validate_order_intent(item.intent_id, True)
    svc.authorize_order_intent(item.intent_id, risk_decision="ALLOW", kill_switch_state="INACTIVE", aegis_decision="APPROVE", session_state="OPEN", authorized_quantity=item.authorized_quantity)
    svc.append_order_event(item.intent_id, "QUEUED", "QUEUED_FOR_FUTURE_ENGINE")
    svc.append_order_event(item.intent_id, "SUBMITTED", "OBSERVED_BROKER_SUBMISSION")
    return item


def test_absent_store_is_truthful_empty_and_read_does_not_create_file(tmp_path):
    svc=service(tmp_path); assert svc.status()["empty"] is True; assert not svc.store.path.exists()


def test_intent_is_immutable_idempotent_and_safety_flags_are_fixed(tmp_path):
    svc=service(tmp_path); item=intent(); first=svc.create_order_intent(item); second=svc.create_order_intent(item)
    assert first == second and len(svc.get_order(item.intent_id)["events"]) == 1
    with pytest.raises(ValueError): svc.create_order_intent(replace(item, symbol="BANKNIFTY"))
    with pytest.raises(ValueError): replace(item, live_trading_enabled=True)
    with pytest.raises(ValueError): replace(item, broker_submission_requested=True)
    with pytest.raises(ValueError): replace(item, execution_requested=True)


@pytest.mark.parametrize("quantity,authorized,lot", [(0,0,25),(26,26,25),(25,26,25)])
def test_quantity_and_lot_contract_fails_closed(quantity, authorized, lot):
    with pytest.raises(ValueError): intent(quantity=quantity, authorized=authorized, lot_size=lot)


def test_state_machine_rejects_invalid_and_terminal_transitions(tmp_path):
    svc=service(tmp_path); svc.create_order_intent(intent())
    with pytest.raises(ValueError): svc.append_order_event("intent-1", "SUBMITTED", "SKIP_GATES")
    svc.mark_rejected("intent-1")
    with pytest.raises(ValueError): svc.append_order_event("intent-1", "VALIDATED", "TOO_LATE")


@pytest.mark.parametrize("risk,kill,aegis,session,reason", [
    ("DENY","INACTIVE","APPROVE","OPEN","RISK_AUTHORIZATION_DENY"),
    ("ALLOW","ACTIVE","APPROVE","OPEN","KILL_SWITCH_ACTIVE"),
    ("ALLOW","UNKNOWN","APPROVE","OPEN","KILL_SWITCH_UNKNOWN"),
    ("ALLOW","INACTIVE","APPROVE","CLOSED","MARKET_CLOSED"),
])
def test_authorization_evidence_fails_closed(tmp_path, risk, kill, aegis, session, reason):
    svc=service(tmp_path); svc.create_order_intent(intent()); svc.validate_order_intent("intent-1", True)
    event=svc.authorize_order_intent("intent-1", risk_decision=risk, kill_switch_state=kill, aegis_decision=aegis, session_state=session, authorized_quantity=50)
    assert event["to_state"] == "REJECTED" and event["reason_code"] == reason


@pytest.mark.parametrize("recommendation", ["CAUTION", "PAUSE", "REJECT", "UNAVAILABLE"])
def test_aegis_recommendation_never_changes_authorization_or_quantity(tmp_path, recommendation):
    svc=service(tmp_path); svc.create_order_intent(intent()); svc.validate_order_intent("intent-1", True)
    event=svc.authorize_order_intent("intent-1", risk_decision="ALLOW", kill_switch_state="INACTIVE", aegis_decision=recommendation, session_state="OPEN", authorized_quantity=50)
    assert event["to_state"] == "AUTHORIZED"
    assert event["details"]["authorized_quantity"] == 50
    assert event["details"]["aegis_execution_influence"] == "ZERO"


def test_weighted_average_partial_and_complete_fill(tmp_path):
    svc=service(tmp_path); progress_to_submitted(svc)
    svc.append_fill(FillEvent("fill-1","intent-1","2026-07-13T09:21:00+05:30",20,Decimal("100"),"BUY"))
    assert svc.get_order("intent-1")["state"] == "PARTIALLY_FILLED"
    svc.append_fill(FillEvent("fill-2","intent-1","2026-07-13T09:22:00+05:30",30,Decimal("110"),"BUY"))
    order=svc.get_order("intent-1"); assert order["state"] == "FILLED" and Decimal(order["average_fill_price"]) == Decimal("106")
    assert order["remaining_authorized_quantity"] == 0 and order["fill_application_applied"] is False


def test_overfill_is_preserved_and_requires_reconciliation(tmp_path):
    svc=service(tmp_path); progress_to_submitted(svc)
    svc.append_fill(FillEvent("fill-x","intent-1","2026-07-13T09:21:00+05:30",51,Decimal("100"),"BUY"))
    order=svc.get_order("intent-1"); assert order["state"] == "RECONCILIATION_REQUIRED" and order["filled_quantity"] == 51


def test_fill_replay_is_idempotent_and_conflict_fails(tmp_path):
    svc=service(tmp_path); progress_to_submitted(svc); fill=FillEvent("fill-1","intent-1","2026-07-13T09:21:00+05:30",20,Decimal("100"),"BUY")
    svc.append_fill(fill); svc.append_fill(fill); assert len(svc.fills("intent-1")["fills"]) == 1
    with pytest.raises(ValueError): svc.append_fill(replace(fill, price=Decimal("101")))


def test_slippage_sign_and_reference_unavailable():
    assert Decimal(slippage("BUY","101","100","ASK")["per_unit"]) == 1
    assert Decimal(slippage("SELL","99","100","BID")["per_unit"]) == 1
    assert Decimal(slippage("BUY","99","100","ASK")["per_unit"]) == -1
    assert slippage("BUY","99",None,"UNAVAILABLE")["status"] == "UNAVAILABLE"


def test_reference_hierarchy_is_side_quote_then_mid_ltp():
    assert select_reference_price("BUY", {"ask": "101", "mid": "100", "ltp": "99"}) == (Decimal("101"), "ASK")
    assert select_reference_price("SELL", {"mid": "100", "ltp": "99"}) == (Decimal("100"), "MID")
    assert select_reference_price("BUY", {"ltp": "99"}) == (Decimal("99"), "LTP")
    assert select_reference_price("BUY", {}) == (None, "UNAVAILABLE")


def test_cost_contract_is_itemized_decimal_and_truthfully_estimated():
    value=costs(25,"100.25"); assert value["status"] == "ESTIMATED" and set(value["items"]) == {"brokerage","transaction_charges","taxes","other"}
    assert value["schedule"]["accuracy_claim"] == "NOT_REGULATORY_OR_BROKER_RECONCILED"


def test_corruption_fails_closed_and_is_not_repaired(tmp_path):
    path=tmp_path/"ledger.json"; path.write_text("{bad",encoding="utf-8"); before=path.read_bytes(); svc=OrderFillLedgerService(OrderFillStore(path))
    assert svc.status()["health"] == "CORRUPT_FAIL_CLOSED" and svc.integrity()["status"] == "CORRUPT_FAIL_CLOSED" and path.read_bytes() == before


def test_restart_reconstructs_state(tmp_path):
    path=tmp_path/"ledger.json"; first=OrderFillLedgerService(OrderFillStore(path)); progress_to_submitted(first)
    second=OrderFillLedgerService(OrderFillStore(path)); assert second.get_order("intent-1")["state"] == "SUBMITTED"


def test_retention_removes_only_old_terminal_orders(tmp_path):
    svc=OrderFillLedgerService(OrderFillStore(tmp_path/"ledger.json", max_terminal_orders=1))
    svc.create_order_intent(intent("terminal-1")); svc.mark_rejected("terminal-1")
    svc.create_order_intent(intent("active-1")); svc.create_order_intent(intent("terminal-2")); svc.mark_rejected("terminal-2")
    assert svc.get_order("active-1")["state"] == "INTENT_CREATED"
    assert {row["intent"]["intent_id"] for row in svc.list_orders()["orders"]} == {"active-1", "terminal-2"}


def test_fill_application_request_is_never_applied(tmp_path):
    svc=service(tmp_path); progress_to_submitted(svc); svc.append_fill(FillEvent("fill-1","intent-1","2026-07-13T09:21:00+05:30",50,Decimal("100"),"BUY"))
    assert svc.get_fill("fill-1")["fill_application_request"]["applied"] is False


@pytest.mark.safety
def test_service_has_no_execution_or_broker_submission_method():
    prohibited=("submit_order","execute_order","place_order","send_order","apply_fill_to_paper_state","automatic_fill")
    assert all(not hasattr(OrderFillLedgerService,name) for name in prohibited)


@pytest.mark.safety
def test_get_only_routes_are_empty_and_non_mutating(monkeypatch, tmp_path):
    from app import main
    svc=service(tmp_path); monkeypatch.setattr(main,"order_fill_ledger",svc)
    assert main.orders_status()["empty"] is True
    assert main.orders()["orders"] == []
    assert main.orders_integrity()["status"] == "HEALTHY"
    assert main.fills()["fills"] == []
    assert not svc.store.path.exists()
    paths={route.path for route in app.routes if route.path.startswith("/v1/orders") or route.path.startswith("/v1/fills")}
    for route in app.routes:
        if route.path in paths: assert set(route.methods or ()) == {"GET"}


def test_frontend_contract_is_read_only_and_visible():
    page=open("citadel-dashboard/src/app/page.tsx",encoding="utf-8").read(); css=open("citadel-dashboard/src/app/globals.css",encoding="utf-8").read()
    assert ("Order & Fill Operations" in page or "ORDER & FILL OPERATIONS" in page.upper()) and "feedSelectors.orderLedger" in page and "broker_submission" in page
    assert "order-ledger-section" in css or "OrderLedgerPanel" in page
    assert all(token not in page for token in ("submitOrder(","placeOrder(","executeOrder("))
