"""Fail-closed paper risk authorization; never authorizes broker transport."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from src.execution.paper_state import PaperStateService
from src.risk.authorization import RiskControlStore, RiskLimits

from .models import PaperRiskDecision

IST=ZoneInfo("Asia/Kolkata")


class PaperRiskAuthorization:
    def __init__(self, paper_state=None, kill_store=None, settings_provider=None, clock=None):
        self.paper_state=paper_state or PaperStateService(); self.kill_store=kill_store or RiskControlStore(); self.settings_provider=settings_provider or self._settings; self.clock=clock or (lambda:datetime.now(IST))

    def authorize(self, *, request_id, contract, market_timestamp, session_state):
        now=self.clock(); quantity=int(contract.lot_size); maximum_loss=round(float(contract.top_ask_price or contract.ltp)*quantity,2)
        limits={"maximum_lots":1,"maximum_open_positions":1,"maximum_completed_trades_per_day":2,"nifty_options_only":True,"no_averaging":True,"no_pyramiding":True,"no_overnight":True}
        def deny(code,reason): return PaperRiskDecision("DENY",code,reason,request_id,quantity,int(contract.lot_size),1,maximum_loss,limits,now.isoformat())
        try:
            configured=RiskLimits.from_mapping(self.settings_provider())
            if configured.live_trading_enabled: return deny("PAPER_MODE_DISABLED","live trading must remain disabled")
            kill=self.kill_store.projection()
            if kill.state!="INACTIVE": return deny(f"KILL_SWITCH_{kill.state}","kill switch is not safely inactive")
            if session_state not in {"OPEN","SPECIAL_SESSION"}: return deny("MARKET_CLOSED","market session is not open")
            if contract.underlying!="NIFTY" or contract.option_type not in {"CE","PE"}: return deny("UNSUPPORTED_INSTRUMENT","only NIFTY options are allowed")
            if quantity<=0: return deny("INVALID_LOT_SIZE","dynamic lot size is invalid")
            age=(now-market_timestamp.astimezone(IST)).total_seconds()
            if age<0 or age>configured.max_market_data_age_seconds: return deny("STALE_MARKET_DATA","option quote is stale")
            state=self.paper_state.risk_snapshot(now.date())
            if state.open_positions>=1: return deny("MAX_OPEN_POSITIONS_REACHED","one paper position is already open")
            if state.trades_taken>=2: return deny("MAX_TRADES_REACHED","two completed/entered paper trades have been reached")
            if state.total_daily_pnl<=-configured.max_daily_loss: return deny("DAILY_LOSS_LIMIT_REACHED","maximum daily loss reached")
            if state.consecutive_losses>=configured.max_consecutive_losses: return deny("MAX_CONSECUTIVE_LOSSES_REACHED","maximum consecutive losses reached")
            if request_id in state.accepted_request_ids: return deny("DUPLICATE_REQUEST","request already applied")
            if maximum_loss>configured.max_risk_per_trade: return deny("PER_TRADE_RISK_EXCEEDED","one-lot premium-at-risk exceeds configured per-trade risk")
            return PaperRiskDecision("ALLOW","PAPER_RISK_ALLOWED","All paper-only risk gates passed",request_id,quantity,int(contract.lot_size),1,maximum_loss,{**limits,"max_daily_loss":configured.max_daily_loss,"max_risk_per_trade":configured.max_risk_per_trade},now.isoformat())
        except Exception: return deny("RISK_STATE_UNAVAILABLE","paper risk authorization failed closed")

    @staticmethod
    def _settings():
        with open("config/settings.json",encoding="utf-8") as handle: return json.load(handle)
