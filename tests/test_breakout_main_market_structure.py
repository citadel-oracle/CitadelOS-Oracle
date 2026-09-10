import pytest

from src.strategy_lab.strategies.breakout_main import (
    MarketStructureConfig,
    MarketStructureEngine,
    StructureState,
)


def candle(index, *, open=10.0, high=11.0, low=9.0, close=10.0):
    return {"bar_index": index, "open": open, "high": high, "low": low, "close": close}


def engine(**values):
    return MarketStructureEngine({"window_enabled": False, "pivot_length": 2, **values})


@pytest.mark.unit
def test_configuration_defaults_and_validation():
    config = MarketStructureConfig.from_mapping()
    assert config.window_bars == 5000
    assert config.algorithmic_logic == "Adjusted Points"
    assert config.pivot_length == 5
    assert config.build_sweeps is True
    with pytest.raises(ValueError):
        MarketStructureConfig.from_mapping({"pivot_length": 1})
    with pytest.raises(ValueError):
        MarketStructureConfig.from_mapping({"max_bars_back": 4999})


@pytest.mark.unit
def test_bootstrap_initializes_persistent_state_and_sweep_precedes_equal_break():
    subject = engine()
    first = subject.update(candle(0))
    assert first["state"]["start"] == 1
    assert first["state"]["bos"] == 11.0
    assert first["state"]["choch"] == 9.0
    assert first["state"]["dnsweep"] is True
    second = subject.update(candle(1, open=10, high=12, low=9.5, close=11))
    assert second["state"]["start"] == 1
    assert second["state"]["upsweep"] is True
    assert second["state"]["bos"] == 12.0
    assert second["events"] == []


@pytest.mark.unit
def test_bootstrap_transitions_and_active_state_runs_on_same_bar():
    bullish = engine(build_sweeps=False)
    bullish.update(candle(0))
    result = bullish.update(candle(1, open=10, high=12, low=9.5, close=11))
    assert result["state"]["start"] == 2
    assert result["state"]["trend"] == 1
    assert result["state"]["main"] == 12.0
    assert result["state"]["temp"] == 1
    assert result["events"][-1]["event"] == "CHoCH"
    assert result["events"][-1]["direction"] == "BULLISH"

    bearish = engine(build_sweeps=False)
    bearish.update(candle(0))
    result = bearish.update(candle(1, open=10, high=10.5, low=8, close=9))
    assert result["state"]["trend"] == -1
    assert result["state"]["main"] == 8.0


@pytest.mark.unit
def test_bearish_and_bullish_bos_transitions():
    bearish = engine(build_sweeps=False)
    bearish.process_bars([candle(i, high=11 + i * 0.1, low=9, close=10) for i in range(5)])
    bearish.state = StructureState(bos=8, choch=15, loc=1, temp=4, trend=-1, start=2, main=7, xloc=1)
    result = bearish.update(candle(5, open=9, high=10, low=7, close=7.5))
    assert result["events"][-1]["event"] == "BOS"
    assert result["events"][-1]["direction"] == "BEARISH"
    assert result["state"]["bos"] is None

    bullish = engine(build_sweeps=False)
    bullish.process_bars([candle(i, high=11, low=7 + i * 0.1, close=10) for i in range(5)])
    bullish.state = StructureState(bos=12, choch=5, loc=1, temp=4, trend=1, start=2, main=13, xloc=1)
    result = bullish.update(candle(5, open=11, high=13, low=9, close=12.5))
    assert result["events"][-1]["event"] == "BOS"
    assert result["events"][-1]["direction"] == "BULLISH"
    assert result["state"]["bos"] is None


@pytest.mark.unit
def test_choch_reverses_trend_and_preserves_existing_bos_as_next_level():
    subject = engine(build_sweeps=False)
    subject.process_bars([candle(i) for i in range(3)])
    subject.state = StructureState(bos=8, choch=12, loc=0, temp=2, trend=-1, start=2, main=8, xloc=0)
    result = subject.update(candle(3, open=11, high=13, low=10, close=13))
    assert result["state"]["trend"] == 1
    assert result["state"]["choch"] == 8
    assert result["events"][-1]["direction"] == "BULLISH"

    subject.state = StructureState(bos=12, choch=8, loc=0, temp=3, trend=1, start=2, main=13, xloc=0)
    result = subject.update(candle(4, open=9, high=10, low=7, close=7))
    assert result["state"]["trend"] == -1
    assert result["state"]["choch"] == 12
    assert result["events"][-1]["direction"] == "BEARISH"


@pytest.mark.unit
def test_active_sweep_precedence_is_inclusive_and_emits_no_bos():
    subject = engine()
    subject.process_bars([candle(i) for i in range(3)])
    subject.state = StructureState(bos=8, choch=12, loc=0, temp=2, trend=-1, start=2, main=7, xloc=0)
    before = len(subject.events)
    result = subject.update(candle(3, open=8, high=9, low=7, close=8))
    assert len(subject.events) == before
    assert result["state"]["dnsweep"] is True
    assert result["state"]["bos"] == 7


@pytest.mark.unit
def test_pivot_confirmation_unshift_and_strict_invalidation():
    subject = engine()
    highs = [11, 12, 15, 12, 11]
    for index, high in enumerate(highs):
        subject.update(candle(index, open=10, high=high, low=9, close=10))
    assert subject.phn[0] == 2
    assert subject.php[0] == 15
    subject.update(candle(5, open=14, high=15, low=9, close=14))
    assert subject.php[0] == 15
    subject.update(candle(6, open=15, high=16, low=9, close=15))
    assert subject.php == []
    assert subject.phn == []


@pytest.mark.unit
def test_find_uses_historical_offsets_and_oldest_equal_extreme():
    subject = engine(build_sweeps=False)
    highs = [5, 10, 8, 10, 7]
    for index, high in enumerate(highs):
        subject.update(candle(index, open=4, high=high, low=3, close=4))
    subject.state.loc = 0
    assert subject.find(True) == 3
    assert subject.snapshot()["history"][-1 - subject.find(True)]["index"] == 1


@pytest.mark.unit
def test_adjusted_point_updates_choch_only_on_literal_cadence():
    subject = engine(build_sweeps=False)
    history = [candle(i, high=11, low=6, close=10) for i in range(5)]
    history.append(candle(5, high=13, low=6, close=10))
    subject.process_bars(history)
    subject.state = StructureState(bos=7, choch=15, loc=0, temp=5, trend=-1, start=2, main=6, xloc=0)
    subject.php = [12]
    subject.phn = [2]
    result = subject.update(candle(6, open=10, high=11, low=6.5, close=10))
    assert result["state"]["choch"] == 12
    assert result["state"]["loc"] == 2


@pytest.mark.unit
def test_window_mode_retains_history_but_starts_state_at_strict_boundary():
    subject = MarketStructureEngine({"window_enabled": True, "window_bars": 1000, "pivot_length": 2})
    results = subject.process_bars([candle(i) for i in range(1002)])
    assert results[0]["processed"] is False
    assert results[1]["processed"] is False
    assert results[2]["processed"] is True
    assert subject.state.zn == 2
    assert len(subject.snapshot()["history"]) == 1002


@pytest.mark.unit
def test_serialization_restores_pine_var_state_and_history(tmp_path):
    subject = engine(build_sweeps=False)
    subject.process_bars([candle(0), candle(1, open=10, high=12, low=9.5, close=11)])
    path = tmp_path / "structure.json"
    subject.save(path)
    restored = MarketStructureEngine.load(path)
    assert restored.snapshot() == subject.snapshot()
    assert restored.update(candle(2))["status"] == "MARKET_STRUCTURE_COMPLETE"


@pytest.mark.unit
def test_regression_rejects_noncontiguous_and_invalid_bars():
    subject = engine()
    subject.update(candle(0))
    with pytest.raises(ValueError, match="contiguous"):
        subject.update(candle(2))
    with pytest.raises(ValueError, match="high"):
        engine().update(candle(0, open=10, high=9, low=8, close=10))
