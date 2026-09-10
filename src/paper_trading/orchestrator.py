"""Lifecycle-owned real-data paper orchestrator; never callable from GET routes."""

import json
import os
import tempfile
import threading
from dataclasses import replace
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from src.brain.context_builder import ContextBuilder
from src.broker.dhan_client import DhanClient
from src.fvg.fvg_engine import FVGEngine
from src.forensics import DecisionEvidenceRecorder
from src.kronos.kronos_engine import KronosEngine
from src.liquidity.liquidity_engine import LiquidityEngine
from src.orderblock.order_block_engine import OrderBlockEngine
from src.scanner.indicator_builder import IndicatorBuilder
from src.structure.structure_engine import StructureEngine
from src.structure.structure_engine_v2 import StructureEngineV2
from src.timeframe.timeframe_engine import TimeframeEngine

from .contracts import ContractResolutionError, OptionContractResolver
from .engine import PaperExecutionEngine
from .models import ResolvedOptionContract
from .registry import StrategyRegistry
from .risk import PaperRiskAuthorization

IST=ZoneInfo("Asia/Kolkata")


class RealMarketPaperOrchestrator:
    SCHEMA_VERSION=1

    def __init__(self, *, candle_source, calendar, argus, aegis, registry=None, resolver=None, risk=None, engine=None, quote_client=None, state_path="logs/real_market_paper_runtime.json", clock=None, interval=3, evidence_recorder=None):
        self.candle_source=candle_source; self.calendar=calendar; self.argus=argus; self.aegis=aegis; self.registry=registry or StrategyRegistry(); self.resolver=resolver or OptionContractResolver(); self.engine=engine or PaperExecutionEngine(); self.risk=risk or PaperRiskAuthorization(paper_state=self.engine.paper_state); self.quote_client=quote_client or DhanClient(); self.state_path=Path(state_path); self.clock=clock or (lambda:datetime.now(IST)); self.interval=max(1,float(interval)); self._stop=threading.Event(); self._thread=None; self._lock=threading.Lock(); self._runtime=self._load_runtime(); self.evidence=evidence_recorder or DecisionEvidenceRecorder()
        self.indicators=IndicatorBuilder(); self.structure=StructureEngine(); self.structure_v2=StructureEngineV2(); self.liquidity=LiquidityEngine(); self.fvg=FVGEngine(); self.order_block=OrderBlockEngine(); self.timeframe=TimeframeEngine(); self.kronos=KronosEngine(); self.context=ContextBuilder()

    def start(self):
        if self._thread and self._thread.is_alive(): return
        self._stop.clear(); self._thread=threading.Thread(target=self._loop,name="real-market-paper-orchestrator",daemon=True); self._thread.start(); self.evidence.scheduler("STARTED",timestamp=self.clock().isoformat())
    def stop(self):
        self._stop.set()
        if self._thread: self._thread.join(timeout=5)
        self.evidence.scheduler("STOPPED",timestamp=self.clock().isoformat())

    def _loop(self):
        while not self._stop.wait(self.interval):
            try: self.tick()
            except Exception as error: self._record("ERROR","ORCHESTRATOR_ERROR",str(error)[:160])

    def tick(self):
        if not self._lock.acquire(blocking=False): return {"status":"SKIPPED","reason":"TICK_ALREADY_RUNNING"}
        candle=context=signal=argus_response=snapshot=aegis=contract=risk=result=None
        try:
            now=self.clock().astimezone(IST); session=self.calendar.status(now); self._runtime["session_state"]=session["session_state"]
            if self._runtime.get("reason")=="RUNTIME_STATE_CORRUPT": return {"status":"BLOCKED","reason":"RUNTIME_STATE_CORRUPT"}
            try: current_state=self.engine.paper_state.load(now.date())
            except Exception: return self._set_state("BLOCKED","PAPER_STATE_UNAVAILABLE")
            if current_state.open_positions and session["session_state"] not in {"OPEN","SPECIAL_SESSION"}: return self._set_state("BLOCKED","OVERNIGHT_POSITION_BREACH")
            self._mark_active(now, session)
            if session["session_state"] not in {"OPEN","SPECIAL_SESSION"}: return self._set_state("WAITING","MARKET_CLOSED")
            pending=self.engine.pending_entry()
            if pending:
                result=self._continue_pending(pending); self._record(result["status"],"PARTIAL_FILL_CONTINUATION",pending["intent"]["intent_id"]); self._write_runtime(); return result
            candles=self.candle_source.load_cache()
            if not candles: return self._set_state("WAITING","CLOSED_CANDLE_CACHE_EMPTY")
            candle=candles[-1]
            if candle.get("closed") is not True and candle.get("is_closed") is not True: return self._set_state("BLOCKED","INCOMPLETE_CANDLE")
            closed_at=datetime.fromisoformat(str(candle["candle_closed_at"]))
            if closed_at.astimezone(IST)>now: return self._set_state("BLOCKED","CANDLE_NOT_CLOSED")
            origin=str(candle["timestamp"])
            if origin==self._runtime.get("last_evaluated_candle"): return self._set_state("MONITORING","NO_NEW_CLOSED_CANDLE")
            self._runtime["last_evaluated_candle"]=origin
            self.evidence.scheduler("CLOSED_CANDLE_ACCEPTED",timestamp=now.isoformat(),detail={"candle_id":origin,"candle_closed_at":candle.get("candle_closed_at")})
            state=self.engine.paper_state.load(now.date())
            if state.open_positions:
                result=self._evaluate_exit(state.open_positions[0],candle,now); self.evidence.paper_lifecycle("POSITION_EVALUATED",timestamp=now.isoformat(),candle_id=origin,payload={"position_id":state.open_positions[0].position_id,"result":result}); self._write_runtime(); return result
            if now.time()>time(15,15): return self._set_state("WAITING","ENTRY_WINDOW_CLOSED")
            closed_context=self._build_context(candles); signal=self.registry.evaluate(closed_context); self._runtime["last_signal"]={key:signal.get(key) for key in ("signal","confidence","entry","sl","target","reason","strategy")}
            context=closed_context
            if signal.get("signal") not in {"BUY","SELL"}:
                self._persist_envelope(candle,context,signal,"WAITING","STRATEGY_WAIT")
                return self._set_state("WAITING","STRATEGY_WAIT")
            argus_response=self.argus.get_oi("NIFTY")
            requested_side="CE" if signal["signal"]=="BUY" else "PE"
            aegis=self.aegis.latest_advisory("NIFTY",requested_side,"simple_pullback"); self._runtime["last_aegis"]={key:aegis.get(key) for key in ("decision_id","recommendation","would_recommend","decision_score","execution_influence")}
            contract=self.resolver.resolve(argus_response,signal["signal"]); request_id=f"paper|{origin}|{signal['strategy']}|{contract.security_id}"
            fetched_at=datetime.fromisoformat(argus_response["data"]["underlying"]["fetched_at"]); risk=self.risk.authorize(request_id=request_id,contract=contract,market_timestamp=fetched_at,session_state=session["session_state"]); self._runtime["last_risk"]=risk.to_dict()
            result=self.engine.enter(request_id=request_id,contract=contract,strategy_signal=signal,aegis_advisory=aegis,risk_decision=risk,candle_timestamp=origin); self._record(result["status"],result.get("reason") or "PAPER_ENTRY",f"{contract.option_type} {contract.strike:g} {contract.expiry}"); self._persist_envelope(candle,context,signal,result["status"],result.get("reason") or "PAPER_ENTRY",snapshot=None,aegis=aegis,argus=argus_response,contract=contract,risk=risk,paper=result); self._write_runtime(); return result
        except ContractResolutionError as error:
            if candle is not None and context is not None and signal is not None:
                self._persist_envelope(candle,context,signal,"BLOCKED","CONTRACT_RESOLUTION_UNAVAILABLE",snapshot=snapshot,aegis=aegis,argus=argus_response)
            return self._set_state("BLOCKED","CONTRACT_RESOLUTION_UNAVAILABLE",str(error))
        finally: self._lock.release()

    def _mark_active(self, now, session):
        try: state=self.engine.paper_state.load(now.date())
        except Exception: return
        if not state.open_positions: return
        position=state.open_positions[0]; quote=self.quote_client.get_quote("NSE_FNO",position.instrument_id)
        ltp=quote.get("ltp")
        if ltp is None:
            self._record("DEGRADED","OPTION_MARK_UNAVAILABLE",position.instrument_id or "unknown"); return
        self.engine.mark(position=position,price=ltp,timestamp=now.isoformat()); self._runtime["last_mark"]={"price":ltp,"timestamp":now.isoformat(),"source":"DHAN_MARKETFEED_OHLC"}
        if now.time()>=time(15,20):
            contract=self._position_contract(position,float(ltp)); result=self.engine.exit(position=position,contract=contract,reason="MANDATORY_INTRADAY_SQUARE_OFF",timestamp=now.isoformat()); self._record(result["status"],"MANDATORY_INTRADAY_SQUARE_OFF",position.instrument_id or "unknown")

    def _continue_pending(self, order):
        intent=order["intent"]; meta=intent.get("metadata") or {}; quote=self.quote_client.get_quote("NSE_FNO",intent["instrument_id"]); ltp=quote.get("ltp")
        if ltp is None: return {"status":"BLOCKED","reason":"PENDING_FILL_QUOTE_UNAVAILABLE"}
        contract=ResolvedOptionContract(str(intent["instrument_id"]),str(intent["exchange_segment"]),"NIFTY",str(meta["option_type"]),float(meta["strike"]),str(meta["expiry"]),int(intent["lot_size"]),float(ltp),None,None,None,None,"ORDER_INTENT","DHAN_MARKETFEED_OHLC")
        return self.engine.continue_entry(contract)

    def _evaluate_exit(self,position,candle,now):
        plan=self.engine.active_plan(position.position_id)
        if not plan: return self._set_state("BLOCKED","POSITION_PLAN_UNAVAILABLE")
        close=float(candle["close"]); reason=None
        if position.option_type=="CE":
            if close<=float(plan["underlying_stop"]): reason="UNDERLYING_STOP_HIT"
            elif close>=float(plan["underlying_target"]): reason="UNDERLYING_TARGET_HIT"
        elif position.option_type=="PE":
            if close>=float(plan["underlying_stop"]): reason="UNDERLYING_STOP_HIT"
            elif close<=float(plan["underlying_target"]): reason="UNDERLYING_TARGET_HIT"
        if not reason: return self._set_state("MONITORING","POSITION_OPEN")
        refreshed=next((item for item in self.engine.paper_state.load(now.date()).open_positions if item.position_id==position.position_id),position); contract=self._position_contract(refreshed,refreshed.mark_price); result=self.engine.exit(position=refreshed,contract=contract,reason=reason,timestamp=candle["timestamp"]); self._record(result["status"],reason,position.instrument_id or "unknown"); return result

    def _build_context(self,candles):
        indicators=self.indicators.build(candles); structure=self.structure.analyze(candles); structure_v2=self.structure_v2.analyze(candles); liquidity=self.liquidity.analyze(candles); fvg=self.fvg.analyze(candles); order_block=self.order_block.analyze(candles); timeframe=self.timeframe.analyze(candles); kronos=self.kronos.analyze(indicators,structure,liquidity,fvg,order_block,structure_v2,timeframe)
        return self.context.build("NIFTY",indicators,kronos,structure,structure_v2,liquidity,fvg,order_block,timeframe)

    def _persist_envelope(self,candle,context,signal,state,reason,*,snapshot=None,aegis=None,argus=None,contract=None,risk=None,paper=None):
        try:
            self.evidence.decision_envelope(candle=candle,context=context,signal=signal,final_state=state,final_reason=reason,aegis_snapshot=snapshot,aegis_decision=aegis,argus=argus,contract=contract,risk=risk,paper_result=paper)
        except Exception:
            # Evidence is non-authoritative and must never alter the production path.
            return None

    @staticmethod
    def _position_contract(position,ltp):
        return ResolvedOptionContract(str(position.instrument_id),"NSE_FNO","NIFTY",str(position.option_type),float(position.strike),str(position.expiry),int(position.lot_size),float(ltp),None,None,None,None,"PAPER_STATE","DHAN_MARKETFEED_OHLC")

    def status(self):
        runtime=dict(self._runtime); runtime.update({"schema_version":1,"mode":"REAL_DATA_PAPER_ONLY","scheduler_running":bool(self._thread and self._thread.is_alive()),"frontend_execution":False,"broker_submission":False,"live_trading_enabled":False,"symbols":["NIFTY"],"maximum_lots":1,"maximum_open_positions":1,"maximum_trades_per_day":2,"strategy_registry":self.registry.projection()}); return runtime
    def timeline(self,limit=50): return {"status":"available","events":list(reversed(self._runtime.get("timeline",[])[-max(1,min(int(limit),100)):]))}
    def position(self):
        try:
            state=self.engine.paper_state.load(); position=state.open_positions[0].to_dict() if state.open_positions else None
            return {"status":"available","position":position,"source":"AUTHORITATIVE_PAPER_STATE"}
        except Exception: return {"status":"unavailable","position":None,"source":"AUTHORITATIVE_PAPER_STATE"}
    def pnl(self):
        try:
            state=self.engine.paper_state.load(); return {"status":"available","trading_date":state.trading_date,"realized_pnl":state.realized_pnl,"unrealized_pnl":state.unrealized_pnl,"total_daily_pnl":state.total_daily_pnl,"open_positions":len(state.open_positions),"trades_taken":state.trades_taken,"source":"AUTHORITATIVE_PAPER_STATE"}
        except Exception: return {"status":"unavailable","realized_pnl":None,"unrealized_pnl":None,"total_daily_pnl":None,"source":"AUTHORITATIVE_PAPER_STATE"}
    def readiness(self):
        status=self.status(); return {"status":"READY" if status.get("state") in {"WAITING","MONITORING","READY"} else "BLOCKED","mode":"REAL_DATA_PAPER_ONLY","closed_candles_only":True,"dhan_market_data":True,"broker_submission":False,"frontend_execution":False,"shadow_models":{"kronos_alpha":True,"chronos_2":True},"hard_limits":{"symbols":["NIFTY"],"maximum_lots":1,"maximum_open_positions":1,"maximum_trades_per_day":2,"overnight":False,"averaging":False,"pyramiding":False},"current_reason":status.get("reason")}
    def dashboard(self): return {"status":self.status(),"readiness":self.readiness(),"position":self.position(),"pnl":self.pnl(),"timeline":self.timeline(12),"generated_at":self.clock().isoformat()}

    def _set_state(self,state,reason,detail=None): self._runtime.update({"state":state,"reason":reason,"updated_at":self.clock().isoformat()}); self._record(state,reason,detail or ""); self._write_runtime(); return {"status":state,"reason":reason}
    def _record(self,status,code,detail):
        event={"timestamp":self.clock().isoformat(),"status":str(status),"code":str(code),"detail":str(detail)[:160]}; timeline=self._runtime.setdefault("timeline",[])
        if not timeline or timeline[-1].get("code")!=event["code"] or timeline[-1].get("detail")!=event["detail"]: timeline.append(event); del timeline[:-500]
    def _load_runtime(self):
        try:
            value=json.loads(self.state_path.read_text(encoding="utf-8"))
            if value.get("schema_version")!=1: raise ValueError("runtime schema invalid")
            return value
        except FileNotFoundError: return self._empty()
        except Exception:
            value=self._empty(); value.update({"state":"BLOCKED","reason":"RUNTIME_STATE_CORRUPT"}); return value
    def _write_runtime(self):
        self.state_path.parent.mkdir(parents=True,exist_ok=True); self._runtime["schema_version"]=1; fd,temp=tempfile.mkstemp(prefix=f".{self.state_path.name}.",dir=self.state_path.parent)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as handle: json.dump(self._runtime,handle,sort_keys=True,separators=(",",":")); handle.flush(); os.fsync(handle.fileno())
            os.replace(temp,self.state_path)
        finally:
            if os.path.exists(temp): os.unlink(temp)
    @staticmethod
    def _empty(): return {"schema_version":1,"state":"NOT_STARTED","reason":"AWAITING_LIFECYCLE_START","updated_at":None,"last_evaluated_candle":None,"last_signal":None,"last_aegis":None,"last_risk":None,"last_mark":None,"timeline":[]}
