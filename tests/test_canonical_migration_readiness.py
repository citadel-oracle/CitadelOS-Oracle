"""
Test Suite for Canonical Feature Engine Phase 6:
Production Migration Readiness Wave.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import pytest

from src.canonical_features.models import CanonicalFeatureSnapshot, SupertrendValue
from src.canonical_features.service import CanonicalFeatureService
from src.canonical_features.migration import MigrationRegistry, MigrationMode, MigrationGuardFailure
from scripts.validate_canonical_live_migration import run_validation


@pytest.fixture(autouse=True)
def reset_service_singleton():
    CanonicalFeatureService.reset_instance()
    yield
    CanonicalFeatureService.reset_instance()


@pytest.fixture
def sample_real_candles():
    candles_path = Path("logs/kronos_alpha_candles.json")
    if candles_path.exists():
        with open(candles_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("candles", [])[:60]
    return [
        {
            "timestamp": f"2026-07-31T10:{i:02d}:00+05:30",
            "open": 24000.0 + i,
            "high": 24010.0 + i,
            "low": 23990.0 + i,
            "close": 24005.0 + i,
            "volume": 1000.0,
        }
        for i in range(60)
    ]


def test_1_locked_profile_mapping():
    from src.canonical_features.formula_registry import FormulaProfileRegistry

    profiles = FormulaProfileRegistry.PROFILES
    assert "EMA_OSE_V1" in profiles
    assert "ATR_WILDER_VOB_V1" in profiles
    assert "SUPERTREND_OSE_V1" in profiles
    assert "VWAP_CUMULATIVE_V1" in profiles

    assert profiles["EMA_OSE_V1"].consumer == "OSE"
    assert profiles["ATR_WILDER_VOB_V1"].consumer == "VOB"
    assert profiles["SUPERTREND_OSE_V1"].consumer == "OSE / Tactical Edge"
    assert profiles["VWAP_CUMULATIVE_V1"].consumer == "Kronos / Edge Lab"


def test_2_dual_read_keeps_legacy_authoritative(tmp_path, sample_real_candles):
    reg = MigrationRegistry(overrides={"OSE": "DUAL_READ"}, control_path=str(tmp_path / "ctrl.json"))
    service = CanonicalFeatureService(
        persistence_path=str(tmp_path / "state.json"),
        bootstrap_path=str(tmp_path / "missing.json"),
        enabled=True,
    )
    for c in sample_real_candles:
        service.publish_candle(c, is_complete=True)

    snap = service.get_latest_snapshot()
    read_res = reg.evaluate_read(
        consumer="OSE",
        feature_name="ema_50",
        profile_id="EMA_OSE_V1",
        legacy_val=24378.985093,
        snapshot=snap,
    )

    assert read_res.mode == MigrationMode.DUAL_READ
    assert read_res.authoritative_source == "LEGACY"
    assert read_res.selected_value == 24378.985093  # Legacy remains decision authority!
    assert read_res.canonical_value is not None
    assert read_res.execution_influence == "ZERO"


def test_3_canonical_primary_blocked_during_readiness(tmp_path):
    reg = MigrationRegistry(overrides={"OSE": "CANONICAL_PRIMARY_WITH_LEGACY_FALLBACK"}, control_path=str(tmp_path / "ctrl.json"))
    mode = reg.get_mode("OSE")
    # Safety Check: CANONICAL_PRIMARY is blocked and defaults to DUAL_READ
    assert mode == MigrationMode.DUAL_READ


def test_4_per_consumer_rollback(tmp_path, sample_real_candles):
    reg = MigrationRegistry(overrides={"OSE": "LEGACY_ONLY"}, control_path=str(tmp_path / "ctrl.json"))
    service = CanonicalFeatureService(
        persistence_path=str(tmp_path / "state.json"),
        bootstrap_path=str(tmp_path / "missing.json"),
        enabled=True,
    )
    for c in sample_real_candles:
        service.publish_candle(c, is_complete=True)

    snap = service.get_latest_snapshot()
    read_res = reg.evaluate_read(
        consumer="OSE",
        feature_name="ema_50",
        profile_id="EMA_OSE_V1",
        legacy_val=24378.985093,
        snapshot=snap,
    )

    assert read_res.mode == MigrationMode.LEGACY_ONLY
    assert read_res.canonical_value is None
    assert read_res.selected_value == 24378.985093
    assert read_res.fallback_reason == "MODE_LEGACY_ONLY"


def test_5_stale_or_missing_snapshot_fallback(tmp_path):
    reg = MigrationRegistry(overrides={"VOB": "DUAL_READ"}, control_path=str(tmp_path / "ctrl.json"))
    read_res = reg.evaluate_read(
        consumer="VOB",
        feature_name="atr_value",
        profile_id="ATR_WILDER_VOB_V1",
        legacy_val=14.926577,
        snapshot=None,  # Missing snapshot
    )

    assert read_res.fallback_occurred is True
    assert read_res.fallback_reason == "NO_SNAPSHOT"
    assert read_res.authoritative_source == "LEGACY"
    assert read_res.selected_value == 14.926577


def test_6_wrong_instrument_or_timeframe_rejection(tmp_path):
    reg = MigrationRegistry(control_path=str(tmp_path / "ctrl.json"))
    bad_snap = CanonicalFeatureSnapshot(
        feature_snapshot_id="snap_bad",
        instrument="BANKNIFTY",  # Wrong instrument
        timeframe="15m",  # Wrong timeframe
    )

    read_res = reg.evaluate_read(
        consumer="OSE",
        feature_name="ema_50",
        profile_id="EMA_OSE_V1",
        legacy_val=24000.0,
        snapshot=bad_snap,
        expected_instrument="NIFTY",
        expected_timeframe="5m",
    )

    assert read_res.fallback_occurred is True
    assert read_res.fallback_reason == "WRONG_INSTRUMENT"
    assert read_res.selected_value == 24000.0


def test_7_missing_feature_fallback():
    reg = MigrationRegistry()
    snap_no_feature = CanonicalFeatureSnapshot(
        feature_snapshot_id="snap_empty",
        instrument="NIFTY",
        timeframe="5m",
        ema_values={},  # Empty EMA values
    )

    read_res = reg.evaluate_read(
        consumer="OSE",
        feature_name="ema_50",
        profile_id="EMA_OSE_V1",
        legacy_val=24000.0,
        snapshot=snap_no_feature,
    )

    assert read_res.fallback_occurred is True
    assert read_res.fallback_reason == "MISSING_FEATURE"
    assert read_res.selected_value == 24000.0


def test_8_zero_execution_influence():
    reg = MigrationRegistry()
    read_res = reg.evaluate_read(
        consumer="OSE",
        feature_name="ema_50",
        profile_id="EMA_OSE_V1",
        legacy_val=24000.0,
        snapshot=None,
    )
    assert read_res.execution_influence == "ZERO"


def test_9_monday_validator_schema():
    # Test Monday validator function against mocked dictionary or live endpoint
    val = run_validation("http://127.0.0.1:8000")
    assert "verdict" in val
    assert "checks" in val
    assert "shadow_status" in val
