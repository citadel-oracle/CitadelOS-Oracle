"""Isolated development paper fills; never shares production ledgers or state."""

import hashlib
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.execution.paper_state import DuplicatePaperEvent
from src.order_ledger.models import FillEvent, OrderIntent
from src.paper_trading.fills import SimulatedFillModel


IST = ZoneInfo("Asia/Kolkata")


class DevelopmentPaperExecutionEngine:
    def __init__(self, *, ledger, paper_state, fill_model=None, clock=None):
        self.ledger = ledger; self.paper_state = paper_state
        self.fill_model = fill_model or SimulatedFillModel(); self.clock = clock or (lambda: datetime.now(IST))

    def enter(self, *, request_id, contract, strategy_signal, weighted_decision, risk_decision, candle_timestamp, replay_id):
        if not risk_decision.allowed: return {"status": "DENIED", "reason": risk_decision.reason_code}
        if weighted_decision.get("decision") != "ALLOW": return {"status": "DENIED", "reason": f"DEVELOPMENT_{weighted_decision.get('decision','UNAVAILABLE')}"}
        now = self.clock(); intent_id = "deventry_" + hashlib.sha256(request_id.encode()).hexdigest()[:20]
        intent = OrderIntent(
            intent_id, now.isoformat(), "NIFTY", contract.security_id, contract.exchange_segment, "BUY", "MARKET", "DAY",
            contract.lot_size, contract.lot_size, contract.lot_size, None, None, Decimal(str(contract.top_ask_price or contract.ltp)),
            "ASK" if contract.top_ask_price else "LTP", strategy_signal["strategy"], strategy_signal.get("profile_version"),
            weighted_decision["decision_id"], "DEVELOPMENT_WEIGHTED_ALLOW", "development-risk-" + request_id, risk_decision.decision,
            str(candle_timestamp), "OPEN", "INACTIVE", False,
            metadata={"paper_only": True, "development_only": True, "production_state_mutated": False, "request_id": request_id,
                      "replay_id": replay_id, "underlying": "NIFTY", "option_type": contract.option_type, "strike": contract.strike,
                      "expiry": contract.expiry, "underlying_entry": strategy_signal["entry"], "underlying_stop": strategy_signal["sl"],
                      "underlying_target": strategy_signal["target"], "weighted_score": weighted_decision["weighted_score"],
                      "module_contributions": weighted_decision["module_contributions"], "confidence": weighted_decision["confidence"],
                      "why_trade": weighted_decision["why_trade"], "no_averaging": True, "no_pyramiding": True})
        self.ledger.create_order_intent(intent)
        self.ledger.validate_order_intent(intent_id, True)
        self.ledger.append_order_event(intent_id, "AUTHORIZED", "DEVELOPMENT_WEIGHTED_AND_RISK_ALLOWED", {"authorized_quantity": contract.lot_size, "weighted_decision": "ALLOW", "risk_decision": "ALLOW", "kill_switch_state": "INACTIVE"}, actor="DEVELOPMENT_PAPER_ENGINE")
        self.ledger.append_order_event(intent_id, "QUEUED", "DEVELOPMENT_PAPER_ENGINE_QUEUED", actor="DEVELOPMENT_PAPER_ENGINE")
        self.ledger.append_order_event(intent_id, "SUBMITTED", "SIMULATED_SUBMISSION_NO_BROKER", actor="DEVELOPMENT_PAPER_ENGINE")
        simulated = self.fill_model.fill(intent_id=intent_id, contract=contract, side="BUY")
        fill = FillEvent(simulated.fill_id, intent_id, simulated.timestamp, simulated.quantity, Decimal(str(simulated.price)), "BUY", source="DEVELOPMENT_SIMULATED_REAL_MARKET_QUOTE")
        self.ledger.append_fill(fill)
        if simulated.partial: return {"status": "PARTIALLY_FILLED", "intent_id": intent_id, "fill": simulated.to_dict(), "paper_state_applied": False}
        paper_event_id = "development-open-" + simulated.fill_id
        try:
            position = self.paper_state.open_position(position_id=intent_id, request_id=request_id, event_id=paper_event_id, symbol="NIFTY", side="BUY", raw_quantity=simulated.quantity, entry_price=simulated.price, instrument_id=contract.security_id, lot_size=contract.lot_size, option_type=contract.option_type, strike=contract.strike, expiry=contract.expiry, confidence=weighted_decision["confidence"], reason="; ".join(weighted_decision["why_trade"]))
        except DuplicatePaperEvent:
            position = next((item for item in self.paper_state.load().open_positions if item.position_id == intent_id), None)
            if position is None: raise
        self.ledger.record_fill_application(simulated.fill_id, paper_event_id=paper_event_id, applied_at=now.isoformat())
        return {"status": "OPENED", "intent_id": intent_id, "fill": simulated.to_dict(), "position": position.to_dict(), "paper_state_applied": True}

    def pending_entry(self):
        rows = self.ledger.list_orders(limit=100)["orders"]
        return next((row for row in rows if row["state"] == "PARTIALLY_FILLED" and (row["intent"].get("metadata") or {}).get("development_only")), None)

    def continue_entry(self, contract):
        order = self.pending_entry()
        if not order: return {"status": "NO_PENDING_ENTRY"}
        remaining = int(order["remaining_authorized_quantity"])
        simulated = self.fill_model.fill(intent_id=order["intent"]["intent_id"], contract=contract, side="BUY", quantity=remaining)
        fill = FillEvent(simulated.fill_id, order["intent"]["intent_id"], simulated.timestamp, simulated.quantity, Decimal(str(simulated.price)), "BUY", source="DEVELOPMENT_SIMULATED_REAL_MARKET_QUOTE")
        self.ledger.append_fill(fill); rebuilt = self.ledger.get_order(order["intent"]["intent_id"])
        if rebuilt["state"] != "FILLED": return {"status": "PARTIALLY_FILLED", "intent_id": order["intent"]["intent_id"], "fill": simulated.to_dict(), "paper_state_applied": False}
        meta = order["intent"]["metadata"]; event_id = "development-open-" + order["intent"]["intent_id"]
        try:
            position = self.paper_state.open_position(position_id=order["intent"]["intent_id"], request_id=meta["request_id"], event_id=event_id, symbol="NIFTY", side="BUY", raw_quantity=int(rebuilt["filled_quantity"]), entry_price=float(rebuilt["average_fill_price"]), instrument_id=order["intent"]["instrument_id"], lot_size=order["intent"]["lot_size"], option_type=meta["option_type"], strike=meta["strike"], expiry=meta["expiry"], confidence=meta.get("confidence"), reason="; ".join(meta.get("why_trade") or []))
        except DuplicatePaperEvent:
            position = next((item for item in self.paper_state.load().open_positions if item.position_id == order["intent"]["intent_id"]), None)
            if position is None: raise
        for item in rebuilt["fills"]: self.ledger.record_fill_application(item["fill_id"], paper_event_id=event_id, applied_at=self.clock().isoformat())
        return {"status": "OPENED", "intent_id": order["intent"]["intent_id"], "position": position.to_dict(), "paper_state_applied": True}

    def mark(self, *, position, price, timestamp):
        event_id = "development-mark-" + hashlib.sha256(f"{position.position_id}|{timestamp}|{price}".encode()).hexdigest()[:20]
        try: return self.paper_state.update_mark(position.position_id, float(price), event_id)
        except DuplicatePaperEvent: return next(item for item in self.paper_state.load().open_positions if item.position_id == position.position_id)

    def exit(self, *, position, contract, reason, timestamp):
        request_id = f"development-exit-{position.position_id}-{reason}-{timestamp}"; intent_id = "devexit_" + hashlib.sha256(request_id.encode()).hexdigest()[:20]; now = self.clock()
        intent = OrderIntent(intent_id, now.isoformat(), "NIFTY", contract.security_id, contract.exchange_segment, "SELL", "MARKET", "DAY", position.remaining_quantity, position.remaining_quantity, position.lot_size, None, None, Decimal(str(contract.top_bid_price or contract.ltp)), "BID" if contract.top_bid_price else "LTP", "DEVELOPMENT_EXIT_ENGINE", "DEVELOPMENT_V1", "DEVELOPMENT_RISK_REDUCING_EXIT", "DEVELOPMENT_RISK_REDUCING_EXIT", "development-risk-reducing-exit", "ALLOW", str(timestamp), "OPEN", "INACTIVE", False, metadata={"paper_only": True, "development_only": True, "position_id": position.position_id, "exit_reason": reason})
        self.ledger.create_order_intent(intent); self.ledger.validate_order_intent(intent_id, True)
        self.ledger.append_order_event(intent_id, "AUTHORIZED", "DEVELOPMENT_RISK_REDUCING_EXIT", {"authorized_quantity": position.remaining_quantity}, actor="DEVELOPMENT_PAPER_ENGINE")
        self.ledger.append_order_event(intent_id, "QUEUED", "DEVELOPMENT_PAPER_ENGINE_QUEUED", actor="DEVELOPMENT_PAPER_ENGINE")
        self.ledger.append_order_event(intent_id, "SUBMITTED", "SIMULATED_SUBMISSION_NO_BROKER", actor="DEVELOPMENT_PAPER_ENGINE")
        simulated = self.fill_model.fill(intent_id=intent_id, contract=contract, side="SELL", quantity=position.remaining_quantity)
        fill = FillEvent(simulated.fill_id, intent_id, simulated.timestamp, simulated.quantity, Decimal(str(simulated.price)), "SELL", source="DEVELOPMENT_SIMULATED_REAL_MARKET_QUOTE"); self.ledger.append_fill(fill)
        if simulated.partial: return {"status": "PARTIALLY_FILLED", "intent_id": intent_id, "fill": simulated.to_dict(), "paper_state_applied": False}
        event_id = "development-close-" + simulated.fill_id
        try: closed = self.paper_state.close_position(position.position_id, simulated.price, event_id, exit_reason=reason)
        except DuplicatePaperEvent: closed = next(item for item in self.paper_state.load().closed_trades if item.close_event_id == event_id)
        self.ledger.record_fill_application(simulated.fill_id, paper_event_id=event_id, applied_at=now.isoformat())
        return {"status": "CLOSED", "intent_id": intent_id, "fill": simulated.to_dict(), "closed_trade": closed.to_dict(), "paper_state_applied": True}

    def active_plan(self, position_id):
        for order in self.ledger.list_orders(limit=100)["orders"]:
            meta = order["intent"].get("metadata") or {}
            if order["intent"]["intent_id"] == position_id and meta.get("development_only"):
                return {"underlying_entry": meta.get("underlying_entry"), "underlying_stop": meta.get("underlying_stop"), "underlying_target": meta.get("underlying_target"), "replay_id": meta.get("replay_id"), "weighted_score": meta.get("weighted_score")}
        return None
