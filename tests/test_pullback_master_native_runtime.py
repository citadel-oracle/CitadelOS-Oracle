import pytest

from src.strategy_lab.core import (
    FairValueGap,
    FairValueGapEngine,
    OrderBlock,
    SharedOrderBlockEngine,
)
from src.strategy_lab.strategies.pullback_master import (
    PullbackMasterConfig,
    PullbackMasterNativeAdapter,
    PullbackMasterStrategyEngine,
    build_deployment_request,
)


def _block(*, bull: bool, top: float, bottom: float, location: int, volume: float = 100.0) -> OrderBlock:
    return OrderBlock(
        bull=bull, top=top, btm=bottom, avg=(top + bottom) / 2,
        loc=location, vol=volume, direction=1 if bull else -1,
    )


def _bar(index: int, at: str, open_: float, high: float, low: float, close: float, volume: float = 100.0):
    return {"bar": {"index": index, "timestamp": at, "open": open_, "high": high,
                    "low": low, "close": close, "volume": volume, "confirmed": True}}


def _engine(config: PullbackMasterConfig | None = None) -> PullbackMasterStrategyEngine:
    blocks = SharedOrderBlockEngine()
    blocks.bullish.append(_block(bull=True, top=100.0, bottom=95.0, location=1_000))
    blocks.bearish.append(_block(bull=False, top=125.0, bottom=120.0, location=2_000))
    return PullbackMasterStrategyEngine(config, order_blocks=blocks)


@pytest.mark.unit
def test_native_adapter_fails_closed_without_bar_and_never_enables_execution():
    result = PullbackMasterNativeAdapter().evaluate({})
    assert result == {
        "status": "NOT_IMPLEMENTED", "reason": "MARKET_CONTEXT_REQUIRED", "signal": "WAIT",
        "paper_only": True, "paper_execution_enabled": False,
        "broker_submission": False, "live_trading_enabled": False,
    }


@pytest.mark.unit
def test_pullback_touch_opens_long_with_ob_stop_and_bearish_ob_target():
    engine = _engine(PullbackMasterConfig(pullback_mode="V3"))
    result = engine.evaluate(_bar(1, "2026-07-14T09:18:00+05:30", 102, 103, 99, 101))
    assert result["signal"] == "BUY"
    assert result["underlying_entry"] == 100.0
    assert result["underlying_stop"] == 95.0
    assert result["underlying_target"] == 120.0
    assert result["position_state"]["ob_location"] == 1_000
    assert result["execution_readiness"] == "BLOCKED_AUTHORITATIVE_OPTION_REQUIRED"
    assert result["paper_execution_enabled"] is False


@pytest.mark.unit
def test_target_precedes_stop_when_both_are_touched_on_same_bar():
    engine = _engine(PullbackMasterConfig(pullback_mode="V3", use_supertrend_trail=False))
    engine.evaluate(_bar(1, "2026-07-14T09:18:00+05:30", 102, 103, 99, 101))
    result = engine.evaluate(_bar(2, "2026-07-14T09:21:00+05:30", 101, 121, 94, 100))
    assert result["signal"] == "SELL"
    assert result["exit_reason"] == "TARGET"
    assert result["underlying_exit"] == 120.0


@pytest.mark.unit
def test_initial_wick_stop_is_strict_below_and_same_bar_reentry_is_blocked():
    engine = _engine(PullbackMasterConfig(pullback_mode="V3", use_supertrend_trail=False))
    engine.evaluate(_bar(1, "2026-07-14T09:18:00+05:30", 102, 103, 99, 101))
    equal = engine.evaluate(_bar(2, "2026-07-14T09:21:00+05:30", 99, 101, 95, 99))
    assert equal["signal"] == "WAIT"
    stopped = engine.evaluate(_bar(3, "2026-07-14T09:24:00+05:30", 99, 100, 94.95, 96))
    assert stopped["signal"] == "SELL"
    assert stopped["exit_reason"] == "STOP"
    assert stopped["position_state"] is None


@pytest.mark.unit
def test_v4_midday_entry_filter_and_afternoon_permission_match_profile():
    midday = _engine()
    blocked = midday.evaluate(_bar(1, "2026-07-14T12:30:00+05:30", 102, 103, 99, 101))
    assert blocked["signal"] == "WAIT"
    assert blocked["shared_core"]["session_allowed"] is False

    afternoon = _engine()
    allowed = afternoon.evaluate(_bar(1, "2026-07-14T14:03:00+05:30", 102, 103, 99, 101))
    assert allowed["signal"] == "BUY"
    assert allowed["shared_core"]["session_allowed"] is True


@pytest.mark.unit
def test_bearish_fvg_supply_target_is_selected_and_has_exit_priority():
    fvg = FairValueGapEngine()
    fvg.bearish.append(FairValueGap(bull=False, top=119.0, btm=116.0, loc=3_000))
    engine = _engine(PullbackMasterConfig(pullback_mode="V3", use_supertrend_trail=False))
    engine.fair_value_gaps = fvg
    engine.evaluate(_bar(1, "2026-07-14T09:18:00+05:30", 102, 103, 99, 101))
    assignment = engine.evaluate(_bar(2, "2026-07-14T09:21:00+05:30", 101, 110, 100, 109))
    assert assignment["position_state"]["bear_fvg_target"] == 116.0
    result = engine.evaluate(_bar(3, "2026-07-14T09:24:00+05:30", 109, 116, 108, 115))
    assert result["signal"] == "SELL"
    assert result["underlying_exit"] == 116.0
    assert result["exit_reason"] == "TARGET"


@pytest.mark.unit
def test_new_upper_bullish_ob_changes_stop_to_close_confirmed_semantics():
    engine = _engine(PullbackMasterConfig(pullback_mode="V3", use_supertrend_trail=False))
    engine.evaluate(_bar(1, "2026-07-14T09:18:00+05:30", 102, 103, 99, 101))
    engine.order_blocks.bullish.insert(0, _block(bull=True, top=108, bottom=105, location=2_000_000_000_000))
    trailed = engine.evaluate(_bar(2, "2026-07-14T09:21:00+05:30", 108, 111, 107, 110))
    assert trailed["position_state"]["stop"] == 105.0
    wick_only = engine.evaluate(_bar(3, "2026-07-14T09:24:00+05:30", 108, 109, 104, 106))
    assert wick_only["signal"] == "WAIT"
    closed_below = engine.evaluate(_bar(4, "2026-07-14T09:27:00+05:30", 106, 107, 103, 104))
    assert closed_below["signal"] == "SELL"
    assert closed_below["exit_reason"] == "STOP"


@pytest.mark.unit
def test_state_round_trip_is_deterministic_and_preserves_shared_core():
    engine = _engine(PullbackMasterConfig(pullback_mode="V3", use_supertrend_trail=False))
    engine.evaluate(_bar(1, "2026-07-14T09:18:00+05:30", 102, 103, 99, 101))
    payload = engine.serialize()
    restored = PullbackMasterStrategyEngine.deserialize(payload)
    assert restored.serialize() == payload
    expected = engine.evaluate(_bar(2, "2026-07-14T09:21:00+05:30", 101, 105, 100, 104))
    actual = restored.evaluate(_bar(2, "2026-07-14T09:21:00+05:30", 101, 105, 100, 104))
    assert actual == expected


@pytest.mark.integration
def test_deployment_uses_native_adapter_and_is_paper_active_only():
    request = build_deployment_request()
    assert isinstance(request.adapter, PullbackMasterNativeAdapter)
    assert request.activation_enabled is True
    assert request.execution is None
    result = request.adapter.evaluate(_bar(1, "2026-07-14T09:18:00+05:30", 100, 101, 99, 100))
    assert result["signal"] == "WAIT"
    assert result["paper_execution_enabled"] is False
    assert result["live_trading_enabled"] is False
