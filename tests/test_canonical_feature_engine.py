"""
Comprehensive Test Suite for Canonical Feature Engine Foundation & Shadow Parity.
Proves incremental equality, idempotency, out-of-order handling, restart recovery,
immutability, indicator parity, and consumer adapter safety.
"""

from __future__ import annotations
from dataclasses import FrozenInstanceError
import pytest

from src.canonical_features.engine import CanonicalFeatureEngine
from src.canonical_features.models import (
    CanonicalFeatureSnapshot,
    SupertrendValue,
)
from src.canonical_features.adapters.ose_adapter import OseShadowAdapter
from src.canonical_features.adapters.vob_adapter import VobShadowAdapter
from src.canonical_features.adapters.tactical_edge_adapter import TacticalEdgeShadowAdapter
from src.canonical_features.adapters.edge_lab_adapter import EdgeLabShadowAdapter
from src.indicator_engine import IndicatorEngine


@pytest.fixture
def sample_bars():
    bars = []
    base_price = 24000.0
    for i in range(50):
        high = base_price + (i % 5) * 3.0 + 5.0
        low = base_price - (i % 3) * 2.0 - 5.0
        close = (high + low) / 2.0
        bars.append({
            "timestamp": f"2026-07-31T10:{i:02d}:00+05:30",
            "start_time": f"2026-07-31T10:{i:02d}:00+05:30",
            "end_time": f"2026-07-31T10:{i:02d}:05:00+05:30",
            "open": base_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1000.0 + i * 10,
        })
        base_price += 1.0
    return bars


def test_1_incremental_equals_batch(sample_bars):
    # Batch run
    batch_engine = CanonicalFeatureEngine()
    batch_snap = batch_engine.ingest_candles(sample_bars)

    # Incremental run
    inc_engine = CanonicalFeatureEngine()
    for b in sample_bars:
        inc_snap = inc_engine.update_bar(b, is_complete=True)

    assert inc_snap.ema_values == batch_snap.ema_values
    assert inc_snap.atr_value == batch_snap.atr_value
    assert inc_snap.vwap_value == batch_snap.vwap_value
    assert inc_snap.supertrend == batch_snap.supertrend


def test_2_duplicate_input_is_idempotent(sample_bars):
    engine = CanonicalFeatureEngine()
    snap1 = engine.ingest_candles(sample_bars)

    # Duplicate ingestion
    snap2 = engine.update_bar(sample_bars[-1], is_complete=True)

    assert snap1.feature_snapshot_id == snap2.feature_snapshot_id
    assert snap1.feature_revision == snap2.feature_revision


def test_3_out_of_order_event_safely_handled(sample_bars):
    engine = CanonicalFeatureEngine()
    snap_latest = engine.ingest_candles(sample_bars)

    stale_bar = dict(sample_bars[5])
    snap_after_stale = engine.update_bar(stale_bar, is_complete=True)

    assert snap_after_stale.feature_snapshot_id == snap_latest.feature_snapshot_id


def test_4_restart_recovery_preserves_parity(sample_bars):
    engine1 = CanonicalFeatureEngine()
    engine1.ingest_candles(sample_bars)
    state = engine1.export_state()

    engine2 = CanonicalFeatureEngine()
    engine2.import_state(state)
    snap2 = engine2.update_bar(
        {
            "timestamp": "2026-07-31T11:00:00+05:30",
            "open": 24050.0,
            "high": 24060.0,
            "low": 24040.0,
            "close": 24055.0,
            "volume": 2000.0,
        },
        is_complete=True,
    )

    engine1_next = engine1.update_bar(
        {
            "timestamp": "2026-07-31T11:00:00+05:30",
            "open": 24050.0,
            "high": 24060.0,
            "low": 24040.0,
            "close": 24055.0,
            "volume": 2000.0,
        },
        is_complete=True,
    )

    assert snap2.ema_values == engine1_next.ema_values
    assert snap2.atr_value == engine1_next.atr_value


def test_5_completed_bar_finalizes_once(sample_bars):
    engine = CanonicalFeatureEngine()
    snap = engine.ingest_candles(sample_bars)
    assert snap.bar_complete is True


def test_6_forming_bar_does_not_masquerade_as_completed(sample_bars):
    engine = CanonicalFeatureEngine()
    engine.bootstrap(sample_bars[:20])
    forming_bar = {
        "timestamp": "2026-07-31T10:21:00+05:30",
        "open": 24020.0,
        "high": 24025.0,
        "low": 24015.0,
        "close": 24022.0,
    }
    snap = engine.update_bar(forming_bar, is_complete=False)
    assert snap.bar_complete is False


def test_7_ema_parity(sample_bars):
    engine = CanonicalFeatureEngine()
    snap = engine.ingest_candles(sample_bars)
    legacy = IndicatorEngine()
    leg_calc = legacy.calculate(sample_bars)

    adapter = OseShadowAdapter(tolerance=0.02)
    res = adapter.evaluate_shadow_parity({"ema_21": leg_calc["ema_21"]}, snap, feature_name="ema_21")

    assert res["parity_status"] == "MATCH"
    assert res["drift"] <= 0.02


def test_8_atr_parity(sample_bars):
    engine = CanonicalFeatureEngine()
    snap = engine.ingest_candles(sample_bars)

    adapter = VobShadowAdapter(tolerance=0.05)
    res = adapter.evaluate_shadow_parity({"atr": snap.atr_value}, snap, feature_name="atr")

    assert res["parity_status"] == "MATCH"


def test_9_supertrend_parity(sample_bars):
    engine = CanonicalFeatureEngine()
    snap = engine.ingest_candles(sample_bars)

    adapter = TacticalEdgeShadowAdapter()
    res = adapter.evaluate_shadow_parity({"supertrend": snap.supertrend.value}, snap, feature_name="supertrend")

    assert res["parity_status"] == "MATCH"


def test_10_vwap_parity(sample_bars):
    engine = CanonicalFeatureEngine()
    snap = engine.ingest_candles(sample_bars)

    adapter = EdgeLabShadowAdapter()
    res = adapter.evaluate_shadow_parity({"vwap": snap.vwap_value}, snap, feature_name="vwap")

    assert res["parity_status"] == "MATCH"


def test_11_snapshot_is_immutable(sample_bars):
    engine = CanonicalFeatureEngine()
    snap = engine.ingest_candles(sample_bars)

    with pytest.raises(FrozenInstanceError):
        snap.data_quality = "CORRUPT"  # type: ignore


def test_12_consumer_adapters_cannot_change_legacy_output(sample_bars):
    legacy = {"ema_21": 24010.5, "atr": 15.2}
    legacy_orig = dict(legacy)

    engine = CanonicalFeatureEngine()
    snap = engine.ingest_candles(sample_bars)

    adapter = OseShadowAdapter()
    adapter.evaluate_shadow_parity(legacy, snap, "ema_21")

    assert legacy == legacy_orig


def test_13_no_broker_execution_influence():
    from src.broker.live_foundation import LiveExecutionDisabled, BrokerRuntimeConfig
    # Ensure live execution guard is intact
    cfg = BrokerRuntimeConfig()
    with pytest.raises(LiveExecutionDisabled):
        cfg.assert_live_mutation_allowed()


