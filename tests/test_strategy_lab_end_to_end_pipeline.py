import json
import threading

import pytest

from src.paper_trading.contracts import ContractResolutionError, OptionContractResolver
from src.strategy_lab import DeploymentRequest, StrategyInputType, StrategyLabService, StrategyMetadata


class InstrumentMaster:
    def resolve(self, **values):
        return {
            "security_id": str(values["security_id"]),
            "lot_size": 15 if values.get("underlying") == "BANKNIFTY" else 25,
            "source": "DHAN_INSTRUMENT_MASTER",
            "exchange_segment": "NSE_FNO",
        }


def argus(underlying="BANKNIFTY"):
    rows = []
    for strike, security in ((57000, 100), (57100, 200), (57200, 300)):
        rows.append({
            "strike": strike,
            "ce": {"security_id": security, "ltp": 100 + (strike - 57000) / 100,
                   "top_ask_price": 101, "top_ask_quantity": 100,
                   "top_bid_price": 99, "top_bid_quantity": 100},
            "pe": {"security_id": security + 1_000, "ltp": 90,
                   "top_ask_price": 91, "top_ask_quantity": 100,
                   "top_bid_price": 89, "top_bid_quantity": 100},
        })
    return {"data": {"underlying": {"symbol": underlying, "atm_strike": 57100, "expiry": "2026-07-16"}, "atm_window": rows}}


class PipelineStrategy:
    def evaluate(self, context):
        return {
            "evaluation_id": context["evaluation_id"],
            "signal": context.get("signal", "WAIT"),
            "position_effect": context.get("position_effect"),
            "side": "LONG",
            "underlying_stop": context.get("underlying_stop", 57000),
            "underlying_target": context.get("underlying_target", 57400),
            "exit_reason": context.get("exit_reason"),
            "reason": context.get("exit_reason") or context.get("signal", "WAIT"),
        }


class StatefulEntryStrategy:
    def __init__(self, count=0):
        self.count = count

    def evaluate(self, context):
        self.count += 1
        return {
            "evaluation_id": f"stateful-{self.count}",
            "signal": "BUY" if self.count == 1 else "WAIT",
            "position_effect": "OPEN" if self.count == 1 else None,
            "side": "LONG", "contract": "STATEFUL-OPTION",
            "entry": 100.0 if self.count == 1 else None,
            "stop": 95.0, "target": 110.0,
        }

    def serialize(self):
        return json.dumps({"count": self.count}, sort_keys=True)

    @classmethod
    def deserialize(cls, payload):
        return cls(json.loads(payload)["count"])


class BlockingStrategy:
    def __init__(self, entered, release):
        self.entered, self.release = entered, release

    def evaluate(self, context):
        self.entered.set()
        self.release.wait(timeout=2)
        return {
            "evaluation_id": context["evaluation_id"],
            "signal": "WAIT",
            "position_state": {},  # Bypass compact_wait optimization in tests
        }


def metadata(strategy_id, *, dynamic_lot=True):
    return StrategyMetadata(
        strategy_id=strategy_id, name=strategy_id, version="1", author="Test",
        input_type=StrategyInputType.PYTHON,
        supported_markets=["NIFTY", "BANKNIFTY"], supported_timeframes=["3m"],
        rr=4, risk_model="STRATEGY_LAB_PAPER_RISK",
        deployment_date="2026-07-14T00:00:00+00:00",
        parameters={
            "option_selection": {"underlying": "BANKNIFTY", "option_type": "CE", "strike_offset": 1},
            "paper_account": {
                "initial_capital": 100_000, "sizing_mode": "FIXED_LOTS",
                "fixed_lots": 1, "lot_size": None if dynamic_lot else 1,
                "max_daily_loss": 3_000, "max_concurrent_positions": 1,
                "max_trades_per_day": 20, "margin_rate": 1.0,
            },
        },
    )


def request(strategy_id, adapter=None, *, dynamic_lot=True):
    return DeploymentRequest(
        metadata=metadata(strategy_id, dynamic_lot=dynamic_lot),
        adapter=adapter or PipelineStrategy(), context_provider=lambda: {},
        option_resolver=OptionContractResolver(InstrumentMaster()),
        scheduler_interval_seconds=60,
    )


def candle(candle_id, evaluation_id, signal="WAIT", **values):
    return {
        "candle_id": candle_id, "evaluation_id": evaluation_id, "signal": signal,
        "symbol": "BANKNIFTY", "timeframe": "3m", "confirmed": True,
        "timestamp": values.pop("timestamp", "2026-07-14T09:18:00+05:30"),
        "argus": argus(), **values,
    }


@pytest.mark.unit
def test_option_resolution_supports_banknifty_offset_ce_pe_and_fails_closed():
    resolver = OptionContractResolver(InstrumentMaster())
    ce = resolver.resolve(argus(), "BUY", underlying="BANKNIFTY", option_type="CE", strike_offset=1)
    pe = resolver.resolve(argus(), "BUY", underlying="BANKNIFTY", option_type="PE", strike_offset=-1)
    assert (ce.security_id, ce.strike, ce.option_type, ce.lot_size) == ("300", 57200.0, "CE", 15)
    assert (pe.security_id, pe.strike, pe.option_type, pe.lot_size) == ("1100", 57000.0, "PE", 15)
    with pytest.raises(ContractResolutionError):
        resolver.resolve(argus(), "BUY", underlying="BANKNIFTY", strike_offset=9)


@pytest.mark.integration
def test_end_to_end_option_signal_oms_portfolio_dashboard_and_review_streams(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    runtime = service.deploy(request("pipeline"))
    first = runtime.tick_once(candle("bank-1", "entry-1", "BUY"))
    assert first["decision"]["paper_execution"]["status"] == "FILLED"
    state = runtime.execution.projection()
    assert state["positions"][0]["contract"] == "300"
    assert state["positions"][0]["quantity"] == 15
    assert state["lifecycle"]["state"] == "MANAGING"

    stream_counts = {name: len(getattr(runtime.workspace, name).read()) for name in ("journal", "replay", "evidence", "order_ledger", "fill_ledger")}
    duplicate = runtime.tick_once(candle("bank-1", "entry-duplicate", "BUY"))
    assert duplicate["reason"] == "CANDLE_ALREADY_PROCESSED"
    second_buy = runtime.tick_once(candle("bank-2", "entry-2", "BUY", timestamp="2026-07-14T09:21:00+05:30"))
    assert second_buy["reason"] == "ACTIVE_POSITION_SUPPRESSED"
    assert {name: len(getattr(runtime.workspace, name).read()) for name in stream_counts} == stream_counts

    closed = runtime.tick_once(candle(
        "bank-3", "target-1", "SELL", position_effect="CLOSE", exit_reason="TARGET",
        timestamp="2026-07-14T09:24:00+05:30",
    ))
    assert closed["decision"]["paper_execution"]["status"] == "FILLED"
    state = runtime.execution.projection()
    assert state["lifecycle"]["state"] == "IDLE"
    assert len(state["closed_trades"]) == 1
    transitions = [row["to"] for row in state["lifecycle"]["transitions"]]
    assert transitions == ["SIGNAL_PENDING", "ENTRY_CONFIRMED", "POSITION_OPEN", "MANAGING", "TARGET", "POSITION_CLOSED", "IDLE"]

    dashboard = service.dashboard()
    assert dashboard["portfolio"]["closed_trades"] == 1
    assert dashboard["execution"]["closed_trade_count"] == 1
    assert dashboard["execution"]["order_count"] == 2
    assert dashboard["execution"]["fill_count"] == 2
    assert dashboard["review"]["journal"]
    assert dashboard["review"]["replay"] == []
    assert dashboard["review"]["evidence"] == []
    for name in ("journal", "replay", "evidence", "order_ledger", "fill_ledger"):
        ids = [row["record_id"] for row in getattr(runtime.workspace, name).read()]
        assert len(ids) == len(set(ids))


@pytest.mark.integration
def test_restart_restores_adapter_candle_and_open_position_state(tmp_path):
    root = str(tmp_path / "lab")
    first_service = StrategyLabService(root)
    first = first_service.deploy(request("restart-pipeline", StatefulEntryStrategy(), dynamic_lot=False))
    first.tick_once(candle("state-1", "ignored", "BUY"))
    assert first.execution.projection()["lifecycle"]["state"] == "MANAGING"
    assert first.strategy.count == 1

    restarted_service = StrategyLabService(root)
    restarted = restarted_service.deploy(request("restart-pipeline", StatefulEntryStrategy(), dynamic_lot=False))
    assert restarted.strategy.count == 1
    assert restarted.execution.projection()["positions"][0]["status"] == "OPEN"
    duplicate = restarted.tick_once(candle("state-1", "ignored-again", "BUY"))
    assert duplicate["reason"] == "CANDLE_ALREADY_PROCESSED"
    restarted.tick_once(candle("state-2", "ignored-2", "WAIT", timestamp="2026-07-14T09:21:00+05:30"))
    assert restarted.strategy.count == 2
    assert len(restarted.execution.projection()["orders"]) == 1


@pytest.mark.parametrize("reason,terminal", [("STOP", "STOP"), ("SESSION_EXIT", "SESSION_EXIT")])
@pytest.mark.integration
def test_stop_and_session_exit_use_valid_state_machine(reason, terminal, tmp_path):
    service = StrategyLabService(str(tmp_path / reason))
    runtime = service.deploy(request(f"exit-{reason.lower()}", dynamic_lot=False))
    runtime.tick_once({
        **candle("entry", "entry", "BUY"), "contract": "DIRECT",
        "entry": 100.0,
    })
    runtime.tick_once({
        **candle("exit", "exit", "SELL", timestamp="2026-07-14T09:21:00+05:30"),
        "contract": "DIRECT", "exit": 90.0, "execution_price": 90.0,
        "exit_reason": reason,
    })
    transitions = [row["to"] for row in runtime.execution.projection()["lifecycle"]["transitions"]]
    assert terminal in transitions
    assert transitions[-2:] == ["POSITION_CLOSED", "IDLE"]


@pytest.mark.integration
def test_manual_close_and_strategy_cancel_are_idempotent(tmp_path):
    service = StrategyLabService(str(tmp_path / "manual"))
    runtime = service.deploy(request("manual-close", dynamic_lot=False))
    runtime.tick_once({**candle("entry", "entry", "BUY"), "contract": "DIRECT", "entry": 100.0})
    first = runtime.execution.close_open_position(price=105.0, reason="MANUAL_PAPER_CLOSE", evaluation_id="manual-1")
    second = runtime.execution.close_open_position(price=105.0, reason="MANUAL_PAPER_CLOSE", evaluation_id="manual-1")
    assert first["status"] == "FILLED"
    assert second["reason"] == "DUPLICATE_EXIT_SUPPRESSED"
    assert len(runtime.execution.projection()["closed_trades"]) == 1

    cancel_runtime = service.deploy(request("strategy-cancel", dynamic_lot=False))
    cancel_runtime.tick_once({**candle("cancel-entry", "cancel-entry", "BUY"), "contract": "DIRECT", "entry": 100.0})
    cancelled = cancel_runtime.execution.cancel_strategy(price=101.0)
    assert cancelled["status"] == "FILLED"
    assert cancel_runtime.execution.projection()["lifecycle"]["state"] == "IDLE"


@pytest.mark.integration
def test_scheduler_overlap_is_skipped_without_duplicate_side_effects(tmp_path):
    entered, release = threading.Event(), threading.Event()
    service = StrategyLabService(str(tmp_path / "overlap"))
    runtime = service.deploy(request("overlap", BlockingStrategy(entered, release), dynamic_lot=False))
    result = {}

    def run():
        result.update(runtime.tick_once(candle("overlap-1", "overlap-1")))

    worker = threading.Thread(target=run)
    worker.start()
    assert entered.wait(timeout=1)
    skipped = runtime.tick_once(candle("overlap-1", "overlap-1"))
    release.set()
    worker.join(timeout=2)
    assert skipped == {"status": "SKIPPED", "reason": "TICK_ALREADY_RUNNING"}
    assert result["status"] == "EVALUATED"
    assert runtime.status()["scheduler"]["skipped_count"] == 1
    assert len(runtime.workspace.evidence.read()) == 1
