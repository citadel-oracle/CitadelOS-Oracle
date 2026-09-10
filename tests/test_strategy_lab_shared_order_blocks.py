from pathlib import Path

import pytest

from src.strategy_lab.core import (
    OrderBlockBar,
    OrderBlockConfig,
    SharedOrderBlockEngine,
)
from src.strategy_lab.strategies.breakout_main import BreakoutMainOrderBlockAdapter
from src.strategy_lab.strategies.pullback_master import PullbackMasterPineEventAdapter


def bar(
    time: int,
    *,
    open: float = 100.0,
    high: float = 110.0,
    low: float = 90.0,
    close: float = 105.0,
    volume: float = 1_000.0,
) -> OrderBlockBar:
    return OrderBlockBar(time=time, open=open, high=high, low=low, close=close, volume=volume)


@pytest.mark.unit
def test_bull_and_bear_creation_unshifts_canonical_state_and_volume():
    engine = SharedOrderBlockEngine()
    bull = engine.create_block(bull=True, boundary=108.0, origin=bar(1, close=105.0))
    bear = engine.create_block(bull=False, boundary=92.0, origin=bar(2, close=95.0))

    assert engine.bullish == [bull]
    assert engine.bearish == [bear]
    assert (bull.top, bull.btm, bull.avg, bull.vol, bull.direction) == (108.0, 90.0, 99.0, 1_000.0, 1)
    assert (bear.top, bear.btm, bear.avg, bear.vol, bear.direction) == (110.0, 92.0, 101.0, 1_000.0, -1)
    assert bull.xloc_bull == bull.xloc_bear == bull.loc == 1
    assert bear.xloc_bull == bear.xloc_bear == bear.loc == 2


@pytest.mark.unit
def test_creation_resets_only_its_side_observation_flags():
    engine = SharedOrderBlockEngine()
    engine.create_block(bull=True, boundary=108.0, origin=bar(1))
    assert engine.observe_latest_states() == ("BULL_NORMAL",)
    engine.create_block(bull=False, boundary=92.0, origin=bar(2))
    assert engine.observe_latest_states() == ("BEAR_NORMAL",)
    engine.create_block(bull=True, boundary=107.0, origin=bar(3))
    assert engine.observe_latest_states() == ("BULL_NORMAL",)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "mitigation_bar"),
    [
        ("Close", bar(2, open=89.0, high=100.0, low=85.0, close=95.0)),
        ("Wick", bar(2, open=96.0, high=100.0, low=89.0, close=97.0)),
        ("Avg", bar(2, open=100.0, high=105.0, low=98.0, close=101.0)),
    ],
)
def test_bull_mitigation_and_breaker_lifecycle(method, mitigation_bar):
    engine = SharedOrderBlockEngine(OrderBlockConfig(mitigation_method=method, show_breakers=True))
    block = engine.create_block(bull=True, boundary=110.0, origin=bar(1))
    engine.mitigate(mitigation_bar, confirmed=False)
    assert block.is_breaker is False
    engine.mitigate(mitigation_bar, confirmed=True)
    assert block.is_breaker is True
    assert block.breaker_location == 2

    if method == "Close":
        removal = bar(3, open=111.0, high=113.0, low=105.0, close=109.0)
    elif method == "Wick":
        removal = bar(3, open=105.0, high=111.0, low=104.0, close=106.0)
    else:
        removal = bar(3, open=100.0, high=101.0, low=99.0, close=100.0)
    engine.mitigate(removal, confirmed=True)
    assert engine.bullish == []


@pytest.mark.unit
def test_bear_mitigation_is_directionally_symmetric_and_strict():
    engine = SharedOrderBlockEngine(OrderBlockConfig(mitigation_method="Close", show_breakers=True))
    block = engine.create_block(bull=False, boundary=90.0, origin=bar(1))
    engine.mitigate(bar(2, open=110.0, high=110.0, low=100.0, close=109.0), confirmed=True)
    assert block.is_breaker is False
    engine.mitigate(bar(3, open=111.0, high=112.0, low=100.0, close=109.0), confirmed=True)
    assert block.is_breaker is True
    engine.mitigate(bar(4, open=89.0, high=95.0, low=88.0, close=90.0), confirmed=True)
    assert engine.bearish == []


@pytest.mark.unit
def test_hidden_breaker_is_removed_immediately():
    engine = SharedOrderBlockEngine(OrderBlockConfig(show_breakers=False))
    engine.create_block(bull=True, boundary=110.0, origin=bar(1))
    engine.mitigate(bar(2, open=89.0, high=100.0, low=85.0, close=95.0), confirmed=True)
    assert engine.bullish == []


@pytest.mark.unit
def test_same_side_overlap_preserves_configured_generation():
    recent = SharedOrderBlockEngine(OrderBlockConfig(overlap_preference="Recent"))
    old = recent.create_block(bull=True, boundary=105.0, origin=bar(1, low=95.0))
    new = recent.create_block(bull=True, boundary=110.0, origin=bar(2, low=100.0))
    recent.remove_overlaps()
    assert recent.bullish == [new]
    assert old not in recent.bullish

    previous = SharedOrderBlockEngine(OrderBlockConfig(overlap_preference="Previous"))
    old = previous.create_block(bull=True, boundary=105.0, origin=bar(1, low=95.0))
    previous.create_block(bull=True, boundary=110.0, origin=bar(2, low=100.0))
    previous.remove_overlaps()
    assert previous.bullish == [old]


@pytest.mark.unit
def test_cross_side_overlap_uses_canonical_bull_then_bear_precedence():
    engine = SharedOrderBlockEngine(OrderBlockConfig(overlap_preference="Recent"))
    engine.create_block(bull=True, boundary=105.0, origin=bar(1, low=95.0))
    bear = engine.create_block(bull=False, boundary=100.0, origin=bar(2, high=110.0))
    engine.remove_overlaps()
    assert engine.bullish == []
    assert engine.bearish == [bear]


@pytest.mark.unit
def test_activity_tracking_matches_three_step_direction_cycle():
    engine = SharedOrderBlockEngine()
    block = engine.create_block(bull=True, boundary=108.0, origin=bar(1_000, close=105.0))
    engine.update_activity(1_300, 1_200, 1_100)
    assert (block.move, block.bull_position, block.bear_position, block.xloc_bull) == (2, 2, 1, 1_200)
    engine.update_activity(1_400, 1_300, 1_200)
    assert (block.move, block.bull_position, block.bear_position) == (3, 3, 1)
    engine.update_activity(1_500, 1_400, 1_300)
    assert (block.move, block.bull_position, block.bear_position, block.xloc_bear) == (1, 3, 2, 1_200)


@pytest.mark.unit
def test_serialization_is_deterministic_and_preserves_array_order(tmp_path: Path):
    engine = SharedOrderBlockEngine(OrderBlockConfig(show_breakers=True))
    engine.create_block(bull=True, boundary=107.0, origin=bar(1))
    newest = engine.create_block(bull=True, boundary=108.0, origin=bar(2))
    engine.create_block(bull=False, boundary=92.0, origin=bar(3))
    engine.observe_latest_states()
    engine.update_activity(500, 400, 300)

    first = engine.serialize()
    assert first == engine.serialize()
    restored = SharedOrderBlockEngine.deserialize(first)
    assert restored.serialize() == first
    assert restored.bullish[0].loc == newest.loc

    path = tmp_path / "order_blocks.json"
    engine.save(path)
    assert SharedOrderBlockEngine.load(path).serialize() == first


@pytest.mark.unit
def test_both_strategies_use_the_exact_shared_engine_type():
    assert PullbackMasterPineEventAdapter.order_block_engine_type is SharedOrderBlockEngine
    assert BreakoutMainOrderBlockAdapter.order_block_engine_type is SharedOrderBlockEngine
    assert type(PullbackMasterPineEventAdapter.build_order_block_engine()) is SharedOrderBlockEngine
    assert type(BreakoutMainOrderBlockAdapter.build_order_block_engine()) is SharedOrderBlockEngine


@pytest.mark.safety
def test_shared_engine_wiring_does_not_change_pullback_adapter_output():
    result = PullbackMasterPineEventAdapter().evaluate({"closed": True})
    assert result["signal"] == "WAIT"
    assert result["reason"] == "AUTHORITATIVE_PINE_EVENT_REQUIRED"
    assert "order_block" not in result
