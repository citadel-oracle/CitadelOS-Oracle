from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.execution.paper_state import PaperStateService
from src.order_ledger.service import OrderFillLedgerService
from src.order_ledger.storage import OrderFillStore
from src.paper_trading.contracts import ContractResolutionError, OptionContractResolver
from src.paper_trading.engine import PaperExecutionEngine
from src.paper_trading.fills import SimulatedFillModel
from src.paper_trading.models import PaperRiskDecision, ResolvedOptionContract
from src.paper_trading.orchestrator import RealMarketPaperOrchestrator
from src.paper_trading.registry import StrategyRegistry
from src.paper_trading.risk import PaperRiskAuthorization
from src.risk.authorization import RiskControlStore

pytestmark=[pytest.mark.unit,pytest.mark.safety]
IST=ZoneInfo("Asia/Kolkata"); NOW=datetime(2026,7,13,10,0,tzinfo=IST)


def contract(**changes):
    value=ResolvedOptionContract("999","NSE_FNO","NIFTY","CE",24200.0,"2026-07-16",25,10.0,10.1,100,9.9,100,"DHAN_INSTRUMENT_MASTER","DHAN_OPTION_CHAIN")
    return replace(value,**changes)


def settings(**changes):
    value={"live_trading_enabled":False,"max_daily_loss":1000,"max_trades_per_day":3,"max_consecutive_losses":2,"max_risk_per_trade":5000,"max_position_quantity":1,"max_open_positions":1,"max_market_data_age_seconds":10,"max_volatility":None}; value.update(changes); return value


def services(tmp_path):
    paper=PaperStateService(tmp_path/"paper.json",now_provider=lambda:NOW); paper.initialize()
    ledger=OrderFillLedgerService(OrderFillStore(tmp_path/"orders.json"),now_provider=lambda:NOW.isoformat())
    return paper,ledger


def risk_service(tmp_path, paper, **config):
    store=RiskControlStore(tmp_path/"risk.json"); store.initialize(False,"test inactive","test")
    return PaperRiskAuthorization(paper_state=paper,kill_store=store,settings_provider=lambda:settings(**config),clock=lambda:NOW)


def allowed_risk(): return PaperRiskDecision("ALLOW","PAPER_RISK_ALLOWED","ok","request-1",25,25,1,252.5,{"maximum_lots":1},NOW.isoformat())
def signal(): return {"signal":"BUY","confidence":80,"entry":24200.0,"sl":24180.0,"target":24240.0,"reason":"existing strategy","strategy":"Simple Pullback"}
def aegis(decision="APPROVE"):
    recommendation={"APPROVE":"NORMAL","APPROVE_REDUCED":"CAUTION","WAIT":"PAUSE","REJECT":"REJECT"}.get(decision,"PAUSE")
    return {"decision_id":"aegis-1","decision":decision,"recommendation":recommendation,"would_recommend":recommendation,"dominant_reasons":["TEST_ADVISORY"],"execution_permission":False,"execution_influence":"ZERO","calculation_timestamp":NOW.isoformat(),"input_snapshot_version":1,"input_fingerprint":"test"}


def test_registry_preserves_existing_strategy_and_caps_count():
    registry=StrategyRegistry(); projection=registry.projection()
    assert projection["active_count"]==1 and projection["maximum_strategies"]==2
    assert projection["strategies"][0]["name"]=="Simple Pullback" and projection["strategies"][0]["logic_modified"] is False
    with pytest.raises(ValueError): StrategyRegistry([object(),object(),object()])


class Master:
    def resolve(self,**kwargs): return {"security_id":str(kwargs["security_id"]),"lot_size":25,"source":"DHAN_INSTRUMENT_MASTER","exchange_segment":"NSE_FNO"}


def argus(side="ce", ask=10.1, ask_qty=25):
    leg={"security_id":999,"ltp":10.0,"top_ask_price":ask,"top_ask_quantity":ask_qty,"top_bid_price":9.9,"top_bid_quantity":25}
    return {"data":{"underlying":{"atm_strike":24200.0,"expiry":"2026-07-16","fetched_at":NOW.isoformat()},"atm_window":[{"strike":24200.0,"ce":leg,"pe":{**leg,"security_id":1000}}]}}


def test_contract_resolver_uses_argus_and_dynamic_master_lot():
    resolved=OptionContractResolver(Master()).resolve(argus(),"BUY")
    assert resolved.security_id=="999" and resolved.lot_size==25 and resolved.top_ask_price==10.1 and resolved.instrument_source=="DHAN_INSTRUMENT_MASTER"


def test_contract_resolver_fails_when_real_fields_absent():
    with pytest.raises(ContractResolutionError): OptionContractResolver(Master()).resolve({"data":{"underlying":{},"atm_window":[]}},"BUY")


@pytest.mark.parametrize("change,reason", [
    ({"live_trading_enabled":True},"PAPER_MODE_DISABLED"),
    ({"max_risk_per_trade":100},"PER_TRADE_RISK_EXCEEDED"),
])
def test_paper_risk_fails_closed(tmp_path,change,reason):
    paper,_=services(tmp_path); decision=risk_service(tmp_path,paper,**change).authorize(request_id="r",contract=contract(),market_timestamp=NOW,session_state="OPEN")
    assert decision.decision=="DENY" and decision.reason_code==reason and decision.broker_authorization is False


def test_paper_risk_allows_exactly_one_dynamic_lot_without_broker_permission(tmp_path):
    paper,_=services(tmp_path); decision=risk_service(tmp_path,paper).authorize(request_id="r",contract=contract(),market_timestamp=NOW,session_state="OPEN")
    assert decision.allowed and decision.quantity==decision.lot_size==25 and decision.number_of_lots==1 and decision.live_trading_enabled is False


def test_full_entry_fill_applies_once_to_paper_state_and_ledger(tmp_path):
    paper,ledger=services(tmp_path); engine=PaperExecutionEngine(ledger=ledger,paper_state=paper,fill_model=SimulatedFillModel(clock=lambda:NOW),clock=lambda:NOW)
    result=engine.enter(request_id="request-1",contract=contract(),strategy_signal=signal(),aegis_decision=aegis(),risk_decision=allowed_risk(),candle_timestamp=NOW.isoformat())
    assert result["status"]=="OPENED" and result["paper_state_applied"] is True
    state=paper.load(); assert len(state.open_positions)==1 and state.open_positions[0].raw_quantity==25 and state.open_positions[0].lot_size==25
    order=ledger.get_order(result["intent_id"]); assert order["state"]=="FILLED" and order["fill_application_applied"] is True
    assert order["intent"]["broker_submission_requested"] is False and order["intent"]["live_trading_enabled"] is False


def test_partial_fill_is_recorded_but_not_applied_to_paper_state(tmp_path):
    paper,ledger=services(tmp_path); engine=PaperExecutionEngine(ledger=ledger,paper_state=paper,fill_model=SimulatedFillModel(clock=lambda:NOW),clock=lambda:NOW)
    result=engine.enter(request_id="request-1",contract=contract(top_ask_quantity=10),strategy_signal=signal(),aegis_decision=aegis(),risk_decision=allowed_risk(),candle_timestamp=NOW.isoformat())
    assert result["status"]=="PARTIALLY_FILLED" and result["paper_state_applied"] is False and not paper.load().open_positions
    assert ledger.get_order(result["intent_id"])["state"]=="PARTIALLY_FILLED"


def test_partial_fill_continuation_completes_one_lot_and_applies_all_fills_once(tmp_path):
    paper,ledger=services(tmp_path); engine=PaperExecutionEngine(ledger=ledger,paper_state=paper,fill_model=SimulatedFillModel(clock=lambda:NOW),clock=lambda:NOW)
    first=engine.enter(request_id="request-1",contract=contract(top_ask_quantity=10),strategy_signal=signal(),aegis_decision=aegis(),risk_decision=allowed_risk(),candle_timestamp=NOW.isoformat())
    assert first["status"]=="PARTIALLY_FILLED"
    second=engine.continue_entry(contract(top_ask_quantity=25))
    assert second["status"]=="OPENED" and paper.load().open_positions[0].raw_quantity==25
    rebuilt=ledger.get_order(first["intent_id"]); assert rebuilt["filled_quantity"]==25 and rebuilt["fill_application_applied"] is True and len(rebuilt["fills"])==2


@pytest.mark.parametrize("decision", ["WAIT", "REJECT", "APPROVE_REDUCED", "UNAVAILABLE"])
def test_aegis_advisory_never_denies_or_mutates_valid_order(tmp_path, decision):
    paper,ledger=services(tmp_path); engine=PaperExecutionEngine(ledger=ledger,paper_state=paper,clock=lambda:NOW)
    result=engine.enter(request_id=f"r-{decision}",contract=contract(),strategy_signal=signal(),aegis_advisory=aegis(decision),risk_decision=allowed_risk(),candle_timestamp=NOW.isoformat())
    assert result["status"]=="OPENED"
    order=ledger.get_order(result["intent_id"])
    assert order["intent"]["requested_quantity"]==25 and order["intent"]["instrument_id"]=="999" and order["intent"]["side"]=="BUY"
    assert order["intent"]["metadata"]["aegis_advisory"]["execution_influence"]=="ZERO"
    assert order["intent"]["broker_submission_requested"] is False


def test_independent_paper_risk_denial_still_prevents_order(tmp_path):
    paper,ledger=services(tmp_path); engine=PaperExecutionEngine(ledger=ledger,paper_state=paper,clock=lambda:NOW)
    denied=replace(allowed_risk(),decision="DENY",reason_code="MARKET_DATA_STALE")
    result=engine.enter(request_id="stale",contract=contract(),strategy_signal=signal(),aegis_advisory=aegis("APPROVE"),risk_decision=denied,candle_timestamp=NOW.isoformat())
    assert result=={"status":"DENIED","reason":"MARKET_DATA_STALE"}
    assert ledger.status()["order_count"]==0


def test_mark_and_exit_use_real_quote_price_for_authoritative_pnl(tmp_path):
    paper,ledger=services(tmp_path); engine=PaperExecutionEngine(ledger=ledger,paper_state=paper,fill_model=SimulatedFillModel(clock=lambda:NOW),clock=lambda:NOW)
    opened=engine.enter(request_id="request-1",contract=contract(),strategy_signal=signal(),aegis_decision=aegis(),risk_decision=allowed_risk(),candle_timestamp=NOW.isoformat()); position=paper.load().open_positions[0]
    engine.mark(position=position,price=11.0,timestamp="mark-1"); assert paper.load().unrealized_pnl==22.5
    closed=engine.exit(position=paper.load().open_positions[0],contract=contract(ltp=12.0,top_bid_price=12.0),reason="UNDERLYING_TARGET_HIT",timestamp="close-1")
    assert closed["status"]=="CLOSED" and paper.load().realized_pnl==47.5 and not paper.load().open_positions


class ClosedCalendar:
    def status(self,at=None): return {"session_state":"WEEKEND"}
class NoCall:
    def __getattr__(self,name): raise AssertionError(f"unexpected call {name}")


def test_closed_market_tick_never_calls_provider_model_or_execution(tmp_path):
    paper,ledger=services(tmp_path); engine=PaperExecutionEngine(ledger=ledger,paper_state=paper,clock=lambda:NOW)
    orchestrator=RealMarketPaperOrchestrator(candle_source=NoCall(),calendar=ClosedCalendar(),argus=NoCall(),aegis=NoCall(),engine=engine,quote_client=NoCall(),state_path=tmp_path/"runtime.json",clock=lambda:NOW)
    assert orchestrator.tick()=={"status":"WAITING","reason":"MARKET_CLOSED"}
    assert ledger.status()["order_count"]==0 and orchestrator.readiness()["frontend_execution"] is False


def test_corrupt_runtime_fails_closed_without_provider_call(tmp_path):
    paper,ledger=services(tmp_path); runtime=tmp_path/"runtime.json"; runtime.write_text("{bad",encoding="utf-8")
    orchestrator=RealMarketPaperOrchestrator(candle_source=NoCall(),calendar=ClosedCalendar(),argus=NoCall(),aegis=NoCall(),engine=PaperExecutionEngine(ledger=ledger,paper_state=paper,clock=lambda:NOW),quote_client=NoCall(),state_path=runtime,clock=lambda:NOW)
    assert orchestrator.tick()=={"status":"BLOCKED","reason":"RUNTIME_STATE_CORRUPT"}


def test_frontend_contract_is_polling_only_with_no_execution_control():
    page=open("citadel-dashboard/src/app/page.tsx",encoding="utf-8").read(); css=open("citadel-dashboard/src/app/globals.css",encoding="utf-8").read()
    assert ("REAL MARKET PAPER TRADING" in page.upper() or "paperTrading" in page) and "feedSelectors.paperTrading" in page
    assert ("paper-trading-section" in css or "PaperTradingPanel" in page or "paperTrading" in page) and "submitPaperTrade" not in page and "executePaperTrade" not in page


def test_public_api_is_get_only_and_no_broker_submission_method_exists():
    from app.main import app
    routes=[route for route in app.routes if route.path.startswith("/v1/paper-trading")]
    assert len(routes)==7 and all(set(route.methods or ())=={"GET"} for route in routes)
    for name in ("submit_order","place_order","send_order","broker_order"):
        assert not hasattr(PaperExecutionEngine,name) and not hasattr(RealMarketPaperOrchestrator,name)
