"""
Test Suite for Canonical Feature Engine Phase 8:
Real Consumer Cutover Path + Runtime Control Plane.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import pytest

from src.canonical_features.models import CanonicalFeatureSnapshot
from src.canonical_features.service import CanonicalFeatureService
from src.canonical_features.migration import MigrationRegistry, MigrationMode
from src.canonical_features.artifact import generate_promotion_readiness_artifact
from scripts.validate_canonical_live_migration import run_validation


@pytest.fixture(autouse=True)
def reset_service_singleton(tmp_path):
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


def test_1_real_consumer_output_boundaries_dual_read(tmp_path, sample_real_candles):
    ctrl_path = tmp_path / "control.json"
    reg = MigrationRegistry(control_path=str(ctrl_path))

    service = CanonicalFeatureService(
        persistence_path=str(tmp_path / "state.json"),
        bootstrap_path=str(tmp_path / "missing.json"),
        enabled=True,
    )
    for c in sample_real_candles:
        service.publish_candle(c, is_complete=True)

    snap = service.get_latest_snapshot()

    # OSE EMA_50
    ose_res = reg.evaluate_read("OSE", "ema_50", "EMA_OSE_V1", 24378.985093, snap)
    assert ose_res.selected_value == 24378.985093
    assert ose_res.authoritative_source == "LEGACY"

    # VOB ATR_14
    vob_res = reg.evaluate_read("VOB", "atr_value", "ATR_WILDER_VOB_V1", 14.926577, snap)
    assert vob_res.selected_value == 14.926577
    assert vob_res.authoritative_source == "LEGACY"

    # Tactical Edge Supertrend
    tact_res = reg.evaluate_read("TACTICAL_EDGE", "supertrend", "SUPERTREND_OSE_V1", 24405.8313, snap)
    assert tact_res.selected_value == 24405.8313
    assert tact_res.authoritative_source == "LEGACY"

    # Edge Lab VWAP
    edge_res = reg.evaluate_read("EDGE_LAB", "vwap_value", "VWAP_CUMULATIVE_V1", 24089.5408, snap)
    assert edge_res.selected_value == 24089.5408
    assert edge_res.authoritative_source == "LEGACY"


def test_2_persistent_control_plane_state(tmp_path):
    ctrl_path = tmp_path / "control.json"
    reg1 = MigrationRegistry(control_path=str(ctrl_path))
    reg1.set_mode("OSE", MigrationMode.LEGACY_ONLY, actor="TEST", reason="ROLLBACK_TEST")

    # Second instance reads persisted control file
    reg2 = MigrationRegistry(control_path=str(ctrl_path))
    assert reg2.get_mode("OSE") == MigrationMode.LEGACY_ONLY


def test_3_closed_market_promotion_refused(tmp_path):
    ctrl_path = tmp_path / "control.json"
    reg = MigrationRegistry(control_path=str(ctrl_path), primary_permit=False)
    reg.set_mode("OSE", MigrationMode.CANONICAL_PRIMARY_WITH_LEGACY_FALLBACK)

    # Permit is False, so mode remains DUAL_READ
    assert reg.get_mode("OSE") == MigrationMode.DUAL_READ


def test_4_rollback_reflected_in_real_consumer(tmp_path, sample_real_candles):
    ctrl_path = tmp_path / "control.json"
    reg = MigrationRegistry(control_path=str(ctrl_path))
    reg.set_mode("VOB", MigrationMode.LEGACY_ONLY, actor="CLI", reason="EMERGENCY_ROLLBACK")

    service = CanonicalFeatureService(
        persistence_path=str(tmp_path / "state.json"),
        bootstrap_path=str(tmp_path / "missing.json"),
        enabled=True,
    )
    for c in sample_real_candles:
        service.publish_candle(c, is_complete=True)

    snap = service.get_latest_snapshot()
    read_res = reg.evaluate_read("VOB", "atr_value", "ATR_WILDER_VOB_V1", 14.926577, snap)

    assert read_res.mode == MigrationMode.LEGACY_ONLY
    assert read_res.canonical_value is None
    assert read_res.selected_value == 14.926577
    assert read_res.fallback_reason == "MODE_LEGACY_ONLY"


def test_5_artifact_accounting_fields(tmp_path, sample_real_candles):
    service = CanonicalFeatureService(
        persistence_path=str(tmp_path / "state.json"),
        bootstrap_path=str(tmp_path / "missing.json"),
        enabled=True,
    )
    for c in sample_real_candles:
        service.publish_candle(c, is_complete=True)

    art_path = tmp_path / "readiness.json"
    art = generate_promotion_readiness_artifact(service, str(art_path))

    ose_art = art["consumers"]["OSE"]
    assert "bars_loaded" in ose_art
    assert "bars_retained" in ose_art
    assert "warmup_bars" in ose_art
    assert "comparable_bars" in ose_art
    assert "feature_comparisons" in ose_art


def test_6_zero_execution_influence():
    val = run_validation("http://127.0.0.1:8000")
    assert "checks" in val
