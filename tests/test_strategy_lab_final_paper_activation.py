from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from src.paper_trading.models import ResolvedOptionContract
from src.strategy_lab import StrategyLabService
from src.strategy_lab.completed_candle import CompletedCandleContextProvider
from src.strategy_lab.core import OrderBlock
from src.strategy_lab.strategies.breakout_main import build_deployment_request as breakout_request
from src.strategy_lab.strategies.breakout_main.adapters import BreakoutMainSignalEngine
from src.strategy_lab.strategies.pullback_master import (
    PullbackMasterConfig,
    PullbackMasterNativeAdapter,
    PullbackMasterStrategyEngine,
    build_deployment_request as pullback_request,
)


def _block(*, bull, top, bottom, loc):
    return OrderBlock(
        bull=bull, top=top, btm=bottom, avg=(top + bottom) / 2,
        loc=loc, vol=100.0, direction=1 if bull else -1,
    )


def _argus():
    return {
        "status": "available",
        "freshness": "fresh",
        "data": {
            "underlying": {
                "symbol": "NIFTY", "atm_strike": 24_000, "expiry": "2026-07-16",
                "market_state": "OPEN", "fetched_at": "2026-07-15T09:20:00+05:30",
            },
            "atm_window": [{
                "strike": 24_000,
                "ce": {"security_id": "NIFTY-CE", "ltp": 100.0},
                "pe": {"security_id": "NIFTY-PE", "ltp": 100.0},
            }],
        },
    }


class _Resolver:
    def resolve(self, *_args, **_kwargs):
        return ResolvedOptionContract(
            "NIFTY-CE", "NSE_FNO", "NIFTY", "CE", 24_000.0,
            "2026-07-16", 25, 100.0, None, None, None, None,
            "TEST_INSTRUMENT_MASTER", "TEST_OPTION_CHAIN",
        )

    def quote_existing(self, _argus_response, contract):
        assert contract == "NIFTY-CE"
        return {"security_id": contract, "ltp": 110.0}


def _context(index, timestamp, open_, high, low, close):
    return {
        "candle_id": f"NIFTY:5m:{timestamp}",
        "symbol": "NIFTY", "underlying": "NIFTY", "timeframe": "5m",
        "timestamp": timestamp, "closed": True, "is_closed": True,
        "argus": _argus(),
        "bar": {
            "index": index, "timestamp": timestamp, "open": open_, "high": high,
            "low": low, "close": close, "volume": 100.0,
            "confirmed": True, "is_closed": True,
        },
    }


@pytest.mark.unit
def test_completed_candle_provider_fans_out_one_cached_context_without_extra_argus_calls():
    at = datetime.fromisoformat("2026-07-15T09:20:00+05:30")
    rows = [{
        "symbol": "NIFTY", "timeframe": "5m", "timestamp": "2026-07-15T09:15:00+05:30",
        "candle_closed_at": at.isoformat(), "open": 100, "high": 102,
        "low": 99, "close": 101, "volume": 100, "closed": True,
        "source": "DHAN_DATA_API", "received_at": at.isoformat(),
    }]

    class Source:
        def load_cache(self):
            return rows

    calls = []
    provider = CompletedCandleContextProvider(
        candle_source=Source(), argus_provider=lambda: calls.append(1) or _argus(),
        clock=lambda: at + timedelta(seconds=1),
    )
    first, second = provider(), provider()
    assert first == second
    assert len(calls) == 1
    assert first["warmup_candle_count"] == 1
    assert first["completed_candles"] == [first["bar"]]

    stale = CompletedCandleContextProvider(
        candle_source=Source(),
        argus_provider=lambda: {
            **_argus(),
            "status": "stale",
            "freshness": "stale",
            "data": {
                **_argus()["data"],
                "underlying": {
                    **_argus()["data"]["underlying"],
                    "fetched_at": (at - timedelta(seconds=700)).isoformat()
                }
            }
        },
        clock=lambda: at + timedelta(seconds=1),
    )()
    assert stale["source_reason"] == "AUTHORITATIVE_OPTION_CHAIN_STALE"


@pytest.mark.integration
def test_both_native_strategies_open_and_close_isolated_paper_positions_exactly_once(tmp_path):
    pullback = PullbackMasterNativeAdapter(
        engine=PullbackMasterStrategyEngine(PullbackMasterConfig(pullback_mode="V3"))
    )
    pullback.engine.order_blocks.bullish.append(_block(bull=True, top=100, bottom=95, loc=1_000))
    pullback.engine.order_blocks.bearish.append(_block(bull=False, top=125, bottom=120, loc=2_000))

    breakout = BreakoutMainSignalEngine()
    breakout.engine.order_blocks.bearish.append(_block(bull=False, top=100, bottom=95, loc=3_000))

    service = StrategyLabService(str(tmp_path / "lab"))
    pull_runtime = service.deploy(replace(pullback_request(), adapter=pullback, option_resolver=_Resolver()))
    break_runtime = service.deploy(replace(breakout_request(), adapter=breakout, option_resolver=_Resolver()))

    pull_entry = _context(1, "2026-07-15T09:20:00+05:30", 102, 103, 99, 101)
    break_signal = _context(1, "2026-07-15T09:20:00+05:30", 99, 102, 98, 101)
    break_entry = _context(2, "2026-07-15T09:25:00+05:30", 101, 103, 99, 102)
    assert pull_runtime.tick_once(pull_entry)["decision"]["paper_execution"]["status"] == "FILLED"
    assert break_runtime.tick_once(break_signal)["decision"]["signal"] == "WAIT"
    assert break_runtime.tick_once(break_entry)["decision"]["paper_execution"]["status"] == "FILLED"

    assert len(pull_runtime.execution.projection()["positions"]) == 1
    assert len(break_runtime.execution.projection()["positions"]) == 1
    before = {
        name: len(getattr(pull_runtime.workspace, name).read())
        for name in ("journal", "replay", "evidence", "order_ledger", "fill_ledger")
    }
    duplicate = pull_runtime.tick_once(pull_entry)
    assert duplicate["reason"] == "CANDLE_ALREADY_PROCESSED"
    assert before == {
        name: len(getattr(pull_runtime.workspace, name).read()) for name in before
    }

    pull_exit = _context(2, "2026-07-15T09:25:00+05:30", 101, 121, 100, 120)
    break_exit = _context(3, "2026-07-15T09:30:00+05:30", 100, 101, 96, 97)
    assert pull_runtime.tick_once(pull_exit)["decision"]["paper_execution"]["status"] == "FILLED"
    assert break_runtime.tick_once(break_exit)["decision"]["paper_execution"]["status"] == "FILLED"
    assert pull_runtime.execution.projection()["closed_trades"][0]["exit_reason"] == "TARGET"
    assert break_runtime.execution.projection()["closed_trades"][0]["exit_reason"] == "STOP"

    dashboard = service.dashboard()
    assert dashboard["summary"]["completed_paper_trades"] == 2
    assert dashboard["execution"]["closed_trade_count"] == 2
    journal_types = [row["event_type"] for row in dashboard["review"]["journal"]]
    assert journal_types.count("STRATEGY_DECISION") == 4
    assert all(str(row.get("payload", {}).get("signal") or "").upper() != "WAIT" for row in dashboard["review"]["journal"])
    assert journal_types.count("TRADE_CLOSED") == 2
    assert dashboard["review"]["replay"] == []
    assert dashboard["review"]["evidence"] == []
    assert all(item["live_trading_enabled"] is False for item in dashboard["strategies"])


@pytest.mark.integration
def test_native_pipeline_and_open_paper_position_restore_without_reprocessing(tmp_path):
    root = str(tmp_path / "restart")
    adapter = PullbackMasterNativeAdapter(
        engine=PullbackMasterStrategyEngine(PullbackMasterConfig(pullback_mode="V3"))
    )
    adapter.engine.order_blocks.bullish.append(_block(bull=True, top=100, bottom=95, loc=1_000))
    adapter.engine.order_blocks.bearish.append(_block(bull=False, top=125, bottom=120, loc=2_000))
    context = _context(1, "2026-07-15T09:20:00+05:30", 102, 103, 99, 101)

    first_service = StrategyLabService(root)
    first = first_service.deploy(replace(pullback_request(), adapter=adapter, option_resolver=_Resolver()))
    assert first.tick_once(context)["decision"]["paper_execution"]["status"] == "FILLED"
    serialized = first.strategy.serialize()

    restarted_service = StrategyLabService(root)
    restarted = restarted_service.deploy(replace(
        pullback_request(), adapter=PullbackMasterNativeAdapter(), option_resolver=_Resolver()
    ))
    assert restarted.strategy.serialize() == serialized
    assert restarted.execution.projection()["positions"][0]["status"] == "OPEN"
    assert restarted.tick_once(context)["reason"] == "CANDLE_ALREADY_PROCESSED"
    assert len(restarted.workspace.journal.read()) == 1
    assert len(restarted.workspace.replay.read()) == 1
    assert len(restarted.workspace.evidence.read()) == 1
