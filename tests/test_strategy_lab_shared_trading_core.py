from datetime import datetime

import pytest

from src.strategy_lab.core import (
    FairValueGap,
    FairValueGapBar,
    FairValueGapConfig,
    FairValueGapEngine,
    LiquidityBar,
    LiquidityZone,
    LiquidityZoneConfig,
    LiquidityZoneEngine,
    SHARED_TRADING_CORE_TYPES,
    SessionConfig,
    SharedRiskEngine,
    SharedRiskPolicy,
    SharedSessionManager,
    SupertrendEngine,
    VolumeFilter,
    VWAPEngine,
)
from src.strategy_lab.core.atr import TradingViewATR
from src.strategy_lab.strategies.breakout_main import BreakoutMainOrderBlockAdapter
from src.strategy_lab.strategies.breakout_main.adapters import BreakoutMainSignalEngine
from src.strategy_lab.strategies.pullback_master import PullbackMasterPineEventAdapter


def fvg_bar(index, *, open=100.0, high=105.0, low=95.0, close=100.0):
    return FairValueGapBar(index, index * 300, open, high, low, close, 1_000.0)


def liquidity_bar(index, high, low, close, volume):
    return LiquidityBar(index, index * 60, close, high, low, close, volume)


@pytest.mark.unit
def test_tradingview_atr_uses_sma_seed_then_rma():
    atr = TradingViewATR(2)
    assert atr.update(10, 8, 9) is None
    assert atr.update(12, 9, 11) == pytest.approx(2.5)
    assert atr.update(14, 10, 13) == pytest.approx(3.25)
    assert TradingViewATR.restore(atr.snapshot()).snapshot() == atr.snapshot()


@pytest.mark.unit
def test_volume_filter_is_stateless_strict_and_fail_closed_on_missing_history():
    missing = VolumeFilter.evaluate([100], length=2, multiplier=1.0)
    equal = VolumeFilter.evaluate([100, 100], length=2, multiplier=1.0)
    above = VolumeFilter.evaluate([100, 101], length=2, multiplier=0.9)
    disabled = VolumeFilter.evaluate([], length=2, multiplier=1.0, enabled=False)
    assert missing.confirmed is False
    assert equal.confirmed is False
    assert above.confirmed is True
    assert disabled.confirmed is True


@pytest.mark.unit
def test_vwap_uses_hlc3_volume_weighting_and_daily_reset(tmp_path):
    engine = VWAPEngine()
    first = engine.update(
        timestamp=datetime(2026, 7, 14, 9, 15), high=101, low=99, close=100, volume=10
    )
    second = engine.update(
        timestamp=datetime(2026, 7, 14, 9, 16), high=111, low=109, close=110, volume=30
    )
    reset = engine.update(
        timestamp=datetime(2026, 7, 15, 9, 15), high=91, low=89, close=90, volume=20
    )
    assert first.value == 100 and first.reset is True
    assert second.value == pytest.approx(107.5) and second.reset is False
    assert reset.value == 90 and reset.reset is True
    path = tmp_path / "vwap.json"
    engine.save(path)
    assert VWAPEngine.load(path).serialize() == engine.serialize()


@pytest.mark.unit
def test_vwap_zero_volume_is_truthfully_unavailable():
    point = VWAPEngine().update(
        timestamp=datetime(2026, 7, 14, 9, 15), high=101, low=99, close=100, volume=0
    )
    assert point.value is None


@pytest.mark.unit
def test_supertrend_matches_atr_band_and_direction_switching(tmp_path):
    engine = SupertrendEngine(factor=1.0, atr_length=2)
    assert engine.update(high=10, low=8, close=9).value is None
    seeded = engine.update(high=11, low=9, close=10)
    switched = engine.update(high=14, low=11, close=13)
    assert (seeded.atr, seeded.direction, seeded.value) == (2.0, 1, 12.0)
    assert switched.atr == pytest.approx(3.0)
    assert switched.direction == -1
    assert switched.value == pytest.approx(9.5)
    path = tmp_path / "supertrend.json"
    engine.save(path)
    assert SupertrendEngine.load(path).serialize() == engine.serialize()


@pytest.mark.unit
def test_fvg_creation_is_delayed_one_bar_and_tracks_raid():
    engine = FairValueGapEngine(
        FairValueGapConfig(atr_length=1, track_raids=True, hide_overlap=False)
    )
    assert engine.update(fvg_bar(0, high=100, low=90, close=95)).created == ()
    assert engine.update(fvg_bar(1, high=105, low=95, close=104)).created == ()
    assert engine.update(fvg_bar(2, open=102, high=106, low=101, close=103)).created == ()
    update = engine.update(fvg_bar(3, open=102, high=104, low=100.5, close=102))
    assert update.created == ("BULLISH",)
    gap = engine.bullish[0]
    assert (gap.top, gap.btm, gap.loc) == (101, 100, 0)
    assert gap.is_raid is True
    assert gap.raid_price == 100.5


@pytest.mark.unit
def test_bearish_fvg_creation_uses_mirrored_three_bar_boundaries():
    engine = FairValueGapEngine(FairValueGapConfig(atr_length=1, hide_overlap=False))
    engine.update(fvg_bar(0, open=105, high=110, low=100, close=105))
    engine.update(fvg_bar(1, open=100, high=105, low=95, close=96))
    engine.update(fvg_bar(2, open=98, high=99, low=94, close=97))
    update = engine.update(fvg_bar(3, open=97, high=99.5, low=95, close=98))
    assert update.created == ("BEARISH",)
    assert (engine.bearish[0].top, engine.bearish[0].btm, engine.bearish[0].loc) == (100, 99, 0)


@pytest.mark.unit
def test_fvg_missing_history_and_unseeded_atr_create_nothing():
    engine = FairValueGapEngine(FairValueGapConfig(atr_length=5))
    engine.process_bars([fvg_bar(0), fvg_bar(1), fvg_bar(2), fvg_bar(3)])
    assert engine.bullish == engine.bearish == []


@pytest.mark.unit
def test_fvg_mitigation_breaker_and_inclusive_edge_semantics():
    engine = FairValueGapEngine(
        FairValueGapConfig(mode="Breakers", mitigation_method="Close", atr_length=1)
    )
    gap = FairValueGap(True, 110, 100, 1)
    engine.bullish.append(gap)
    engine.update(fvg_bar(0, open=100, high=105, low=99, close=101))
    assert gap.is_breaker is False
    engine.update(fvg_bar(1, open=99, high=105, low=98, close=101))
    assert gap.is_breaker is True
    engine.update(fvg_bar(2, open=111, high=112, low=105, close=109))
    assert engine.bullish == []


@pytest.mark.unit
def test_fvg_overlap_and_deterministic_replay_serialization():
    config = FairValueGapConfig(atr_length=1, hide_overlap=True)
    engine = FairValueGapEngine(config)
    engine.bullish.extend([FairValueGap(True, 110, 100, 2), FairValueGap(True, 105, 95, 1)])
    engine._remove_overlaps()
    assert [item.loc for item in engine.bullish] == [2]
    bars = [
        fvg_bar(0, high=100, low=90, close=95),
        fvg_bar(1, high=105, low=95, close=104),
        fvg_bar(2, high=106, low=101, close=103),
        fvg_bar(3, high=108, low=102, close=105),
    ]
    first = FairValueGapEngine.replay(bars, config)
    second = FairValueGapEngine.replay(bars, config)
    assert first.serialize() == second.serialize()
    assert FairValueGapEngine.deserialize(first.serialize()).serialize() == first.serialize()


@pytest.mark.unit
def test_fvg_cross_side_overlap_uses_bull_then_bear_order():
    engine = FairValueGapEngine(FairValueGapConfig(atr_length=1, hide_overlap=True))
    engine.bullish.append(FairValueGap(True, 110, 100, 1))
    bear = FairValueGap(False, 105, 95, 2)
    engine.bearish.append(bear)
    engine._remove_overlaps()
    assert engine.bullish == []
    assert engine.bearish == [bear]


def liquidity_config(**changes):
    values = {
        "left_bars": 2,
        "right_bars": 1,
        "max_zones": 2,
        "volume_strength": "Low",
        "atr_length": 1,
        "normalization_length": 2,
    }
    values.update(changes)
    return LiquidityZoneConfig(**values)


@pytest.mark.unit
def test_liquidity_pivot_volume_filter_static_distance_and_grab():
    engine = LiquidityZoneEngine(liquidity_config())
    bars = [
        liquidity_bar(0, 10, 8, 9, 1),
        liquidity_bar(1, 11, 9, 10, 1),
        liquidity_bar(2, 20, 10, 19, 10),
        liquidity_bar(3, 12, 10, 11, 2),
    ]
    updates = engine.process_bars(bars)
    assert updates[-1].created == "UPPER"
    zone = engine.zones[0]
    assert zone.pivot_index == 2
    assert zone.average_volume == 10
    assert zone.normalized_volume > 1
    assert zone.line_end_index == 4
    engine.update(liquidity_bar(4, zone.level + 1, zone.level - 1, zone.level, 2))
    assert zone.grabbed is True
    assert zone.grabbed_index == 4


@pytest.mark.unit
def test_liquidity_dynamic_distance_uses_pivot_normalized_volume_and_atr():
    engine = LiquidityZoneEngine(liquidity_config(dynamic_distance=True))
    engine.process_bars(
        [
            liquidity_bar(0, 10, 8, 9, 1),
            liquidity_bar(1, 11, 9, 10, 1),
            liquidity_bar(2, 20, 10, 19, 10),
            liquidity_bar(3, 12, 10, 11, 2),
        ]
    )
    zone = engine.zones[0]
    pivot_atr = engine._history[2]["atr"]
    assert zone.distance == pytest.approx(zone.normalized_volume * pivot_atr / 2)


@pytest.mark.unit
def test_liquidity_lower_pivot_is_created_symmetrically():
    engine = LiquidityZoneEngine(liquidity_config())
    updates = engine.process_bars(
        [
            liquidity_bar(0, 12, 10, 11, 1),
            liquidity_bar(1, 11, 9, 10, 1),
            liquidity_bar(2, 2, 0, 1, 10),
            liquidity_bar(3, 10, 8, 9, 2),
        ]
    )
    assert updates[-1].created == "LOWER"
    assert engine.zones[0].base == 0
    assert engine.zones[0].outer < engine.zones[0].base


@pytest.mark.unit
def test_liquidity_equal_right_extreme_does_not_confirm_pivot():
    engine = LiquidityZoneEngine(liquidity_config())
    engine.process_bars(
        [
            liquidity_bar(0, 10, 8, 9, 1),
            liquidity_bar(1, 11, 9, 10, 1),
            liquidity_bar(2, 20, 10, 19, 10),
            liquidity_bar(3, 20, 10, 11, 2),
        ]
    )
    assert engine.zones == []


@pytest.mark.unit
def test_liquidity_window_start_capacity_and_serialization(tmp_path):
    engine = LiquidityZoneEngine(liquidity_config(max_zones=1))
    assert engine.update(liquidity_bar(0, 10, 8, 9, 1)).created is None
    engine.zones.extend(
        [
            # Capacity is enforced on the next deterministic update.
            LiquidityZone("UPPER", 0, 0, 10, 11, 1, 10, 2, 0),
            LiquidityZone("LOWER", 1, 60, 9, 8, 1, 10, 2, 1),
        ]
    )
    engine.update(liquidity_bar(1, 9, 8.5, 8.8, 2))
    assert len(engine.zones) == 1
    path = tmp_path / "liquidity.json"
    engine.save(path)
    assert LiquidityZoneEngine.load(path).serialize() == engine.serialize()


@pytest.mark.unit
def test_session_permissions_boundaries_modes_reset_and_persistence(tmp_path):
    manager = SharedSessionManager(SessionConfig())
    assert manager.evaluate(datetime(2026, 7, 14, 9, 14)).entry_allowed is False
    assert manager.evaluate(datetime(2026, 7, 14, 9, 15)).entry_allowed is True
    at_square_off = manager.evaluate(datetime(2026, 7, 14, 15, 15))
    assert at_square_off.entry_allowed is False and at_square_off.square_off is True
    next_day = manager.evaluate(datetime(2026, 7, 15, 9, 15))
    assert next_day.daily_reset is True
    path = tmp_path / "session.json"
    manager.save(path)
    assert SharedSessionManager.load(path).serialize() == manager.serialize()
    positional = SharedSessionManager(SessionConfig(mode="Positional"))
    result = positional.evaluate(datetime(2026, 7, 14, 3, 0))
    assert result.entry_allowed is True and result.square_off is False

    overnight = SharedSessionManager(
        SessionConfig(entry_session="2200-0200", square_off_session="0200-0215")
    )
    assert overnight.evaluate(datetime(2026, 7, 14, 23, 0)).entry_allowed is True
    assert overnight.evaluate(datetime(2026, 7, 15, 1, 59)).entry_allowed is True
    assert overnight.evaluate(datetime(2026, 7, 15, 2, 0)).square_off is True


@pytest.mark.safety
def test_shared_risk_fails_closed_without_configuration_and_enforces_policies(tmp_path):
    assert SharedRiskEngine().evaluate(requested_capital=1, requested_risk=1).reason == "RISK_CONFIGURATION_ABSENT"
    engine = SharedRiskEngine(SharedRiskPolicy(100_000, 1_000, 3_000, 1))
    assert engine.evaluate(requested_capital=50_000, requested_risk=500).authorized is True
    engine.state.concurrent_trades = 1
    assert engine.evaluate(requested_capital=1, requested_risk=1).reason == "MAX_CONCURRENT_TRADES"
    engine.state.concurrent_trades = 0
    engine.state.daily_realized_pnl = -3_000
    assert engine.evaluate(requested_capital=1, requested_risk=1).reason == "DAILY_LOSS_LIMIT"
    engine.state.daily_realized_pnl = 0
    engine.state.allocated_capital = 99_999
    assert engine.evaluate(requested_capital=2, requested_risk=0).reason == "CAPITAL_ALLOCATION"
    engine.state.allocated_capital = 0
    engine.state.allocated_risk = 1_000
    assert engine.evaluate(requested_capital=0, requested_risk=1).reason == "RISK_ALLOCATION"
    path = tmp_path / "risk.json"
    engine.save(path)
    assert SharedRiskEngine.load(path).serialize() == engine.serialize()


@pytest.mark.unit
def test_pullback_and_breakout_import_the_same_shared_core_bindings():
    assert PullbackMasterPineEventAdapter.shared_core_types is SHARED_TRADING_CORE_TYPES
    assert BreakoutMainSignalEngine.shared_core_types is SHARED_TRADING_CORE_TYPES
    assert BreakoutMainOrderBlockAdapter.shared_core_types is SHARED_TRADING_CORE_TYPES
    assert set(SHARED_TRADING_CORE_TYPES) == {
        "fair_value_gaps",
        "liquidity_zones",
        "order_blocks",
        "risk",
        "sessions",
        "supertrend",
        "volume_filter",
        "vwap",
    }
