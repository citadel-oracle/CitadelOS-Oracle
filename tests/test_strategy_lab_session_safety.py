from dataclasses import replace
from copy import deepcopy
from datetime import datetime

import pytest

from src.strategy_lab import StrategyLabService
from src.strategy_lab.core import OrderBlock
from src.strategy_lab.strategies.pullback_master import (
    PullbackMasterConfig,
    PullbackMasterNativeAdapter,
    PullbackMasterStrategyEngine,
    build_deployment_request,
)


def _block(bull, top, bottom, loc):
    return OrderBlock(
        bull=bull, top=top, btm=bottom, avg=(top + bottom) / 2,
        loc=loc, vol=100.0, direction=1 if bull else -1,
    )


def _adapter(config=None):
    engine = PullbackMasterStrategyEngine(
        config or PullbackMasterConfig(pullback_mode="V3", use_supertrend_trail=False)
    )
    engine.order_blocks.bullish.append(_block(True, 100, 95, 1_000))
    engine.order_blocks.bearish.append(_block(False, 125, 120, 2_000))
    return PullbackMasterNativeAdapter(engine=engine)


def _context(candle_id, at, index, *, contract="HELD-CE", held_quote=110.0):
    quotes = [{"ce": {"security_id": "ATM-ROTATED", "ltp": 999.0}}]
    if held_quote is not None:
        quotes.insert(0, {"ce": {"security_id": "HELD-CE", "ltp": held_quote}})
    return {
        "candle_id": candle_id,
        "symbol": "NIFTY_CE",
        "timeframe": "1m",
        "timestamp": at,
        "closed": True,
        "contract": contract,
        "option_contract": contract,
        "paper_price": 100.0 if contract == "HELD-CE" else 999.0,
        "lot_size": 25,
        "chart_contract": {
            "security_id": contract,
            "exchange_segment": "NSE_FNO",
            "underlying": "NIFTY",
            "option_type": "CE",
            "strike": 25_000.0,
            "expiry": "2026-07-23",
            "lot_size": 25,
            "instrument_source": "TEST_MASTER",
            "quote_source": "TEST_QUOTE",
        },
        "argus": {"data": {"atm_window": quotes}},
        "bar": {
            "index": index,
            "timestamp": at,
            "open": 102.0,
            "high": 103.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 100.0,
            "confirmed": True,
        },
    }


def _runtime(tmp_path, adapter=None):
    request = replace(build_deployment_request(), adapter=adapter or _adapter())
    return StrategyLabService(str(tmp_path)).deploy(request)


@pytest.mark.integration
def test_pullback_square_off_uses_held_contract_and_is_exactly_once(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.tick_once(_context("entry", "2026-07-16T09:18:00+05:30", 1))
    position = runtime.execution.projection()["positions"][0]

    square = _context(
        "square", "2026-07-16T15:15:00+05:30", 2,
        contract="ATM-ROTATED", held_quote=110.0,
    )
    result = runtime.tick_once(square)
    assert result["decision"]["exit_reason"] == "SESSION_SQUARE_OFF"
    assert result["decision"]["paper_execution"]["status"] == "FILLED"
    state = runtime.execution.projection()
    order, fill = state["orders"][-1], state["fills"][-1]
    assert order["position_id"] == position["position_id"]
    assert order["contract"] == "HELD-CE"
    assert order["requested_quantity"] == 25
    assert order["option_contract"] == position["option_contract"]
    assert fill["contract"] == "HELD-CE"
    assert fill["price"] == 110.0
    counts = (len(state["orders"]), len(state["fills"]), len(state["closed_trades"]))
    assert runtime.tick_once(square)["reason"] == "CANDLE_ALREADY_PROCESSED"
    state = runtime.execution.projection()
    assert (len(state["orders"]), len(state["fills"]), len(state["closed_trades"])) == counts


@pytest.mark.integration
def test_missing_square_off_quote_fails_closed_is_visible_and_can_retry(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.tick_once(_context("entry", "2026-07-16T09:18:00+05:30", 1))
    missing = runtime.tick_once(_context(
        "missing", "2026-07-16T15:15:00+05:30", 2,
        contract="ATM-ROTATED", held_quote=None,
    ))
    execution = missing["decision"]["paper_execution"]
    assert (execution["status"], execution["reason"]) == (
        "REJECTED", "AUTHORITATIVE_EXIT_PRICE_REQUIRED",
    )
    assert len([row for row in runtime.execution.projection()["positions"] if row["status"] == "OPEN"]) == 1
    assert runtime.strategy.engine.state.position is not None

    retried = runtime.tick_once(_context(
        "retry", "2026-07-16T15:16:00+05:30", 3,
        contract="ATM-ROTATED", held_quote=111.0,
    ))
    assert retried["decision"]["paper_execution"]["status"] == "FILLED"
    assert runtime.execution.projection()["fills"][-1]["price"] == 111.0


@pytest.mark.unit
def test_positional_pullback_is_not_force_closed(tmp_path):
    adapter = _adapter(PullbackMasterConfig(
        trading_mode="Positional",
        pullback_mode="V3",
        use_supertrend_trail=False,
    ))
    runtime = _runtime(tmp_path, adapter)
    runtime.tick_once(_context("entry", "2026-07-16T09:18:00+05:30", 1))
    result = runtime.tick_once(_context(
        "late", "2026-07-16T15:15:00+05:30", 2,
        contract="HELD-CE", held_quote=110.0,
    ))
    assert result["decision"]["signal"] == "WAIT"
    assert len([row for row in runtime.execution.projection()["positions"] if row["status"] == "OPEN"]) == 1


@pytest.mark.integration
def test_stale_position_diagnostic_is_restart_safe_and_same_session_is_clean(tmp_path):
    root = str(tmp_path)
    first = _runtime(root)
    first.tick_once(_context("entry", "2026-07-15T09:18:00+05:30", 1))
    state = deepcopy(first.execution.projection())
    state["positions"][0]["entry_time"] = "2026-07-15T03:48:00+00:00"
    first.execution._commit(state, "TEST_STALE_POSITION", {}, "stale-position-fixture")
    stale = first.status()["diagnostics"]
    assert len(stale) == 1
    assert stale[0]["status"] == "STALE_PREVIOUS_SESSION_POSITION"
    assert stale[0]["contract"] == "HELD-CE"
    assert stale[0]["automatic_square_off_configured"] is True

    restarted = StrategyLabService(root).deploy(
        replace(build_deployment_request(), adapter=_adapter())
    )
    assert restarted.status()["diagnostics"][0]["position_id"] == stale[0]["position_id"]
    closed = restarted.tick_once(_context(
        "restart-square", "2026-07-16T15:15:00+05:30", 2,
        contract="ATM-ROTATED", held_quote=112.0,
    ))
    assert closed["decision"]["paper_execution"]["status"] == "FILLED"
    assert restarted.execution.projection()["fills"][-1]["contract"] == "HELD-CE"

    current = _runtime(tmp_path / "current")
    today = datetime.now().astimezone().date().isoformat()
    current.tick_once(_context("today-entry", f"{today}T09:18:00+05:30", 1))
    assert current.status()["diagnostics"] == []
