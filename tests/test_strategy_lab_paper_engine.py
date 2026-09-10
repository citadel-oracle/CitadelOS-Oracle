from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from app.main import app
from src.oracle_personal.ledger import PersonalOracleLedger
from src.oracle_personal.service import PersonalOracleService
from src.strategy_lab import (
    DeploymentRequest,
    ExecutionProvider,
    PaperExecutionProvider,
    StrategyInputType,
    StrategyLabService,
    StrategyMetadata,
)
from src.strategy_lab.events import DomainEvent, InternalEventBus
from src.strategy_lab.paper_engine import aggregate_portfolio


class ContextStrategy:
    def evaluate(self, context):
        signal = str(context.get("signal") or "WAIT").upper()
        result = {
            "evaluation_id": context["evaluation_id"],
            "signal": signal,
            "reason": context.get("reason") or f"TEST_{signal}",
            "contract": context.get("contract", "NIFTY-TEST"),
            "position_id": context.get("position_id"),
            "option_contract": context.get("option_contract"),
            "side": context.get("side", "LONG"),
            "position_effect": context.get("position_effect"),
            "entry": context.get("entry"),
            "exit": context.get("exit"),
            "stop": context.get("stop"),
            "target": context.get("target"),
            "initial_stop": context.get("initial_stop"),
            "current_stop": context.get("current_stop"),
            "underlying_stop": context.get("underlying_stop"),
            "underlying_initial_stop": context.get("underlying_initial_stop"),
            "underlying_current_stop": context.get("underlying_current_stop"),
            "trailing_enabled": context.get("trailing_enabled"),
            "trailing_activation_price": context.get("trailing_activation_price"),
            "trailing_anchor": context.get("trailing_anchor"),
            "trailing_distance": context.get("trailing_distance"),
            "trailing_step": context.get("trailing_step"),
            "risk_position_id": context.get("risk_position_id"),
            "risk_contract": context.get("risk_contract"),
            "risk_source": context.get("risk_source"),
            "risk_source_timestamp": context.get("risk_source_timestamp"),
            "risk_rule_version": context.get("risk_rule_version"),
            "position_state": context.get("position_state"),
            "order_type": context.get("order_type", "MARKET"),
            "limit_price": context.get("limit_price"),
            "stop_price": context.get("stop_price"),
            "available_quantity": context.get("available_quantity"),
            "expires_at": context.get("expires_at"),
        }
        return result


class GapExitStrategy:
    def evaluate(self, context):
        bar = context.get("bar") or {}
        signal = str(context.get("signal") or "WAIT").upper()
        if signal != "BUY" and float(bar.get("low") or 999999) < 95.0:
            signal = "SELL"
        return {
            "evaluation_id": str(context.get("evaluation_id") or f"gap:{bar.get('timestamp')}"),
            "signal": signal,
            "reason": "STOP_LOSS_REACHED" if signal == "SELL" else f"TEST_{signal}",
            "exit_reason": "STOP" if signal == "SELL" else None,
            "contract": "57351", "side": "LONG",
            "position_effect": "OPEN" if signal == "BUY" else "CLOSE" if signal == "SELL" else None,
            "entry": context.get("entry"), "exit": context.get("current_price"),
            "stop": 95.0, "target": 110.0,
        }


def paper_parameters(
    *,
    initial_capital: float = 50_000.0,
    sizing_mode: str = "FIXED_LOTS",
    fixed_lots: Optional[int] = 1,
    lot_size: int = 50,
    fixed_rupee_risk: Optional[float] = None,
    fixed_risk_percent: Optional[float] = None,
):
    return {
        "paper_account": {
            "initial_capital": initial_capital,
            "sizing_mode": sizing_mode,
            "fixed_lots": fixed_lots,
            "lot_size": lot_size,
            "fixed_rupee_risk": fixed_rupee_risk,
            "fixed_risk_percent": fixed_risk_percent,
            "max_daily_loss": 5_000.0,
            "max_concurrent_positions": 2,
            "max_trades_per_day": 5,
            "margin_rate": 1.0,
            "fee_rate_bps": 1.0,
            "flat_fee_per_fill": 2.0,
            "slippage_bps": 5.0,
        }
    }


def metadata(strategy_id: str, *, parameters=None):
    return StrategyMetadata(
        strategy_id=strategy_id,
        name=strategy_id,
        version="1.0.0",
        author="Test",
        input_type=StrategyInputType.PYTHON,
        supported_markets=["NIFTY"],
        supported_timeframes=["5m"],
        rr=2.0,
        risk_model="STRATEGY_LAB_PAPER_RISK",
        deployment_date="2026-07-14T00:00:00+00:00",
        parameters=parameters or {},
    )


def request(strategy_id: str, *, parameters=None):
    return DeploymentRequest(
        metadata=metadata(strategy_id, parameters=parameters),
        adapter=ContextStrategy(),
        context_provider=lambda: {"evaluation_id": "idle", "signal": "WAIT"},
        scheduler_interval_seconds=60,
    )


def tick(runtime, **values):
    context = {
        "timestamp": values.pop("timestamp", "2026-07-14T09:20:00+05:30"),
        **values,
    }
    return runtime.tick_once(context_override=context)["decision"]


@pytest.mark.unit
def test_only_paper_execution_provider_exists_and_has_no_broker_surface():
    provider: ExecutionProvider = PaperExecutionProvider()
    assert provider.provider_name == "CITADEL_STRATEGY_LAB_PAPER"
    assert provider.paper_only is True
    assert provider.broker_submission is False
    assert not hasattr(provider, "place_order")
    assert not hasattr(provider, "submit_broker_order")


@pytest.mark.unit
def test_internal_event_bus_is_publish_subscribe_and_event_ids_are_idempotent():
    received = []
    bus = InternalEventBus()
    bus.subscribe("SignalCreated", received.append)
    first = DomainEvent("SignalCreated", "sig_1", None, ["sig_1"], {"signal": "BUY"})
    second = DomainEvent("SignalCreated", "sig_1", None, ["sig_1"], {"signal": "BUY"})
    bus.publish(first)
    assert received == [first]
    assert first.event_id == second.event_id


@pytest.mark.integration
def test_full_signal_order_fill_position_close_lifecycle_and_statistics(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    runtime = service.deploy(request("pullback", parameters=paper_parameters()))

    entry = tick(
        runtime,
        evaluation_id="entry-1",
        signal="BUY",
        contract="NIFTY-TEST",
        entry=100.0,
        stop=95.0,
        target=110.0,
        close=100.0,
    )
    assert entry["paper_execution"]["status"] == "FILLED"
    state = runtime.execution.projection()
    assert state["positions"][0]["status"] == "OPEN"
    assert state["positions"][0]["quantity"] == 50
    assert state["account"]["initial_capital"] == 50_000.0
    assert state["account"]["margin_used"] > 0

    tick(runtime, evaluation_id="mark-1", signal="WAIT", contract="NIFTY-TEST", close=108.0, timestamp="2026-07-14T09:25:00+05:30")
    marked = runtime.execution.projection()["positions"][0]
    assert marked["current_price"] == 108.0
    assert marked["mfe"] > 0

    exit_decision = tick(
        runtime,
        evaluation_id="exit-1",
        signal="SELL",
        position_effect="CLOSE",
        contract="NIFTY-TEST",
        exit=110.0,
        close=110.0,
        timestamp="2026-07-14T09:30:00+05:30",
    )
    assert exit_decision["paper_execution"]["status"] == "FILLED"
    state = runtime.execution.projection()
    assert state["positions"][0]["status"] == "CLOSED"
    assert len(state["closed_trades"]) == 1
    assert state["statistics"]["completed_trades"] == 1
    assert state["statistics"]["net_profit"] == state["closed_trades"][0]["realized_pnl"]
    assert state["account"]["realized_pnl"] == state["closed_trades"][0]["realized_pnl"]


@pytest.mark.integration
def test_entry_context_is_immutable_and_follows_trade_outcome(tmp_path):
    lab_root = tmp_path / "lab"
    service = StrategyLabService(str(lab_root))
    runtime = service.deploy(request("oracle-context", parameters=paper_parameters(lot_size=65)))
    oracle = PersonalOracleService(
        ledger=PersonalOracleLedger(tmp_path / "oracle.json"),
        strategy_lab_root=lab_root,
    )
    pre_entry_states = []

    def observe_oracle(event):
        if event.event_type == "TradeCandidateFormed":
            state = runtime.execution.projection()
            pre_entry_states.append((len(state["orders"]), len(state["fills"]), len(state["positions"])))
            oracle.capture_shadow_advisory(event.payload["candidate"], source_event_id=event.event_id)
        elif event.event_type == "TradeCompleted":
            oracle.ingest_strategy_lab_trade(event.payload["trade"], source_event_id=event.event_id)

    service.subscribe_events(observe_oracle)
    option = {
        "security_id": "63942", "underlying": "NIFTY", "option_type": "PE",
        "strike": 24050.0, "expiry": "2026-07-28", "instrument_source": "DHAN_INSTRUMENT_MASTER",
        "quote_source": "DHAN_OPTION_CHAIN",
    }
    tick(
        runtime, evaluation_id="oracle-entry", signal="BUY", contract="63942",
        option_contract=option, entry=150.0, stop=None, target=None, close=150.0,
        reason="PULLBACK_CONFIRMED", timeframe="1m", reference_price=24010.0,
        market_regime="TRENDING", setup_tag="PULLBACK",
    )
    opened = runtime.execution.projection()["positions"][0]
    assert pre_entry_states == [(0, 0, 0)]
    assert len(oracle.ledger.advisories()) == 1
    advisory_before = oracle.ledger.advisories()[0].to_dict()
    context = deepcopy(opened["oracle_entry_context"])
    assert context["source_trade_id"] == opened["trade_id"]
    assert context["candidate_signal_id"]
    assert context["option_side"] == "PE" and context["strike"] == 24050.0
    assert context["reference_price"] == 24010.0
    assert context["stop_loss"] is None and context["target"] is None
    assert set(("stop_loss", "target")) <= set(context["missing_context_fields"])

    tick(runtime, evaluation_id="oracle-mark", signal="WAIT", contract="63942", close=155.0, market_regime="RANGING")
    assert runtime.execution.projection()["positions"][0]["oracle_entry_context"] == context
    tick(
        runtime, evaluation_id="oracle-exit", signal="SELL", position_effect="CLOSE",
        contract="63942", exit=155.0, close=155.0,
        timestamp="2026-07-14T09:30:00+05:30",
    )
    closed = runtime.execution.projection()["closed_trades"][0]
    assert closed["oracle_entry_context"] == context
    assert len(oracle.ledger.events()) == 1
    assert len(oracle.ledger.outcomes()) == 1
    assert oracle.ledger.advisories()[0].to_dict() == advisory_before
    event = oracle.ledger.events()[0]
    assert event.source_record_id == closed["trade_id"]
    assert event.ingestion_mode == "EVENT_DRIVEN"


@pytest.mark.integration
def test_shadow_failure_is_fail_open_and_execution_output_is_identical(tmp_path):
    baseline_service = StrategyLabService(str(tmp_path / "baseline"))
    baseline = baseline_service.deploy(request("fail-open", parameters=paper_parameters()))
    failed_service = StrategyLabService(str(tmp_path / "failed"))
    failed = failed_service.deploy(request("fail-open", parameters=paper_parameters()))

    def fail_shadow(event):
        if event.event_type == "TradeCandidateFormed":
            raise RuntimeError("ORACLE_UNAVAILABLE")

    failed_service.subscribe_events(fail_shadow)
    values = dict(
        evaluation_id="same-candidate", signal="BUY", contract="NIFTY-TEST",
        entry=100.0, stop=95.0, target=110.0, close=100.0,
    )
    baseline_result = tick(baseline, **values)["paper_execution"]
    failed_result = tick(failed, **values)["paper_execution"]
    assert {key: baseline_result.get(key) for key in ("status", "reason", "order_status")} == {
        key: failed_result.get(key) for key in ("status", "reason", "order_status")
    }
    for runtime in (baseline, failed):
        state = runtime.execution.projection()
        assert len(state["orders"]) == len(state["fills"]) == len(state["positions"]) == 1
        assert state["paper_only"] is True and state["broker_submission"] is False


@pytest.mark.integration
def test_open_position_marks_from_authoritative_argus_contract_quote(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    runtime = service.deploy(request("argus-mark", parameters=paper_parameters()))
    tick(runtime, evaluation_id="entry", signal="BUY", contract="57344", entry=100.0, stop=95.0, target=110.0, close=100.0)

    tick(
        runtime,
        evaluation_id="mark",
        signal="WAIT",
        symbol="NIFTY",
        argus={"data": {"atm_window": [{"ce": {"security_id": 57344, "ltp": 108.5}}]}},
        timestamp="2026-07-14T09:25:00+05:30",
    )

    marked = runtime.execution.projection()["positions"][0]
    assert marked["current_price"] == 108.5
    assert marked["pnl"] > 0
    assert marked["rr"] > 0
    assert marked["duration_seconds"] >= 0


@pytest.mark.integration
def test_fill_price_is_not_published_as_live_quote_and_exact_argus_quote_marks_mtm(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    parameters = paper_parameters(lot_size=65)
    parameters["paper_account"]["slippage_bps"] = 0.0
    runtime = service.deploy(request("held-quote", parameters=parameters))
    tick(runtime, evaluation_id="entry", signal="BUY", contract="57351", entry=150.75, stop=146.4, target=261.9, close=150.75)
    opened = runtime.execution.projection()["positions"][0]
    assert opened["current_price"] is None
    assert opened["pnl"] is None
    assert opened["pnl_valid"] is False
    assert opened["pnl_status"] == "MTM_UNAVAILABLE"
    assert opened["quote_status"] == "UNAVAILABLE"

    quote_time = datetime.now(timezone.utc).isoformat()
    tick(
        runtime,
        evaluation_id="mark", signal="WAIT", contract="57351", current_price=150.75,
        argus={"data": {"underlying": {"fetched_at": quote_time}, "atm_window": [
            {"pe": {"security_id": "57351", "ltp": 138.65, "fetched_at": quote_time}}
        ]}},
        timestamp="2026-07-14T09:25:00+05:30",
    )
    marked = runtime.execution.projection()["positions"][0]
    assert marked["current_price"] == 138.65
    assert marked["pnl"] == pytest.approx(-786.50)
    assert marked["quote_source"] == "ARGUS_DHAN_OPTION_CHAIN"
    assert marked["quote_security_id"] == "57351"
    assert marked["quote_status"] == "FRESH"


@pytest.mark.integration
def test_stale_held_contract_quote_is_never_marked_fresh(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    runtime = service.deploy(request("stale-held-quote", parameters=paper_parameters(lot_size=65)))
    tick(runtime, evaluation_id="entry", signal="BUY", contract="57351", entry=150.75, stop=146.4, target=261.9, close=150.75)
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    tick(
        runtime,
        evaluation_id="mark", signal="WAIT", contract="57351",
        argus={"data": {"underlying": {"fetched_at": stale_time}, "atm_window": [
            {"pe": {"security_id": "57351", "ltp": 138.65, "fetched_at": stale_time}}
        ]}},
        timestamp="2026-07-14T09:25:00+05:30",
    )
    marked = runtime.execution.projection()["positions"][0]
    assert marked["quote_status"] == "STALE"
    assert marked["pnl_valid"] is False
    assert marked["pnl_status"] == "MTM_STALE"


@pytest.mark.integration
def test_open_position_replays_authoritative_gap_candles_until_first_stop_only(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    base = request("gap-replay", parameters=paper_parameters(lot_size=65))
    req = type(base)(
        metadata=base.metadata, adapter=GapExitStrategy(), context_provider=base.context_provider,
        scheduler_interval_seconds=base.scheduler_interval_seconds,
    )
    runtime = service.deploy(req)
    tick(
        runtime, evaluation_id="entry", signal="BUY", contract="57351", entry=100.0,
        current_price=100.0, bar={"timestamp": "2026-07-14T09:20:00+05:30", "low": 100.0, "close": 100.0, "confirmed": True},
    )
    history = [
        {"index": 1, "timestamp": "2026-07-14T09:21:00+05:30", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 10.0, "confirmed": True, "is_closed": True},
        {"index": 2, "timestamp": "2026-07-14T09:22:00+05:30", "open": 96.0, "high": 96.0, "low": 94.0, "close": 94.5, "volume": 12.0, "confirmed": True, "is_closed": True},
        {"index": 3, "timestamp": "2026-07-14T09:23:00+05:30", "open": 94.0, "high": 95.0, "low": 90.0, "close": 91.0, "volume": 15.0, "confirmed": True, "is_closed": True},
    ]
    runtime.context_provider = lambda: {
        "symbol": "NIFTY_PE", "timeframe": "1m", "contract": "57351",
        "timestamp": "2026-07-14T09:23:00+05:30", "current_price": 91.0,
        "paper_price": 91.0, "option_price": 91.0,
        "bar": history[-1], "completed_candles": history,
        "data_readiness": {"DATA_READY": True},
        "argus": {"data": {"underlying": {"fetched_at": "2026-07-14T09:23:00+05:30"}, "atm_window": [
            {"pe": {"security_id": "57351", "ltp": 91.0, "fetched_at": "2026-07-14T09:23:00+05:30"}}
        ]}},
    }

    runtime.bootstrap_data()
    first = runtime.tick_once()
    second = runtime.tick_once()
    runtime.tick_once()
    state = runtime.execution.projection()

    assert first["decision"]["signal"] == "WAIT"
    assert second["decision"]["signal"] == "SELL"
    assert second["decision"]["candle_id"].endswith("2026-07-14T09:22:00+05:30")
    assert len([row for row in state["orders"] if row["position_effect"] == "CLOSE"]) == 1
    assert len([row for row in state["fills"] if row["position_effect"] == "CLOSE"]) == 1
    assert state["positions"][0]["status"] == "CLOSED"
    assert runtime._gap_replay_contexts == []
    assert all(row.get("paper_only") is True for row in state["orders"])


@pytest.mark.integration
def test_close_uses_held_contract_when_resolver_selects_new_atm_contract(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    runtime = service.deploy(request("held-contract-close", parameters=paper_parameters(lot_size=65)))
    held_option = {"security_id": 57344, "option_type": "CE", "strike": 24100}
    tick(
        runtime,
        evaluation_id="entry",
        signal="BUY",
        contract="57344",
        option_contract=held_option,
        entry=193.20,
        stop=186.50,
        target=278.26,
        close=193.20,
    )
    opened = runtime.execution.projection()["positions"][0]

    decision = tick(
        runtime,
        evaluation_id="exit",
        signal="SELL",
        position_effect="CLOSE",
        contract="57346",
        option_contract={"security_id": 57346, "option_type": "CE", "strike": 24150},
        exit=150.0,
        close=150.0,
        argus={"data": {"atm_window": [{"ce": {"security_id": 57344, "ltp": 180.0}}]}},
        timestamp="2026-07-14T09:30:00+05:30",
    )

    assert decision["paper_execution"]["status"] == "FILLED"
    state = runtime.execution.projection()
    close_order = state["orders"][-1]
    close_fill = state["fills"][-1]
    closed_trade = state["closed_trades"][-1]
    assert close_order["contract"] == "57344"
    assert close_order["position_id"] == opened["position_id"]
    assert close_order["requested_quantity"] == 65
    assert close_order["option_contract"] == held_option
    assert close_fill["contract"] == "57344"
    assert closed_trade["contract"] == "57344"
    assert closed_trade["status"] == "CLOSED"
    assert state["positions"][0]["status"] == "CLOSED"
    assert state["account"]["realized_pnl"] == closed_trade["realized_pnl"]
    assert all(order.get("rejection_reason") != "OPEN_POSITION_NOT_FOUND" for order in state["orders"])


@pytest.mark.safety
def test_close_rejects_ambiguous_multiple_open_positions(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    runtime = service.deploy(request("ambiguous-close", parameters=paper_parameters()))
    tick(runtime, evaluation_id="entry", signal="BUY", contract="57344", entry=100.0, stop=95.0, target=110.0, close=100.0)
    second = deepcopy(runtime.execution._state["positions"][0])
    second.update({"position_id": "pos_second", "contract": "57348", "option_contract": {"security_id": 57348}})
    runtime.execution._state["positions"].append(second)

    decision = tick(
        runtime,
        evaluation_id="ambiguous-exit",
        signal="SELL",
        position_effect="CLOSE",
        contract="57346",
        exit=150.0,
        argus={"data": {"atm_window": [{"ce": {"security_id": 57344, "ltp": 105.0}}]}},
        timestamp="2026-07-14T09:30:00+05:30",
    )

    assert decision["paper_execution"]["status"] == "REJECTED"
    assert decision["paper_execution"]["reason"] == "OPEN_POSITION_AMBIGUOUS"
    assert all(position["status"] == "OPEN" for position in runtime.execution.projection()["positions"])


@pytest.mark.integration
def test_atomic_paper_position_reconciliation_is_validated_backed_up_and_idempotent(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    target = service.deploy(request("BO_NIFTY_CE_1M", parameters=paper_parameters(lot_size=65)))
    other = service.deploy(request("PB_NIFTY_PE_1M", parameters=paper_parameters(lot_size=65)))
    held_option = {"security_id": 57344, "option_type": "CE", "strike": 24100}
    tick(target, evaluation_id="target-entry", signal="BUY", contract="57344", option_contract=held_option, entry=193.2, stop=186.5, target=278.26, close=193.2)
    tick(other, evaluation_id="other-entry", signal="BUY", contract="60000", entry=100.0, stop=95.0, target=110.0, close=100.0)
    position = target.execution.projection()["positions"][0]
    before = deepcopy(target.execution.projection())
    other_before = deepcopy(other.execution.projection())
    quote = {"security_id": 57344, "ltp": 180.0}

    dry_run = service.reconcile_paper_position(
        strategy_id="BO_NIFTY_CE_1M", position_id=position["position_id"],
        contract="57344", quantity=65, quote=quote, dry_run=True,
    )
    assert dry_run["status"] == "VALIDATED"
    assert target.execution.projection() == before

    result = service.reconcile_paper_position(
        strategy_id="BO_NIFTY_CE_1M", position_id=position["position_id"],
        contract="57344", quantity=65, quote=quote, dry_run=False,
        backup_root=str(tmp_path / "backups"),
    )
    assert result["status"] == "RECONCILED"
    assert result["paper_only"] is True
    assert result["live_trading_enabled"] is False
    assert result["broker_submission"] is False
    assert (tmp_path / "backups").joinpath(result["backup_path"].split("/")[-1]).is_dir()
    state = target.execution.projection()
    assert state["positions"][0]["status"] == "CLOSED"
    assert state["orders"][-1]["position_id"] == position["position_id"]
    assert state["orders"][-1]["contract"] == "57344"
    assert state["fills"][-1]["contract"] == "57344"
    assert state["closed_trades"][-1]["exit_reason"] == "RECONCILIATION"
    assert other.execution.projection() == other_before

    second = service.reconcile_paper_position(
        strategy_id="BO_NIFTY_CE_1M", position_id=position["position_id"],
        contract="57344", quantity=65, quote=quote, dry_run=False,
        backup_root=str(tmp_path / "backups"),
    )
    assert second["status"] == "ALREADY_RECONCILED"
    assert len(target.execution.projection()["fills"]) == 2


@pytest.mark.safety
@pytest.mark.parametrize(
    ("strategy_id", "position_id", "contract", "quantity", "quote", "reason"),
    [
        ("UNKNOWN", "position", "57344", 65, {"security_id": 57344, "ltp": 180.0}, "STRATEGY_RUNTIME_NOT_LOADED"),
        ("BO_NIFTY_CE_1M", "wrong", "57344", 65, {"security_id": 57344, "ltp": 180.0}, "POSITION_NOT_FOUND"),
        ("BO_NIFTY_CE_1M", "position", "57346", 65, {"security_id": 57346, "ltp": 180.0}, "CONTRACT_MISMATCH"),
        ("BO_NIFTY_CE_1M", "position", "57344", 50, {"security_id": 57344, "ltp": 180.0}, "QUANTITY_MISMATCH"),
        ("BO_NIFTY_CE_1M", "position", "57344", 65, {}, "AUTHORITATIVE_EXIT_PRICE_REQUIRED"),
    ],
)
def test_reconciliation_identity_and_quote_fail_closed(tmp_path, strategy_id, position_id, contract, quantity, quote, reason):
    service = StrategyLabService(str(tmp_path / "lab"))
    runtime = service.deploy(request("BO_NIFTY_CE_1M", parameters=paper_parameters(lot_size=65)))
    tick(runtime, evaluation_id="entry", signal="BUY", contract="57344", entry=193.2, stop=186.5, target=278.26, close=193.2)
    actual = runtime.execution.projection()["positions"][0]["position_id"]
    before = deepcopy(runtime.execution.projection())
    result = service.reconcile_paper_position(
        strategy_id=strategy_id,
        position_id=actual if position_id == "position" else position_id,
        contract=contract,
        quantity=quantity,
        quote=quote,
        dry_run=False,
        backup_root=str(tmp_path / "backups"),
    )
    assert result["status"] == "REJECTED"
    assert result["reason"] == reason
    assert runtime.execution.projection() == before


@pytest.mark.integration
def test_immutable_ids_and_complete_parent_child_lineage(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    runtime = service.deploy(request("lineage", parameters=paper_parameters()))
    decision = tick(runtime, evaluation_id="lineage-entry", signal="BUY", contract="NIFTY-TEST", entry=100.0, stop=95.0, target=110.0, close=100.0)
    state = runtime.execution.projection()
    order = state["orders"][0]
    fill = state["fills"][0]
    position = state["positions"][0]
    execution = decision["paper_execution"]

    assert order["parent_id"] == order["signal_id"]
    assert fill["parent_id"] == order["order_id"]
    assert position["parent_id"] == fill["fill_id"]
    assert order["signal_id"] in fill["lineage"]
    assert order["order_id"] in fill["lineage"]
    assert fill["fill_id"] in position["lineage"]
    assert execution["entity_id"] == fill["fill_id"]

    events = [row["event_type"] for row in runtime.workspace.transactions.read()]
    assert {
        "SignalCreated",
        "OrderCreated",
        "OrderFilled",
        "PositionOpened",
        "JournalCreated",
        "ReplayCreated",
        "StatisticsUpdated",
        "DashboardUpdated",
    }.issubset(events)
    assert runtime.workspace.transactions.verify()["valid"] is True


@pytest.mark.safety
def test_unconfigured_risk_fails_closed_and_emits_risk_rejected(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    runtime = service.deploy(request("unconfigured"))
    decision = tick(runtime, evaluation_id="reject-1", signal="BUY", entry=100.0, stop=95.0, contract="NIFTY-TEST", close=100.0)
    assert decision["paper_execution"]["status"] == "REJECTED"
    assert decision["paper_execution"]["reason"] == "PAPER_RISK_POLICY_REQUIRED"
    assert runtime.execution.projection()["fills"] == []
    assert "RiskRejected" in [row["event_type"] for row in runtime.workspace.transactions.read()]


@pytest.mark.safety
def test_duplicate_evaluation_cannot_duplicate_order_fill_or_position(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    runtime = service.deploy(request("idempotent", parameters=paper_parameters()))
    values = dict(evaluation_id="same-evaluation", signal="BUY", entry=100.0, stop=95.0, contract="NIFTY-TEST", close=100.0)
    first = tick(runtime, **values)["paper_execution"]
    second = tick(runtime, **values)["paper_execution"]
    state = runtime.execution.projection()
    assert second == first
    assert len(state["orders"]) == 1
    assert len(state["fills"]) == 1
    assert len([row for row in state["positions"] if row["status"] == "OPEN"]) == 1


@pytest.mark.integration
def test_pending_partial_filled_cancelled_and_expired_oms_states(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    runtime = service.deploy(request("oms", parameters=paper_parameters(lot_size=10)))
    pending = tick(
        runtime,
        evaluation_id="limit-1",
        signal="BUY",
        entry=100.0,
        stop=95.0,
        contract="NIFTY-TEST",
        order_type="LIMIT",
        limit_price=95.0,
        high=101.0,
        low=98.0,
        close=100.0,
    )
    assert pending["paper_execution"]["status"] == "PENDING"
    order_id = pending["paper_execution"]["order_id"]

    tick(runtime, evaluation_id="match-1", signal="WAIT", contract="NIFTY-TEST", high=96.0, low=94.0, close=95.0, available_quantity=4, timestamp="2026-07-14T09:25:00+05:30")
    assert runtime.execution.projection()["orders"][0]["status"] == "PARTIAL"
    assert runtime.execution.projection()["orders"][0]["filled_quantity"] == 4
    tick(runtime, evaluation_id="match-2", signal="WAIT", contract="NIFTY-TEST", high=96.0, low=94.0, close=95.0, available_quantity=6, timestamp="2026-07-14T09:30:00+05:30")
    assert runtime.execution.projection()["orders"][0]["status"] == "FILLED"
    assert len(runtime.execution.projection()["fills"]) == 2

    second_service = StrategyLabService(str(tmp_path / "cancel-lab"))
    second = second_service.deploy(request("cancel", parameters=paper_parameters(lot_size=10)))
    second_pending = tick(second, evaluation_id="limit-2", signal="BUY", entry=100.0, stop=95.0, contract="NIFTY-CANCEL", order_type="LIMIT", limit_price=90.0, high=101.0, low=98.0, close=100.0)
    second_order = second_pending["paper_execution"]["order_id"]
    assert second.execution.cancel_order(second_order)["status"] == "CANCELLED"

    third_service = StrategyLabService(str(tmp_path / "expire-lab"))
    third = third_service.deploy(request("expire", parameters=paper_parameters(lot_size=10)))
    third_pending = tick(third, evaluation_id="limit-3", signal="BUY", entry=100.0, stop=95.0, contract="NIFTY-EXPIRE", order_type="LIMIT", limit_price=90.0, high=101.0, low=98.0, close=100.0)
    third_order = third_pending["paper_execution"]["order_id"]
    assert third.execution.expire_order(third_order)["status"] == "EXPIRED"


@pytest.mark.integration
def test_restart_recovers_authoritative_transaction_state(tmp_path):
    root = str(tmp_path / "lab")
    deployment = request("restart", parameters=paper_parameters())
    first = StrategyLabService(root)
    runtime = first.deploy(deployment)
    tick(runtime, evaluation_id="entry-restart", signal="BUY", entry=100.0, stop=95.0, contract="NIFTY-TEST", close=100.0)
    before = runtime.execution.projection()

    restarted = StrategyLabService(root)
    recovered = restarted.deploy(deployment)
    after = recovered.execution.projection()
    assert after["account"] == before["account"]
    assert after["orders"] == before["orders"]
    assert after["fills"] == before["fills"]
    assert after["positions"] == before["positions"]
    tick(recovered, evaluation_id="exit-restart", signal="SELL", position_effect="CLOSE", exit=110.0, contract="NIFTY-TEST", close=110.0, timestamp="2026-07-14T09:30:00+05:30")
    closed = recovered.execution.projection()
    final_service = StrategyLabService(root)
    final_runtime = final_service.deploy(deployment)
    final_state = final_runtime.execution.projection()
    assert final_state["closed_trades"] == closed["closed_trades"]
    assert final_state["account"] == closed["account"]
    assert final_state["statistics"] == closed["statistics"]


@pytest.mark.integration
def test_future_entry_persists_supplied_held_position_risk_snapshot(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    parameters = paper_parameters(lot_size=65)
    parameters["paper_account"]["slippage_bps"] = 0.0
    runtime = service.deploy(request("risk-snapshot", parameters=parameters))
    tick(
        runtime,
        evaluation_id="risk-entry",
        signal="BUY",
        contract="57351",
        entry=150.75,
        initial_stop=146.40,
        current_stop=146.40,
        stop=146.40,
        underlying_stop=24210.0,
        target=261.90,
        trailing_enabled=True,
        trailing_activation_price=160.0,
        trailing_anchor=150.75,
        trailing_distance=4.0,
        trailing_step=1.0,
        risk_source="STRATEGY_SUPPLIED_OPTION_RISK",
        risk_source_timestamp="2026-07-14T09:20:00+05:30",
        risk_rule_version="RISK_RULE_V1",
        close=150.75,
    )

    state = runtime.execution.projection()
    order = state["orders"][0]
    position = state["positions"][0]
    expected = {
        "protective_stop": 146.40,
        "initial_stop": 146.40,
        "current_stop": 146.40,
        "initial_risk_per_unit": pytest.approx(4.35),
        "trailing_enabled": True,
        "trailing_activation_price": 160.0,
        "trailing_anchor": 150.75,
        "trailing_distance": 4.0,
        "trailing_step": 1.0,
        "risk_source": "STRATEGY_SUPPLIED_OPTION_RISK",
        "risk_rule_version": "RISK_RULE_V1",
    }
    for key, value in expected.items():
        assert order[key] == value
        assert position[key] == value
    assert position["held_security_id"] == position["contract"] == "57351"
    assert position["underlying_initial_stop"] == 24210.0
    assert position["underlying_current_stop"] == 24210.0
    assert position["underlying_stop"] == 24210.0
    assert position["strategy_version"] == "1.0.0"
    assert position["risk_status"] == "REPORTED"
    assert position["risk_snapshot"]["position_id"] == position["position_id"]
    assert position["risk_audit"][0]["event"] == "POSITION_RISK_INITIALIZED"
    assert state["paper_only"] is True
    assert state["live_trading_enabled"] is False
    assert state["broker_submission"] is False


@pytest.mark.integration
def test_missing_option_risk_remains_truthful_and_distinct_from_underlying_stop(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    runtime = service.deploy(request("null-risk", parameters=paper_parameters(lot_size=65)))
    tick(
        runtime,
        evaluation_id="underlying-only-entry",
        signal="BUY",
        contract="57351",
        entry=150.75,
        underlying_stop=24210.0,
        close=150.75,
    )
    position = runtime.execution.projection()["positions"][0]
    assert position["initial_stop"] is None
    assert position["current_stop"] is None
    assert position["protective_stop"] is None
    assert position["initial_risk_per_unit"] is None
    assert position["target"] is None
    assert position["trailing_enabled"] is None
    assert position["underlying_initial_stop"] == 24210.0
    assert position["underlying_current_stop"] == 24210.0

    entirely_missing = StrategyLabService(str(tmp_path / "missing"))
    missing_runtime = entirely_missing.deploy(request("missing-risk", parameters=paper_parameters(lot_size=65)))
    tick(missing_runtime, evaluation_id="missing-entry", signal="BUY", contract="57351", entry=150.75, close=150.75)
    missing_position = missing_runtime.execution.projection()["positions"][0]
    assert missing_position["risk_status"] == "NOT_REPORTED"
    assert missing_position["risk_snapshot"]["current_stop"] is None
    assert missing_position["risk_snapshot"]["underlying_current_stop"] is None


@pytest.mark.integration
def test_risk_updates_are_monotonic_restart_safe_and_held_contract_isolated(tmp_path):
    root = str(tmp_path / "lab")
    deployment = request("held-risk", parameters=paper_parameters(lot_size=65))
    service = StrategyLabService(root)
    runtime = service.deploy(deployment)
    tick(
        runtime,
        evaluation_id="entry",
        signal="BUY",
        contract="57351",
        entry=150.75,
        current_stop=146.40,
        underlying_stop=24210.0,
        target=261.90,
        close=150.75,
    )
    opened = runtime.execution.projection()["positions"][0]
    position_id = opened["position_id"]
    order_ledger_before = runtime.workspace.order_ledger.path.read_bytes()
    fill_ledger_before = runtime.workspace.fill_ledger.path.read_bytes()
    orders_before = deepcopy(runtime.execution.projection()["orders"])
    fills_before = deepcopy(runtime.execution.projection()["fills"])
    closed_before = deepcopy(runtime.execution.projection()["closed_trades"])

    tick(
        runtime,
        evaluation_id="trail-forward",
        signal="WAIT",
        contract="57351",
        risk_position_id=position_id,
        risk_contract="57351",
        current_stop=149.0,
        underlying_stop=24240.0,
        trailing_enabled=True,
        trailing_anchor=160.0,
        close=155.0,
        timestamp="2026-07-14T09:21:00+05:30",
    )
    advanced = runtime.execution.projection()["positions"][0]
    assert advanced["initial_stop"] == 146.40
    assert advanced["current_stop"] == advanced["protective_stop"] == advanced["stop"] == 149.0
    assert advanced["underlying_current_stop"] == 24240.0
    assert advanced["risk_audit"][-1]["event"] == "POSITION_RISK_UPDATED"

    tick(
        runtime,
        evaluation_id="trail-backward",
        signal="WAIT",
        contract="57351",
        risk_position_id=position_id,
        risk_contract="57351",
        current_stop=148.0,
        underlying_stop=24220.0,
        close=155.0,
        timestamp="2026-07-14T09:22:00+05:30",
    )
    tick(
        runtime,
        evaluation_id="atm-rotation",
        signal="WAIT",
        contract="57353",
        risk_position_id=position_id,
        risk_contract="57353",
        current_stop=170.0,
        underlying_stop=24300.0,
        close=170.0,
        timestamp="2026-07-14T09:23:00+05:30",
    )
    isolated = runtime.execution.projection()["positions"][0]
    assert isolated["contract"] == isolated["held_security_id"] == "57351"
    assert isolated["initial_stop"] == 146.40
    assert isolated["current_stop"] == 149.0
    assert isolated["underlying_current_stop"] == 24240.0
    assert len(isolated["risk_audit"]) == 2

    restarted = StrategyLabService(root).deploy(deployment)
    restored = restarted.execution.projection()["positions"][0]
    assert restored["risk_snapshot"] == isolated["risk_snapshot"]
    assert restored["risk_audit"] == isolated["risk_audit"]
    dashboard_position = service.dashboard()["execution"]["authoritative_open_positions"][0]
    assert dashboard_position["position_id"] == position_id
    assert dashboard_position["risk_snapshot"] == restored["risk_snapshot"]

    final_state = runtime.execution.projection()
    assert final_state["orders"] == orders_before
    assert final_state["fills"] == fills_before
    assert final_state["closed_trades"] == closed_before
    assert runtime.workspace.order_ledger.path.read_bytes() == order_ledger_before
    assert runtime.workspace.fill_ledger.path.read_bytes() == fill_ledger_before
    assert final_state["broker_submission"] is False


@pytest.mark.safety
def test_strategy_capital_positions_ledgers_and_pnl_are_isolated(tmp_path):
    service = StrategyLabService(str(tmp_path / "lab"))
    alpha = service.deploy(request("alpha-capital", parameters=paper_parameters(initial_capital=50_000)))
    beta = service.deploy(request("beta-capital", parameters=paper_parameters(initial_capital=30_000, lot_size=10)))
    tick(alpha, evaluation_id="alpha-entry", signal="BUY", entry=100.0, stop=95.0, contract="ALPHA", close=100.0)

    alpha_state = alpha.execution.projection()
    beta_state = beta.execution.projection()
    assert alpha_state["account"]["initial_capital"] == 50_000
    assert beta_state["account"]["initial_capital"] == 30_000
    assert len(alpha_state["orders"]) == 1
    assert beta_state["orders"] == []
    assert alpha.workspace.root != beta.workspace.root
    assert alpha.workspace.order_ledger.path != beta.workspace.order_ledger.path
    assert service.portfolio()["total_equity"] == pytest.approx(
        alpha_state["account"]["current_equity"] + beta_state["account"]["current_equity"]
    )
    portfolio = service.portfolio()
    assert portfolio["initial_capital"] == pytest.approx(80_000)
    assert portfolio["current_capital"] == pytest.approx(portfolio["total_equity"])
    assert portfolio["available_capital"] == pytest.approx(
        alpha_state["account"]["available_margin"] + beta_state["account"]["available_margin"]
    )
    assert portfolio["open_pnl"] == pytest.approx(
        alpha_state["account"]["unrealized_pnl"] + beta_state["account"]["unrealized_pnl"]
    )
    assert portfolio["closed_pnl"] == pytest.approx(
        alpha_state["account"]["realized_pnl"] + beta_state["account"]["realized_pnl"]
    )
    assert service.portfolio()["multi_portfolio_ready"] is True
    assert service.portfolio()["multi_portfolio_enabled"] is False

    dashboard = service.dashboard()
    assert dashboard["execution"]["order_count"] == 1
    assert dashboard["execution"]["fill_count"] == 1
    assert dashboard["execution"]["position_count"] == 1
    assert dashboard["execution"]["order_counts"]["FILLED"] == 1
    assert dashboard["execution"]["paper_only"] is True
    assert dashboard["review"]["status"] == "available"
    assert dashboard["review"]["validation"] == []


@pytest.mark.unit
def test_today_pnl_uses_ist_exit_date_and_excludes_validation_state():
    now = datetime(2026, 7, 29, 6, 0, tzinfo=timezone.utc)
    account = {
        "initial_capital": 100_000,
        "current_equity": 101_500,
        "available_margin": 101_500,
        "margin_used": 0,
        "daily_pnl": 9_999,
        "realized_pnl": 1_500,
        "unrealized_pnl": 0,
        "maximum_drawdown": 0,
        "drawdown": 0,
    }
    prior = {
        "strategy_id": "PB_NIFTY_CE_1M",
        "account": account,
        "positions": [],
        "closed_trades": [{
            "trade_id": "prior",
            "exit_time": "2026-07-28T09:00:00+00:00",
            "realized_pnl": 1_500,
        }],
        "statistics": {},
        "risk_policy": {},
    }
    validation = {
        **prior,
        "strategy_id": "validation_nifty_3m_oracle_paper",
        "closed_trades": [{
            "trade_id": "fixture",
            "exit_time": "2026-07-29T05:00:00+00:00",
            "realized_pnl": 3_500,
        }],
    }
    result = aggregate_portfolio([prior, validation], now=now)
    assert result["trading_date"] == "2026-07-29"
    assert result["today_pnl"] == 0
    assert result["session_realized_pnl"] == 0


@pytest.mark.unit
def test_today_pnl_is_current_day_realized_plus_open_mtm():
    now = datetime(2026, 7, 29, 6, 0, tzinfo=timezone.utc)
    state = {
        "strategy_id": "PB_NIFTY_PE_1M",
        "account": {
            "initial_capital": 100_000,
            "current_equity": 100_240,
            "available_margin": 90_000,
            "margin_used": 10_000,
            "daily_pnl": -999,
            "realized_pnl": 200,
            "unrealized_pnl": 40,
            "maximum_drawdown": 0,
            "drawdown": 0,
        },
        "positions": [{"position_id": "open", "status": "OPEN"}],
        "closed_trades": [{
            "trade_id": "today",
            "exit_time": "2026-07-29T04:00:00+00:00",
            "realized_pnl": 200,
        }],
        "statistics": {},
        "risk_policy": {},
    }
    result = aggregate_portfolio([state], now=now)
    assert result["session_realized_pnl"] == 200
    assert result["open_pnl"] == 40
    assert result["today_pnl"] == 240


@pytest.mark.unit
def test_fixed_rupee_and_percent_sizing_are_deterministic(tmp_path):
    rupee_service = StrategyLabService(str(tmp_path / "rupee"))
    rupee = rupee_service.deploy(request("rupee", parameters=paper_parameters(sizing_mode="FIXED_RUPEE_RISK", fixed_lots=None, lot_size=10, fixed_rupee_risk=1_000)))
    tick(rupee, evaluation_id="rupee-entry", signal="BUY", entry=100.0, stop=95.0, contract="R", close=100.0)
    assert rupee.execution.projection()["positions"][0]["quantity"] == 200

    percent_service = StrategyLabService(str(tmp_path / "percent"))
    percent = percent_service.deploy(request("percent", parameters=paper_parameters(sizing_mode="FIXED_PERCENT", fixed_lots=None, lot_size=10, fixed_risk_percent=1.0)))
    tick(percent, evaluation_id="percent-entry", signal="BUY", entry=100.0, stop=95.0, contract="P", close=100.0)
    assert percent.execution.projection()["positions"][0]["quantity"] == 100


@pytest.mark.integration
def test_paper_engine_routes_are_get_only():
    paths = {
        "/v1/strategy-lab/paper/portfolio",
        "/v1/strategy-lab/paper/capital",
        "/v1/strategy-lab/paper/positions",
        "/v1/strategy-lab/paper/orders",
        "/v1/strategy-lab/paper/fills",
        "/v1/strategy-lab/paper/statistics",
        "/v1/strategy-lab/paper/open-trades",
        "/v1/strategy-lab/paper/closed-trades",
    }
    routes = [route for route in app.routes if getattr(route, "path", None) in paths]
    assert {route.path for route in routes} == paths
    assert all(route.methods == {"GET"} for route in routes)
