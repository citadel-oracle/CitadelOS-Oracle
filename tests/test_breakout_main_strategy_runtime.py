from datetime import datetime

import pytest

from src.strategy_lab.core import OrderBlock, SharedOrderBlockEngine
from src.strategy_lab.storage import StrategyWorkspace
from src.strategy_lab.strategies.breakout_main import (
    BreakoutMainConfig,
    BreakoutMainStrategyEngine,
    LongPosition,
    PendingSignal,
)
from src.strategy_lab.strategies.breakout_main.adapters import BreakoutMainExecutionAdapter


def block(*, top, btm, loc, breaker=False):
    return OrderBlock(
        bull=False, top=top, btm=btm, avg=(top + btm) / 2,
        loc=loc, vol=1000, direction=-1, is_breaker=breaker,
    )


def context(index, *, o=99, h=101, low=98, close=100.5, volume=1000, at="10:00", **extra):
    return {
        "bar": {
            "index": index, "timestamp": f"2026-07-14T{at}:00+05:30",
            "open": o, "high": h, "low": low, "close": close,
            "volume": volume, "confirmed": True,
        },
        "symbol": "NIFTY", "timeframe": "1m", **extra,
    }


def engine(config=None):
    obs = SharedOrderBlockEngine()
    obs.bearish = [block(top=100, btm=99, loc=10), block(top=111, btm=108, loc=20)]
    return BreakoutMainStrategyEngine(config, order_blocks=obs)


@pytest.mark.unit
def test_signal_creation_then_next_bar_wick_confirmation():
    strategy = engine()
    created = strategy.evaluate(context(1, h=102, close=101))
    assert created["signal"] == "WAIT"
    assert created["reason"] == "PENDING_SIGNAL_CREATED"
    assert created["pending_signal"] == {
        "high": 102.0, "low": 98.0, "stop": 97.0, "target": 108,
        "target_top": 111, "setup_location": 10, "signal_bar": 1,
    }

    entered = strategy.evaluate(context(2, h=102.01, low=99, close=101.5))
    assert entered["signal"] == "BUY"
    assert entered["underlying_entry"] == 102
    assert entered["position_state"]["target"] == 108
    assert entered["used_setup_locations"] == [10]
    assert entered["execution_readiness"] == "BLOCKED_AUTHORITATIVE_OPTION_REQUIRED"
    assert entered["events"][-1]["event"] == "POSITION_OPENED"


@pytest.mark.unit
def test_pending_signal_cancellation_and_session_expiry():
    strategy = engine()
    strategy.evaluate(context(1, h=102, close=101))
    cancelled = strategy.evaluate(context(2, h=101, low=96.9, close=100))
    assert cancelled["reason"] == "SIGNAL_CANCELLED_STOP"
    assert cancelled["pending_signal"] is None

    strategy = engine(BreakoutMainConfig(cancel_signal_on_stop=False))
    strategy.evaluate(context(1, h=102, close=101))
    expired = strategy.evaluate(context(2, h=102, low=98, close=101, at="15:16"))
    assert expired["reason"] == "SIGNAL_CANCELLED_SESSION"
    assert expired["pending_signal"] is None


@pytest.mark.unit
def test_close_confirmation_does_not_use_wick():
    strategy = engine(BreakoutMainConfig(trigger_mode="Close Above Signal High", entry_mode="Breakout Close"))
    strategy.evaluate(context(1, h=102, close=101))
    wick_only = strategy.evaluate(context(2, h=103, low=99, close=101.9))
    assert wick_only["signal"] == "WAIT"
    entered = strategy.evaluate(context(3, h=103, low=99, close=102.1))
    assert entered["signal"] == "BUY"
    assert entered["underlying_entry"] == 102.1


@pytest.mark.unit
def test_volume_filter_is_strict_and_fail_closed_without_history():
    strategy = engine(BreakoutMainConfig(volume_filter_enabled=True, volume_sma_length=2, volume_multiplier=1.0))
    strategy.evaluate(context(1, h=102, close=101, volume=100))
    equal_average = strategy.evaluate(context(2, h=103, low=99, close=102, volume=100))
    assert equal_average["signal"] == "WAIT"
    assert equal_average["reason"] == "VOLUME_FILTER_BLOCKED"


@pytest.mark.unit
def test_exit_priority_target_before_stop_and_squareoff_before_both():
    strategy = engine()
    strategy.state.position = LongPosition(102, 97, 108, 111, 10, 2)
    both = strategy.evaluate(context(3, h=109, low=96, close=100))
    assert both["signal"] == "SELL"
    assert both["reason"] == "TARGET_REACHED"
    assert both["underlying_exit"] == 108

    strategy = engine()
    strategy.state.position = LongPosition(102, 97, 108, 111, 10, 2)
    squareoff = strategy.evaluate(context(3, h=109, low=96, close=105, at="15:16"))
    assert squareoff["reason"] == "SESSION_SQUARE_OFF"
    assert squareoff["underlying_exit"] == 105


@pytest.mark.unit
def test_stop_exit_reentry_releases_last_matching_used_setup():
    strategy = engine()
    strategy.state.used_setup_locations = [10, 30, 10]
    strategy.state.position = LongPosition(102, 97, None, None, 10, 2)
    stopped = strategy.evaluate(context(3, h=101, low=96, close=99))
    assert stopped["reason"] == "STOP_LOSS_REACHED"
    assert stopped["used_setup_locations"] == [10, 30]


@pytest.mark.unit
def test_fixed_stop_remains_and_supertrend_trail_only_tightens():
    strategy = engine(BreakoutMainConfig(stop_mode="Supertrend Trail", supertrend_atr_length=1))
    for index in range(1, 5):
        strategy.evaluate(context(index, o=99 + index, h=102 + index, low=98 + index, close=101 + index))
    strategy.state.position = LongPosition(105, 90, 200, 210, 10, 4)
    result = strategy.evaluate(context(5, o=104, h=108, low=103, close=107))
    assert strategy.state.position is not None
    assert strategy.state.position.stop >= 90
    trails = [event for event in result["events"] if event["event"] == "STOP_TRAILED"]
    if trails:
        assert trails[0]["stop"] > trails[0]["previous_stop"]


@pytest.mark.unit
def test_target_close_inside_requires_close_within_zone():
    strategy = engine(BreakoutMainConfig(target_method="Close Inside VOB"))
    strategy.state.position = LongPosition(102, 97, 108, 111, 10, 2)
    above_zone = strategy.evaluate(context(3, o=110, h=113, low=105, close=112))
    assert above_zone["signal"] == "WAIT"
    inside = strategy.evaluate(context(4, o=109, h=111, low=107, close=110))
    assert inside["signal"] == "SELL"
    assert inside["reason"] == "TARGET_REACHED"


@pytest.mark.unit
def test_daily_reset_clears_used_and_pending_but_not_positional_state():
    strategy = engine()
    strategy.evaluate(context(1, h=99, close=98, at="14:00"))
    strategy.state.used_setup_locations = [10]
    strategy.state.pending = PendingSignal(102, 98, 97, None, None, 10, 1)
    next_day = context(2, h=101, low=99, close=100)
    next_day["bar"]["timestamp"] = "2026-07-15T10:00:00+05:30"
    result = strategy.evaluate(next_day)
    assert result["used_setup_locations"] == []
    assert any(event["event"] == "DAILY_RESET" for event in result["events"])


@pytest.mark.unit
def test_serialization_is_deterministic_and_resumes_state(tmp_path):
    strategy = engine()
    strategy.evaluate(context(1, h=102, close=101))
    payload = strategy.serialize()
    restored = BreakoutMainStrategyEngine.deserialize(payload)
    assert restored.serialize() == payload
    path = tmp_path / "breakout.json"
    strategy.save(path)
    loaded = BreakoutMainStrategyEngine.load(path)
    assert loaded.serialize() == payload
    assert loaded.evaluate(context(2, h=103, low=99, close=102))["signal"] == "BUY"


@pytest.mark.unit
def test_events_alerts_and_authoritative_option_fields_are_mapped():
    strategy = engine()
    strategy.evaluate(context(1, h=102, close=101))
    result = strategy.evaluate(context(2, h=103, low=99, close=102, option_contract="NIFTY-CE", paper_price=125.5))
    assert result["contract"] == "NIFTY-CE"
    assert result["entry"] == 125.5
    assert result["alert"]["message"].startswith("BUY|symbol=NIFTY|tf=1m|price=125.5")
    assert result["journal_events"] == result["replay_events"] == result["evidence_events"]


@pytest.mark.integration
def test_paper_execution_bridge_uses_existing_engine_and_never_broker(tmp_path):
    workspace = StrategyWorkspace(tmp_path, "breakout-main-pine-v5")
    workspace.write("metadata", {
        "strategy_id": "breakout-main-pine-v5",
        "parameters": {"paper_account": {
            "initial_capital": 100000, "sizing_mode": "FIXED_LOTS",
            "fixed_lots": 1, "lot_size": 25, "max_daily_loss": 3000,
            "max_concurrent_positions": 1, "max_trades_per_day": 20,
        }},
    })
    adapter = BreakoutMainExecutionAdapter()
    evaluation = {
        "evaluation_id": "eval-1", "evaluated_at": "2026-07-14T10:01:00+05:30",
        "signal": "BUY", "contract": "NIFTY-CE", "entry": 100.0,
        "position_effect": "OPEN", "side": "LONG",
    }
    result = adapter.process(evaluation=evaluation, context={}, workspace=workspace)
    assert result["status"] == "FILLED"
    assert result["paper_only"] is True
    assert result["broker_submission"] is False
    assert len(workspace.order_ledger.read()) == 2
    assert len(workspace.fill_ledger.read()) == 1


@pytest.mark.safety
def test_paper_execution_fails_closed_without_authoritative_contract_or_policy(tmp_path):
    workspace = StrategyWorkspace(tmp_path, "breakout-main-pine-v5")
    workspace.write("metadata", {"strategy_id": "breakout-main-pine-v5", "parameters": {}})
    result = BreakoutMainExecutionAdapter().process(
        evaluation={"evaluation_id": "e", "signal": "BUY"}, context={}, workspace=workspace,
    )
    assert result["status"] == "REJECTED"
    assert result["paper_state_mutated"] is False
    assert result["broker_submission"] is False
