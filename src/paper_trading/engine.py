"""Paper-only order/fill execution and authoritative Paper State application."""

import hashlib
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.execution.paper_state import DuplicatePaperEvent, PaperStateService
from src.order_ledger.models import FillEvent, OrderIntent
from src.order_ledger.service import OrderFillLedgerService

from .fills import SimulatedFillModel

IST=ZoneInfo("Asia/Kolkata")


class PaperExecutionEngine:
    def __init__(self, ledger=None, paper_state=None, fill_model=None, clock=None):
        self.ledger=ledger or OrderFillLedgerService(); self.paper_state=paper_state or PaperStateService(); self.fill_model=fill_model or SimulatedFillModel(); self.clock=clock or (lambda:datetime.now(IST))

    def enter(self, *, request_id, contract, strategy_signal, aegis_decision=None, aegis_advisory=None, risk_decision, candle_timestamp):
        if not risk_decision.allowed: return {"status":"DENIED","reason":risk_decision.reason_code}
        advisory=aegis_advisory or aegis_decision or {"recommendation":"UNAVAILABLE","execution_influence":"ZERO"}
        now=self.clock(); intent_id="paperentry_"+hashlib.sha256(request_id.encode()).hexdigest()[:20]
        recommendation=str(advisory.get("recommendation") or advisory.get("decision") or "UNAVAILABLE")
        advisory_metadata={"assessment":advisory.get("decision"),"recommendation":recommendation,"would_recommend":advisory.get("would_recommend") or recommendation,"reasons":"|".join(str(item) for item in (advisory.get("dominant_reasons") or advisory.get("hard_gate_reasons") or [])),"confidence":advisory.get("confidence") if advisory.get("confidence") is not None else advisory.get("decision_score"),"calculation_timestamp":advisory.get("calculation_timestamp") or advisory.get("generated_at"),"input_snapshot":advisory.get("input_snapshot"),"input_snapshot_version":advisory.get("input_snapshot_version"),"input_fingerprint":advisory.get("input_fingerprint"),"execution_influence":"ZERO"}
        intent=OrderIntent(intent_id,now.isoformat(),"NIFTY",contract.security_id,contract.exchange_segment,"BUY","MARKET","DAY",contract.lot_size,contract.lot_size,contract.lot_size,None,None,Decimal(str(contract.top_ask_price or contract.ltp)),"ASK" if contract.top_ask_price else "LTP",strategy_signal["strategy"],None,str(advisory.get("decision_id") or "UNAVAILABLE"),recommendation,"paper-risk-"+request_id,risk_decision.decision,str(candle_timestamp),"OPEN","INACTIVE",False,metadata={"paper_only":True,"request_id":request_id,"underlying":"NIFTY","option_type":contract.option_type,"strike":contract.strike,"expiry":contract.expiry,"underlying_entry":strategy_signal["entry"],"underlying_stop":strategy_signal["sl"],"underlying_target":strategy_signal["target"],"confidence":strategy_signal.get("confidence"),"reason":strategy_signal.get("reason","")[:160],"no_averaging":True,"no_pyramiding":True,"aegis_advisory":advisory_metadata})
        self.ledger.create_order_intent(intent); self.ledger.validate_order_intent(intent_id,True); self.ledger.authorize_order_intent(intent_id,risk_decision="ALLOW",kill_switch_state="INACTIVE",aegis_decision=recommendation,session_state="OPEN",authorized_quantity=contract.lot_size); self.ledger.append_order_event(intent_id,"QUEUED","PAPER_ENGINE_QUEUED"); self.ledger.append_order_event(intent_id,"SUBMITTED","SIMULATED_SUBMISSION_NO_BROKER")
        simulated=self.fill_model.fill(intent_id=intent_id,contract=contract,side="BUY")
        fill=FillEvent(simulated.fill_id,intent_id,simulated.timestamp,simulated.quantity,Decimal(str(simulated.price)),"BUY",source="SIMULATED_REAL_MARKET_QUOTE")
        self.ledger.append_fill(fill)
        if simulated.partial: return {"status":"PARTIALLY_FILLED","intent_id":intent_id,"fill":simulated.to_dict(),"paper_state_applied":False}
        paper_event_id="paper-open-"+simulated.fill_id
        try:
            position=self.paper_state.open_position(position_id=intent_id,request_id=request_id,event_id=paper_event_id,symbol="NIFTY",side="BUY",raw_quantity=simulated.quantity,entry_price=simulated.price,instrument_id=contract.security_id,lot_size=contract.lot_size,option_type=contract.option_type,strike=contract.strike,expiry=contract.expiry,stop_price=None,target_price=None,confidence=strategy_signal.get("confidence"),reason=strategy_signal.get("reason", ""))
        except DuplicatePaperEvent:
            position=next((item for item in self.paper_state.load().open_positions if item.position_id==intent_id),None)
            if position is None: raise
        self.ledger.record_fill_application(simulated.fill_id,paper_event_id=paper_event_id,applied_at=now.isoformat())
        return {"status":"OPENED","intent_id":intent_id,"fill":simulated.to_dict(),"position":position.to_dict(),"paper_state_applied":True}

    def pending_entry(self):
        rows=self.ledger.list_orders(limit=100)["orders"]
        return next((row for row in rows if row["state"]=="PARTIALLY_FILLED" and (row["intent"].get("metadata") or {}).get("paper_only") and row["intent"].get("strategy_id")!="PAPER_EXIT_ENGINE"),None)

    def continue_entry(self, contract):
        order=self.pending_entry()
        if not order: return {"status":"NO_PENDING_ENTRY"}
        remaining=int(order["remaining_authorized_quantity"]); simulated=self.fill_model.fill(intent_id=order["intent"]["intent_id"],contract=contract,side="BUY",quantity=remaining)
        fill=FillEvent(simulated.fill_id,order["intent"]["intent_id"],simulated.timestamp,simulated.quantity,Decimal(str(simulated.price)),"BUY",source="SIMULATED_REAL_MARKET_QUOTE"); self.ledger.append_fill(fill); rebuilt=self.ledger.get_order(order["intent"]["intent_id"])
        if rebuilt["state"]!="FILLED": return {"status":"PARTIALLY_FILLED","intent_id":order["intent"]["intent_id"],"fill":simulated.to_dict(),"paper_state_applied":False}
        meta=order["intent"]["metadata"]; event_id="paper-open-"+order["intent"]["intent_id"]
        try:
            position=self.paper_state.open_position(position_id=order["intent"]["intent_id"],request_id=meta["request_id"],event_id=event_id,symbol="NIFTY",side="BUY",raw_quantity=int(rebuilt["filled_quantity"]),entry_price=float(rebuilt["average_fill_price"]),instrument_id=order["intent"]["instrument_id"],lot_size=order["intent"]["lot_size"],option_type=meta["option_type"],strike=meta["strike"],expiry=meta["expiry"],confidence=meta.get("confidence"),reason=meta.get("reason", ""))
        except DuplicatePaperEvent:
            position=next((item for item in self.paper_state.load().open_positions if item.position_id==order["intent"]["intent_id"]),None)
            if position is None: raise
        for item in rebuilt["fills"]: self.ledger.record_fill_application(item["fill_id"],paper_event_id=event_id,applied_at=self.clock().isoformat())
        return {"status":"OPENED","intent_id":order["intent"]["intent_id"],"position":position.to_dict(),"paper_state_applied":True}

    def mark(self, *, position, price, timestamp):
        event_id="paper-mark-"+hashlib.sha256(f"{position.position_id}|{timestamp}|{price}".encode()).hexdigest()[:20]
        try: updated=self.paper_state.update_mark(position.position_id,float(price),event_id)
        except DuplicatePaperEvent: updated=next(item for item in self.paper_state.load().open_positions if item.position_id==position.position_id)
        return updated

    def exit(self, *, position, contract, reason, timestamp):
        request_id=f"paper-exit-{position.position_id}-{reason}-{timestamp}"; intent_id="paperexit_"+hashlib.sha256(request_id.encode()).hexdigest()[:20]; now=self.clock()
        intent=OrderIntent(intent_id,now.isoformat(),"NIFTY",contract.security_id,contract.exchange_segment,"SELL","MARKET","DAY",position.remaining_quantity,position.remaining_quantity,position.lot_size,None,None,Decimal(str(contract.top_bid_price or contract.ltp)),"BID" if contract.top_bid_price else "LTP", "PAPER_EXIT_ENGINE",None,"RISK_REDUCING_EXIT","RISK_REDUCING_EXIT","paper-risk-reducing-exit","ALLOW",str(timestamp),"OPEN","INACTIVE",False,metadata={"paper_only":True,"position_id":position.position_id,"exit_reason":reason})
        self.ledger.create_order_intent(intent); self.ledger.validate_order_intent(intent_id,True); self.ledger.append_order_event(intent_id,"AUTHORIZED","RISK_REDUCING_PAPER_EXIT",{"authorized_quantity":position.remaining_quantity}); self.ledger.append_order_event(intent_id,"QUEUED","PAPER_ENGINE_QUEUED"); self.ledger.append_order_event(intent_id,"SUBMITTED","SIMULATED_SUBMISSION_NO_BROKER")
        simulated=self.fill_model.fill(intent_id=intent_id,contract=contract,side="SELL",quantity=position.remaining_quantity); fill=FillEvent(simulated.fill_id,intent_id,simulated.timestamp,simulated.quantity,Decimal(str(simulated.price)),"SELL",source="SIMULATED_REAL_MARKET_QUOTE"); self.ledger.append_fill(fill)
        if simulated.partial: return {"status":"PARTIALLY_FILLED","intent_id":intent_id,"fill":simulated.to_dict(),"paper_state_applied":False}
        event_id="paper-close-"+simulated.fill_id
        try: closed=self.paper_state.close_position(position.position_id,simulated.price,event_id,exit_reason=reason)
        except DuplicatePaperEvent: closed=next(item for item in self.paper_state.load().closed_trades if item.close_event_id==event_id)
        self.ledger.record_fill_application(simulated.fill_id,paper_event_id=event_id,applied_at=now.isoformat())
        return {"status":"CLOSED","intent_id":intent_id,"fill":simulated.to_dict(),"closed_trade":closed.to_dict(),"paper_state_applied":True}

    def active_plan(self, position_id):
        for order in self.ledger.list_orders(limit=100)["orders"]:
            meta=order["intent"].get("metadata") or {}
            if order["intent"]["intent_id"]==position_id and meta.get("paper_only"):
                return {"underlying_entry":meta.get("underlying_entry"),"underlying_stop":meta.get("underlying_stop"),"underlying_target":meta.get("underlying_target")}
        return None
