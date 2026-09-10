from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.development import DevelopmentPaperExecutionEngine, DevelopmentRiskAuthorization, DevelopmentWeightedDecisionEngine, SimplePullbackDevelopment
from src.execution.paper_state import PaperStateService
from src.order_ledger.service import OrderFillLedgerService
from src.order_ledger.storage import OrderFillStore
from src.paper_trading.models import PaperRiskDecision, ResolvedOptionContract
from src.strategies.simple_pullback import SimplePullbackStrategy
from src.risk.authorization import RiskControlStore


pytestmark = [pytest.mark.unit, pytest.mark.safety]
IST = ZoneInfo("Asia/Kolkata"); NOW = datetime(2026, 7, 13, 10, 0, tzinfo=IST)


@dataclass
class Context:
    indicators: dict
    kronos: dict
    confidence: float = 80


def signal(): return {"signal": "BUY", "confidence": 80, "entry": 110, "sl": 100, "target": 130, "reason": "development", "strategy": "Simple Pullback (Development)", "profile_version": "DEVELOPMENT_V1"}
def safety(**changes):
    value = {"live_trading_enabled": False, "kill_switch_state": "INACTIVE", "session_state": "OPEN", "paper_state_health": "HEALTHY", "closed_candle": True, "market_data_fresh": True}; value.update(changes); return value
def evidence():
    return {"technical": {"available": True, "direction": "BULLISH", "confidence": 90}, "kronos_core": {"available": True, "direction": "BULLISH", "confidence": 90}, "argus": {"available": True, "direction": "BULLISH", "confidence": 90}, "kronos_alpha": {"available": True, "direction": "BULLISH", "confidence": 80}, "chronos_2": {"available": False}, "athena": {"available": False}, "oracle": {"available": False}, "hermes": {"available": False}}


def test_development_strategy_relaxes_only_ema_ordering_and_leaves_production_result_unchanged():
    context = Context({"close": 110, "ema_21": 100, "ema_38": 105}, {"bias": "BULLISH"})
    assert SimplePullbackStrategy().generate(context)["signal"] == "WAIT"
    result = SimplePullbackDevelopment().generate(context)
    assert result["signal"] == "BUY" and result["sl"] == 100 and result["target"] == 130
    assert SimplePullbackDevelopment().config()["production_strategy_modified"] is False


def test_weighted_decision_allows_alignment_without_all_optional_modules():
    decision = DevelopmentWeightedDecisionEngine(clock=lambda: NOW).assess(symbol="NIFTY", timeframe="5m", candle_timestamp=NOW.isoformat(), signal=signal(), evidence=evidence(), safety=safety())
    assert decision["decision"] == "ALLOW" and decision["weighted_score"] == 66.5
    assert set(decision["missing_optional_evidence"]) == {"chronos_2", "athena", "oracle", "hermes"}
    assert decision["production_aegis_used"] is False and decision["live_trading_enabled"] is False


def test_weighted_decision_preserves_true_safety_vetoes():
    decision = DevelopmentWeightedDecisionEngine(clock=lambda: NOW).assess(symbol="NIFTY", timeframe="5m", candle_timestamp=NOW.isoformat(), signal=signal(), evidence=evidence(), safety=safety(kill_switch_state="ACTIVE"))
    assert decision["decision"] == "BLOCK" and "KILL_SWITCH_ACTIVE" in decision["hard_vetoes"]


def test_development_execution_uses_only_isolated_state_and_ledger(tmp_path):
    development_state = PaperStateService(tmp_path / "development-paper.json", now_provider=lambda: NOW); development_state.initialize()
    production_state = PaperStateService(tmp_path / "production-paper.json", now_provider=lambda: NOW); production_state.initialize()
    ledger = OrderFillLedgerService(OrderFillStore(tmp_path / "development-orders.json"), now_provider=lambda: NOW.isoformat())
    engine = DevelopmentPaperExecutionEngine(ledger=ledger, paper_state=development_state, clock=lambda: NOW)
    contract = ResolvedOptionContract("999", "NSE_FNO", "NIFTY", "CE", 24200, "2026-07-16", 25, 10, 10.1, 25, 9.9, 25, "DHAN_INSTRUMENT_MASTER", "DHAN_OPTION_CHAIN")
    risk = PaperRiskDecision("ALLOW", "DEVELOPMENT_RISK_ALLOWED", "ok", "dev-request", 25, 25, 1, 252.5, {}, NOW.isoformat())
    decision = DevelopmentWeightedDecisionEngine(clock=lambda: NOW).assess(symbol="NIFTY", timeframe="5m", candle_timestamp=NOW.isoformat(), signal=signal(), evidence=evidence(), safety=safety())
    result = engine.enter(request_id="dev-request", contract=contract, strategy_signal=signal(), weighted_decision=decision, risk_decision=risk, candle_timestamp=NOW.isoformat(), replay_id="replay-1")
    assert result["status"] == "OPENED" and len(development_state.load().open_positions) == 1
    assert not production_state.load().open_positions
    intent = ledger.get_order(result["intent_id"])["intent"]
    assert intent["metadata"]["development_only"] is True and intent["broker_submission_requested"] is False


def test_development_engine_has_no_broker_submission_surface():
    for name in ("submit_order", "place_order", "send_order", "broker_order"):
        assert not hasattr(DevelopmentPaperExecutionEngine, name)


def test_development_risk_keeps_live_and_kill_switch_vetoes(tmp_path):
    state = PaperStateService(tmp_path / "development-paper.json", now_provider=lambda: NOW); state.initialize()
    kill = RiskControlStore(tmp_path / "risk.json"); kill.initialize(False, "test inactive", "test")
    config = {"live_trading_enabled": False, "max_daily_loss": 1000, "max_trades_per_day": 2, "max_consecutive_losses": 2, "max_risk_per_trade": 5000, "max_position_quantity": 1, "max_open_positions": 1, "max_market_data_age_seconds": 10, "max_volatility": None}
    risk = DevelopmentRiskAuthorization(paper_state=state, kill_store=kill, settings_provider=lambda: config, clock=lambda: NOW)
    contract = ResolvedOptionContract("999", "NSE_FNO", "NIFTY", "CE", 24200, "2026-07-16", 25, 10, 10.1, 25, 9.9, 25, "DHAN_INSTRUMENT_MASTER", "DHAN_OPTION_CHAIN")
    allowed = risk.authorize(request_id="dev-risk", contract=contract, market_timestamp=NOW, session_state="OPEN")
    assert allowed.allowed and allowed.limits["maximum_development_trades_per_day"] == 20
    unsafe = DevelopmentRiskAuthorization(paper_state=state, kill_store=kill, settings_provider=lambda: {**config, "live_trading_enabled": True}, clock=lambda: NOW).authorize(request_id="unsafe", contract=contract, market_timestamp=NOW, session_state="OPEN")
    assert unsafe.decision == "DENY" and unsafe.reason_code == "LIVE_TRADING_ENABLED"


def test_development_routes_are_get_only_and_v2_has_isolated_feed():
    from app.main import app, v2_integration
    routes = [route for route in app.routes if route.path == "/v1/development/dashboard"]
    assert len(routes) == 1 and set(routes[0].methods or ()) == {"GET"}
    assert "development" in v2_integration.providers
