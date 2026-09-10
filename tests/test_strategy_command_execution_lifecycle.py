from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from src.paper_trading.contracts import OptionContractResolver
from src.strategy_command import (
    ConfiguredOptionContractResolver,
    StrategyCommandRuntimeBridge,
    StrategyCommandService,
)
from src.strategy_lab import StrategyLabService
from src.strategy_lab import (
    DeploymentRequest,
    DisabledPaperExecution,
    StrategyInputType,
    StrategyMetadata,
)


class InstrumentMaster:
    def resolve(self, **values):
        return {
            "security_id": str(values["security_id"]),
            "lot_size": 50,
            "source": "DHAN_INSTRUMENT_MASTER_TEST_FIXTURE",
            "exchange_segment": "NSE_FNO",
        }


class WaitOnlyStrategy:
    def evaluate(self, _context):
        return {"evaluation_id": "wait-only", "signal": "WAIT"}


def context(timestamp: str, candle_id: str, premium: float) -> dict:
    rows = []
    for offset, security_id in (
        (-100, "19999"),
        (-50, "20000"),
        (0, "20001"),
        (50, "20002"),
        (100, "20003"),
    ):
        strike = 24000 + offset
        rows.append({
            "strike": strike,
            "ce": {
                "security_id": security_id,
                "trading_symbol": f"NIFTY260728C{strike}",
                "ltp": premium,
                "top_bid_price": premium - 0.5,
                "top_bid_quantity": 500,
                "top_ask_price": premium + 0.5,
                "top_ask_quantity": 500,
                "oi": 100_000,
                "volume": 25_000,
                "timestamp": timestamp,
            },
            "pe": {
                "security_id": f"3{security_id}",
                "trading_symbol": f"NIFTY260728P{strike}",
                "ltp": premium,
                "top_bid_price": premium - 0.5,
                "top_bid_quantity": 500,
                "top_ask_price": premium + 0.5,
                "top_ask_quantity": 500,
                "oi": 100_000,
                "volume": 25_000,
                "timestamp": timestamp,
            },
        })
    return {
        "candle_id": candle_id,
        "evaluation_id": candle_id,
        "timestamp": timestamp,
        "source_timestamp": timestamp,
        "source_health": "FRESH",
        "symbol": "NIFTY",
        "underlying": "NIFTY",
        "timeframe": "1m",
        "confirmed": True,
        "bar": {
            "index": int(candle_id.rsplit("-", 1)[-1]),
            "timestamp": timestamp,
            "open": 24000.0,
            "high": 24000.0,
            "low": 24000.0,
            "close": 24000.0,
            "volume": 1_000_000,
            "confirmed": True,
        },
        "price_action": {
            "direction": "CALL",
            "source": "IMMUTABLE_RECORDED_FIXTURE",
            "timestamp": timestamp,
        },
        "vob": {
            "direction": "CALL",
            "source": "IMMUTABLE_RECORDED_FIXTURE",
            "evaluated_through": timestamp,
        },
        "timeframe_evidence": {
            "1m": {
                "direction": "CALL",
                "freshness": "FRESH",
                "timestamp": timestamp,
            },
        },
        "argus": {
            "status": "available",
            "freshness": "fresh",
            "data": {
                "fetched_at": timestamp,
                "underlying": {
                    "symbol": "NIFTY",
                    "expiry": "2026-07-28",
                    "atm_strike": 24000,
                    "ltp": 24000,
                    "fetched_at": timestamp,
                },
                "atm_window": rows,
            },
        },
    }


def runtime_fixture(tmp_path, *, fixed_rupee_risk: int = 1_500):
    command = StrategyCommandService(tmp_path / "command")
    version = next(
        row
        for row in command.projection()["versions"]
        if row["strategy_id"] == "BP_NIFTY_CE_1M"
    )
    roles = {
        role: ["1m"]
        for role in (
            "entry",
            "signal",
            "price_action",
            "vob",
            "context",
            "confirmation",
            "regime",
            "guardian",
            "exit",
        )
    }
    draft = command.save_draft(
        strategy_id=version["strategy_id"],
        strategy_version=version["version"],
        deployment_instance_id="bull-pulse-command-paper",
        configuration={
            "market": {
                "instrument": "NIFTY",
                "option_sides": ["CALL"],
                "strike_offset": 2,
                "maximum_spread": 2.0,
                "minimum_oi": 10_000,
                "minimum_volume": 1_000,
            },
            "timeframes": {"roles": roles},
            "position": {
                "fixed_lots": 1,
                "maximum_lots": 1,
                "fixed_rupee_risk": fixed_rupee_risk,
            },
            "session": {
                "first_entry_time": "00:00",
                "last_entry_time": "23:59",
                "cooldown_seconds": 0,
            },
            "execution": {
                "enabled": True,
                "path": "ORACLE_PAPER",
                "paper_only": True,
                "live_trading_enabled": False,
                "broker_submission": False,
            },
        },
    )
    command.deploy(
        draft["deployment_instance_id"],
        expected_configuration_hash=draft["configuration_hash"],
    )
    lab = StrategyLabService(str(tmp_path / "lab"))
    lab.subscribe_events(command.observe_domain_event)
    bridge = StrategyCommandRuntimeBridge(
        command=command,
        lab=lab,
        context_factory=lambda _: lambda: {},
    )
    deployment = command.deployment(draft["deployment_instance_id"])
    request = bridge._request(deployment)
    request = replace(
        request,
        option_resolver=ConfiguredOptionContractResolver(
            deployment["configuration"],
            OptionContractResolver(InstrumentMaster()),
        ),
    )
    return lab.deploy(request), command, lab, deployment


@pytest.mark.integration
def test_real_strategy_signal_runs_one_complete_paper_lifecycle(tmp_path):
    runtime, command, lab, deployment = runtime_fixture(tmp_path)

    waiting = runtime.tick_once(
        context("2026-07-24T10:30:00+05:30", "bull-1", 100.0)
    )
    assert waiting["decision"]["signal"] == "WAIT"
    assert waiting["decision"]["paper_execution"]["status"] == "NO_ACTION"

    opened = runtime.tick_once(
        context("2026-07-24T10:31:00+05:30", "bull-2", 110.0)
    )
    assert opened["decision"]["signal"] == "BUY"
    assert opened["decision"]["total_score"] == 100
    assert opened["decision"]["paper_execution"]["status"] == "FILLED"
    state = runtime.execution.projection()
    assert len(state["missions"]) == 1
    assert len(state["orders"]) == len(state["fills"]) == 1
    assert state["positions"][0]["contract"] == "20003"
    assert state["positions"][0]["quantity"] == 50
    assert state["positions"][0]["mission_id"] == state["missions"][0]["mission_id"]
    assert state["missions"][0]["status"] == "GUARDIAN_ACTIVE"
    assert state["missions"][0]["decision_evidence"]["total_score"] == 100
    assert state["missions"][0]["paper_only"] is True
    assert state["missions"][0]["live_trading_enabled"] is False
    assert state["missions"][0]["broker_submission"] is False

    closed = runtime.tick_once(
        context("2026-07-24T10:32:00+05:30", "bull-3", 88.0)
    )
    assert closed["decision"]["signal"] == "SELL"
    assert closed["decision"]["paper_execution"]["status"] == "FILLED"
    state = runtime.execution.projection()
    assert len(state["orders"]) == len(state["fills"]) == 2
    assert len(state["closed_trades"]) == 1
    assert state["missions"][0]["status"] == "EXITED"
    assert state["closed_trades"][0]["exit_reason"] == "LEG_STOP_LOSS_HIT"
    assert state["closed_trades"][0]["guardian_contribution"] == "PAPER_GUARDIAN"
    assert runtime.status()["lifecycle"]["runtime_state"] == "EXITED"

    source = deepcopy(runtime.status())
    projected = StrategyCommandService(
        tmp_path / "command",
        runtime_provider=lambda: {"strategies": [source]},
    ).projection()
    instance = next(
        row
        for row in projected["deployments"]
        if row["deployment_instance_id"] == deployment["deployment_instance_id"]
    )
    assert instance["runtime"]["state"] == "EXITED"
    assert instance["runtime"]["lifecycle"]["latest_trade"]["mission_id"]
    assert instance["analytics"]["trades"] == 1
    messages = {
        row["message"]
        for row in projected["notifications"]
        if row["deployment_instance_id"] == deployment["deployment_instance_id"]
    }
    assert {
        "Strategy signal ready",
        "Paper mission created",
        "Paper order created",
        "Paper fill recorded",
        "Guardian monitoring active",
        "Paper position exited",
        "Paper trade completed",
    } <= messages


@pytest.mark.integration
def test_restart_and_duplicate_candle_do_not_duplicate_mission_order_or_fill(tmp_path):
    runtime, command, lab, deployment = runtime_fixture(tmp_path)
    first = context("2026-07-24T10:30:00+05:30", "restart-1", 100.0)
    entry = context("2026-07-24T10:31:00+05:30", "restart-2", 110.0)
    runtime.tick_once(first)
    runtime.tick_once(entry)
    before = runtime.execution.projection()

    restarted = StrategyLabService(str(tmp_path / "lab"))
    bridge = StrategyCommandRuntimeBridge(
        command=command,
        lab=restarted,
        context_factory=lambda _: lambda: {},
    )
    request = bridge._request(deployment)
    request = replace(
        request,
        option_resolver=ConfiguredOptionContractResolver(
            deployment["configuration"],
            OptionContractResolver(InstrumentMaster()),
        ),
    )
    restored = restarted.deploy(request)
    duplicate = restored.tick_once(entry)
    after = restored.execution.projection()

    assert duplicate["reason"] == "CANDLE_ALREADY_PROCESSED"
    assert len(after["missions"]) == len(before["missions"]) == 1
    assert len(after["orders"]) == len(before["orders"]) == 1
    assert len(after["fills"]) == len(before["fills"]) == 1
    assert after["positions"][0]["contract"] == "20003"
    assert after["positions"][0]["status"] == "OPEN"


@pytest.mark.unit
def test_single_timeframe_consensus_is_confirmed_without_fake_confirmation(tmp_path):
    runtime, _, _, _ = runtime_fixture(tmp_path)
    runtime.tick_once(
        context("2026-07-24T10:30:00+05:30", "single-1", 100.0)
    )
    decision = runtime.tick_once(
        context("2026-07-24T10:31:00+05:30", "single-2", 110.0)
    )["decision"]
    assert decision["timeframe_consensus"] == {
        "mode": "PRIMARY_PLUS_CONFIRMATION",
        "votes": {"1m": "BULLISH"},
        "required_timeframes": ["1m"],
        "stale_timeframes": [],
        "consensus": "BULLISH",
        "reason": "SINGLE_TIMEFRAME_CONFIRMED",
    }


@pytest.mark.integration
def test_one_trade_per_instrument_conflict_is_atomic_and_persisted(tmp_path):
    first, command, lab, deployment = runtime_fixture(tmp_path)
    first.tick_once(context("2026-07-24T10:30:00+05:30", "first-1", 100.0))
    first.tick_once(context("2026-07-24T10:31:00+05:30", "first-2", 110.0))
    assert len(first.execution.projection()["missions"]) == 1

    second_draft = command.save_draft(
        strategy_id=deployment["strategy_id"],
        strategy_version=deployment["strategy_version"],
        deployment_instance_id="bull-pulse-command-paper-two",
        name="Bull Pulse · Conflict Peer",
        configuration=deployment["configuration"],
    )
    command.deploy(
        second_draft["deployment_instance_id"],
        expected_configuration_hash=second_draft["configuration_hash"],
    )
    second_deployment = command.deployment(second_draft["deployment_instance_id"])
    bridge = StrategyCommandRuntimeBridge(
        command=command,
        lab=lab,
        context_factory=lambda _: lambda: {},
    )
    request = bridge._request(second_deployment)
    request = replace(
        request,
        option_resolver=ConfiguredOptionContractResolver(
            second_deployment["configuration"],
            OptionContractResolver(InstrumentMaster()),
        ),
    )
    second = lab.deploy(request)
    second.tick_once(context("2026-07-24T10:30:00+05:30", "second-1", 100.0))
    result = second.tick_once(
        context("2026-07-24T10:31:00+05:30", "second-2", 110.0)
    )
    execution = result["decision"]["paper_execution"]
    state = second.execution.projection()

    assert execution["status"] == "REJECTED"
    assert execution["reason"] == "CONFLICT_POLICY_ONE_TRADE_PER_INSTRUMENT_ACTIVE"
    assert state["missions"] == []
    assert state["fills"] == []
    assert state["orders"][0]["conflict_decision"]["decision"] == "BLOCK"
    assert state["orders"][0]["conflict_decision"]["incumbents"][0][
        "deployment_instance_id"
    ] == "bull-pulse-command-paper"
    assert len(first.execution.projection()["orders"]) == 1


@pytest.mark.integration
def test_stale_evidence_and_invalid_risk_never_create_a_fill(tmp_path):
    stale, _, _, _ = runtime_fixture(tmp_path / "stale")
    stale.tick_once(context("2026-07-24T10:30:00+05:30", "stale-1", 100.0))
    stale_signal = context(
        "2026-07-24T10:31:00+05:30",
        "stale-2",
        110.0,
    )
    stale_signal["timeframe_evidence"]["1m"]["freshness"] = "STALE"
    stale_result = stale.tick_once(stale_signal)["decision"]
    assert stale_result["signal"] == "WAIT"
    assert stale_result["reason"] == "SINGLE_TIMEFRAME_STALE"
    assert stale.execution.projection()["orders"] == []
    assert stale.execution.projection()["fills"] == []

    risk_blocked, _, _, _ = runtime_fixture(
        tmp_path / "risk",
        fixed_rupee_risk=500,
    )
    risk_blocked.tick_once(
        context("2026-07-24T10:30:00+05:30", "risk-1", 100.0)
    )
    rejected = risk_blocked.tick_once(
        context("2026-07-24T10:31:00+05:30", "risk-2", 110.0)
    )["decision"]["paper_execution"]
    state = risk_blocked.execution.projection()
    assert rejected["status"] == "REJECTED"
    assert rejected["reason"] == "FIXED_RUPEE_RISK_EXCEEDED"
    assert state["missions"] == []
    assert len(state["orders"]) == 1
    assert state["fills"] == []


@pytest.mark.integration
def test_dashboard_projects_non_executing_runtime_without_paper_adapter(tmp_path):
    lab = StrategyLabService(str(tmp_path / "lab"))
    lab.deploy(
        DeploymentRequest(
            metadata=StrategyMetadata(
                strategy_id="observe-only",
                name="Observe only",
                version="1.0.0",
                author="CITADEL_TEST",
                input_type=StrategyInputType.PYTHON,
                supported_markets=["NIFTY"],
                supported_timeframes=["1m"],
                rr=2.0,
                risk_model="NOT_APPLICABLE",
                parameters={"execution_path": "OBSERVE"},
            ),
            adapter=WaitOnlyStrategy(),
            context_provider=lambda: {},
            execution=DisabledPaperExecution(),
        )
    )

    dashboard = lab.dashboard()

    assert len(dashboard["strategies"]) == 1
    assert dashboard["execution"]["orders"] == []
    assert dashboard["execution"]["fills"] == []
