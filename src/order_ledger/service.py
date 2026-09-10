"""Audit-only Order & Fill Ledger service; intentionally has no submission API."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Optional

from .accounting import costs, slippage
from .models import FillApplicationRequest, FillEvent, OrderEvent, OrderIntent, stable_id
from .state_machine import TERMINAL_STATES, validate_transition
from .storage import LedgerCorrupt, LedgerUnavailable, OrderFillStore


class OrderFillLedgerService:
    def __init__(self, store=None, now_provider=None):
        self.store = store or OrderFillStore()
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc).isoformat())

    def create_order_intent(self, intent: OrderIntent) -> dict:
        def operation(document):
            existing = next((row for row in document["intents"] if row["intent_id"] == intent.intent_id), None)
            if existing:
                if existing != intent.to_dict(): raise ValueError("intent id conflicts with immutable payload")
                return False, self._order(document, intent.intent_id)
            document["intents"].append(intent.to_dict())
            event = OrderEvent(stable_id("evt", {"intent": intent.intent_id, "state": "INTENT_CREATED"}), intent.intent_id, intent.created_at, None, "INTENT_CREATED", "INTENT_CAPTURED", "ORDER_LEDGER")
            document["events"].append(event.to_dict())
            return True, self._order(document, intent.intent_id)
        return self.store.update(operation)

    def validate_order_intent(self, intent_id: str, valid: bool, reason_code="VALIDATION_PASSED"):
        return self.append_order_event(intent_id, "VALIDATED" if valid else "REJECTED", reason_code)

    def authorize_order_intent(self, intent_id: str, *, risk_decision: str, kill_switch_state: str, aegis_decision: str, session_state: str, authorized_quantity: int):
        target, reason = "AUTHORIZED", "AUTHORIZATION_EVIDENCE_ACCEPTED"
        if risk_decision != "ALLOW": target, reason = "REJECTED", "RISK_AUTHORIZATION_DENY"
        elif kill_switch_state != "INACTIVE": target, reason = "REJECTED", f"KILL_SWITCH_{kill_switch_state}"
        elif session_state not in {"OPEN", "SPECIAL_SESSION"}: target, reason = "REJECTED", "MARKET_CLOSED"
        order = self.get_order(intent_id)
        requested = int(order["intent"]["requested_quantity"])
        if type(authorized_quantity) is not int or not 0 < authorized_quantity <= requested: raise ValueError("invalid authorized quantity")
        return self.append_order_event(intent_id, target, reason, {"authorized_quantity": authorized_quantity, "risk_decision": risk_decision, "kill_switch_state": kill_switch_state, "aegis_advisory": aegis_decision, "aegis_execution_influence": "ZERO", "session_state": session_state})

    def append_order_event(self, intent_id: str, target: str, reason_code: str, details: Optional[Mapping[str, Any]] = None, actor="ORDER_LEDGER", event_id=None, occurred_at=None):
        def operation(document):
            self._intent(document, intent_id)
            current = self._state(document, intent_id)
            identifier = event_id or stable_id("evt", {"intent": intent_id, "from": current, "to": target, "reason": reason_code, "details": details or {}})
            existing = next((row for row in document["events"] if row["event_id"] == identifier), None)
            if existing: return False, existing
            validate_transition(current, target)
            event = OrderEvent(identifier, intent_id, occurred_at or self.now_provider(), current, target, reason_code, actor, details=dict(details or {}))
            document["events"].append(event.to_dict())
            return True, event.to_dict()
        return self.store.update(operation)

    def append_fill(self, fill: FillEvent):
        def operation(document):
            intent = self._intent(document, fill.intent_id)
            existing = next((row for row in document["fills"] if row["fill_id"] == fill.fill_id), None)
            if existing:
                if existing != fill.to_dict(): raise ValueError("fill id conflicts with immutable payload")
                return False, existing
            state = self._state(document, fill.intent_id)
            if state not in {"SUBMITTED", "ACKNOWLEDGED", "PARTIALLY_FILLED", "CANCEL_PENDING", "RECONCILIATION_REQUIRED"}: raise ValueError("fill is invalid for current order state")
            previous = sum(int(row["quantity"]) for row in document["fills"] if row["intent_id"] == fill.intent_id)
            authorized = self._authorized_quantity(document, intent)
            document["fills"].append(fill.to_dict())
            total = previous + fill.quantity
            target = "RECONCILIATION_REQUIRED" if total > authorized else "FILLED" if total == authorized else "PARTIALLY_FILLED"
            event = OrderEvent(stable_id("evt", {"fill": fill.fill_id, "state": target}), fill.intent_id, fill.occurred_at, state, target, "FILL_QUANTITY_EXCEEDS_AUTHORIZATION" if total > authorized else "FILL_OBSERVED", "ORDER_LEDGER", broker_order_id=fill.broker_order_id, details={"fill_id": fill.fill_id, "cumulative_filled_quantity": total})
            validate_transition(state, target)
            document["events"].append(event.to_dict())
            return True, fill.to_dict()
        return self.store.update(operation)

    def request_cancel(self, intent_id: str): return self.append_order_event(intent_id, "CANCEL_PENDING", "CANCEL_REQUEST_RECORDED")
    def mark_rejected(self, intent_id: str, reason="REJECTED"): return self.append_order_event(intent_id, "REJECTED", reason)
    def mark_expired(self, intent_id: str): return self.append_order_event(intent_id, "EXPIRED", "ORDER_EXPIRED")

    def status(self):
        try:
            document = self.store.load(); orders = [self._order(document, row["intent_id"]) for row in document["intents"]]
            active = sum(order["state"] not in TERMINAL_STATES for order in orders)
            return {"status": "READY", "health": "HEALTHY", "schema_version": 1, "mode": "AUDIT_ONLY", "order_count": len(orders), "active_order_count": active, "terminal_order_count": len(orders)-active, "fill_count": len(document["fills"]), "execution_engine": "NOT_ACTIVE", "broker_submission": "DISABLED", "live_trading_enabled": False, "paper_state_mutation": False, "empty": not orders, "warnings": []}
        except LedgerUnavailable:
            return {"status": "UNAVAILABLE", "health": "CORRUPT_FAIL_CLOSED", "schema_version": 1, "mode": "AUDIT_ONLY", "order_count": None, "active_order_count": None, "terminal_order_count": None, "fill_count": None, "execution_engine": "NOT_ACTIVE", "broker_submission": "DISABLED", "live_trading_enabled": False, "paper_state_mutation": False, "empty": None, "warnings": ["ORDER_LEDGER_UNAVAILABLE_OR_CORRUPT"]}

    def list_orders(self, limit=50, state=None):
        document = self.store.load(); rows = [self._order(document, item["intent_id"]) for item in document["intents"]]
        if state: rows = [row for row in rows if row["state"] == state]
        bounded = max(1, min(int(limit), 100)); return {"status": "available", "orders": list(reversed(rows[-bounded:])), "count": len(rows), "limit": bounded}

    def get_order(self, intent_id): return self._order(self.store.load(), intent_id)
    def events(self, intent_id, limit=100): return {"status": "available", "events": [row for row in self.store.load()["events"] if row["intent_id"] == intent_id][-max(1,min(int(limit),100)): ]}
    def fills(self, intent_id=None, limit=100):
        rows = self.store.load()["fills"]
        if intent_id: rows = [row for row in rows if row["intent_id"] == intent_id]
        return {"status": "available", "fills": list(reversed(rows[-max(1,min(int(limit),100)): ]))}
    def get_fill(self, fill_id):
        document=self.store.load(); row = next((item for item in document["fills"] if item["fill_id"] == fill_id), None)
        if row is None: raise KeyError(fill_id)
        applied=next((item for item in document["fill_applications"] if item["fill_id"]==fill_id),None)
        request=FillApplicationRequest(row["fill_id"],row["intent_id"]).to_dict(); request.update(applied or {})
        return {**row, "fill_application_request": request}

    def record_fill_application(self, fill_id, *, paper_event_id, applied_at):
        def operation(document):
            fill=next((item for item in document["fills"] if item["fill_id"]==fill_id),None)
            if fill is None: raise KeyError(fill_id)
            existing=next((item for item in document["fill_applications"] if item["fill_id"]==fill_id),None)
            value={"fill_id":fill_id,"intent_id":fill["intent_id"],"applied":True,"target":"PAPER_STATE","paper_event_id":str(paper_event_id),"applied_at":str(applied_at),"schema_version":1}
            if existing:
                if existing!=value: raise ValueError("fill application identity conflict")
                return False,existing
            document["fill_applications"].append(value); return True,value
        return self.store.update(operation)

    def cost_summary(self, intent_id):
        order = self.get_order(intent_id); rows = order["fills"]
        return {"status": "available", "intent_id": intent_id, "fills": [{"fill_id": row["fill_id"], **costs(int(row["quantity"]), row["price"])} for row in rows], "accuracy": "ESTIMATE_ONLY_NOT_REGULATORY_OR_BROKER_RECONCILED"}

    def slippage_summary(self, intent_id):
        order = self.get_order(intent_id); intent = order["intent"]
        return {"status": "available", "intent_id": intent_id, "fills": [{"fill_id": row["fill_id"], **slippage(row["side"], row["price"], intent.get("reference_price"), intent.get("reference_price_source") or "UNAVAILABLE")} for row in order["fills"]]}

    def integrity(self):
        try:
            document = self.store.load(); issues=[]
            intent_ids={row.get("intent_id") for row in document["intents"]}
            for row in [*document["events"], *document["fills"]]:
                if row.get("intent_id") not in intent_ids: issues.append("ORPHAN_RECORD")
            return {"status": "HEALTHY" if not issues else "RECONCILIATION_REQUIRED", "schema_version": 1, "issue_count": len(issues), "issues": sorted(set(issues)), "broker_reconciliation": "NOT_PERFORMED"}
        except LedgerCorrupt: return {"status": "CORRUPT_FAIL_CLOSED", "schema_version": 1, "issue_count": None, "issues": ["LEDGER_CORRUPT"], "broker_reconciliation": "NOT_PERFORMED"}

    @staticmethod
    def _intent(document, intent_id):
        row = next((item for item in document["intents"] if item["intent_id"] == intent_id), None)
        if row is None: raise KeyError(intent_id)
        return row
    @staticmethod
    def _state(document, intent_id):
        rows=[row for row in document["events"] if row["intent_id"] == intent_id]
        return rows[-1]["to_state"] if rows else None
    def _authorized_quantity(self, document, intent):
        events=[row for row in document["events"] if row["intent_id"] == intent["intent_id"] and row["to_state"] == "AUTHORIZED"]
        return int(events[-1].get("details", {}).get("authorized_quantity", intent["authorized_quantity"])) if events else int(intent["authorized_quantity"])
    def _order(self, document, intent_id):
        intent=self._intent(document,intent_id); events=[row for row in document["events"] if row["intent_id"]==intent_id]; fills=[row for row in document["fills"] if row["intent_id"]==intent_id]
        total=sum(int(row["quantity"]) for row in fills); value=sum(Decimal(row["price"])*int(row["quantity"]) for row in fills)
        applied={row["fill_id"] for row in document.get("fill_applications",[]) if row["intent_id"]==intent_id and row.get("applied") is True}
        return {"intent": intent, "state": events[-1]["to_state"] if events else None, "events": events, "fills": fills, "filled_quantity": total, "average_fill_price": format(value/total,"f") if total else None, "remaining_authorized_quantity": max(0,self._authorized_quantity(document,intent)-total), "reconciliation_state": "REQUIRED" if events and events[-1]["to_state"]=="RECONCILIATION_REQUIRED" else "NOT_REQUIRED", "fill_application_applied": bool(fills) and all(row["fill_id"] in applied for row in fills)}
