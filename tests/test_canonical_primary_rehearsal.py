"""
Test Suite for Canonical Feature Engine Phase 7:
Canonical Primary Cutover Rehearsal.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import pytest

from src.canonical_features.models import CanonicalFeatureSnapshot
from src.canonical_features.service import CanonicalFeatureService
from src.canonical_features.migration import MigrationRegistry, MigrationMode, MigrationGuardFailure
from src.canonical_features.artifact import generate_promotion_readiness_artifact
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


def test_1_promotion_permit_required():
    reg = MigrationRegistry(primary_permit=False)
    reg.set_mode("OSE", MigrationMode.CANONICAL_PRIMARY_WITH_LEGACY_FALLBACK)
    # Mode stays DUAL_READ because permit is False
    assert reg.get_mode("OSE") == MigrationMode.DUAL_READ


def test_2_primary_selection_when_permitted(tmp_path, sample_real_candles):
    reg = MigrationRegistry(primary_permit=True)
    reg.set_mode("OSE", MigrationMode.CANONICAL_PRIMARY_WITH_LEGACY_FALLBACK)

    service = CanonicalFeatureService(
        persistence_path=str(tmp_path / "state.json"),
        bootstrap_path=str(tmp_path / "missing.json"),
        enabled=True,
    )
    for c in sample_real_candles:
        service.publish_candle(c, is_complete=True)

    snap = service.get_latest_snapshot()
    canonical_ema = snap.ema_values["ema_50"]
    read_res = reg.evaluate_read(
        consumer="OSE",
        feature_name="ema_50",
        profile_id="EMA_OSE_V1",
        legacy_val=canonical_ema,  # Matching legacy value
        snapshot=snap,
    )

    assert read_res.mode == MigrationMode.CANONICAL_PRIMARY_WITH_LEGACY_FALLBACK
    assert read_res.authoritative_source == "CANONICAL"
    assert read_res.selected_value == canonical_ema  # Canonical selected!
    assert read_res.execution_influence == "ZERO"


def test_3_forced_drift_failure_automatic_fallback(tmp_path, sample_real_candles):
    reg = MigrationRegistry(primary_permit=True)
    reg.set_mode("VOB", MigrationMode.CANONICAL_PRIMARY_WITH_LEGACY_FALLBACK)

    service = CanonicalFeatureService(
        persistence_path=str(tmp_path / "state.json"),
        bootstrap_path=str(tmp_path / "missing.json"),
        enabled=True,
    )
    for c in sample_real_candles:
        service.publish_candle(c, is_complete=True)

    snap = service.get_latest_snapshot()
    # Inject large drift legacy value
    read_res = reg.evaluate_read(
        consumer="VOB",
        feature_name="atr_value",
        profile_id="ATR_WILDER_VOB_V1",
        legacy_val=9999.9,  # High drift
        snapshot=snap,
        max_tolerance=0.02,
    )

    assert read_res.fallback_occurred is True
    assert read_res.fallback_reason == "DRIFT_EXCEEDED"
    assert read_res.authoritative_source == "LEGACY"
    assert read_res.selected_value == 9999.9  # Legacy returned as decision fallback!


def test_4_stale_snapshot_live_market_fallback():
    reg = MigrationRegistry(primary_permit=True)
    reg.set_mode("OSE", MigrationMode.CANONICAL_PRIMARY_WITH_LEGACY_FALLBACK)

    stale_snap = CanonicalFeatureSnapshot(
        feature_snapshot_id="snap_stale",
        instrument="NIFTY",
        timeframe="5m",
        freshness_age_seconds=1200.0,  # > 900s
        ema_values={"ema_50": 24000.0},
    )

    read_res = reg.evaluate_read(
        consumer="OSE",
        feature_name="ema_50",
        profile_id="EMA_OSE_V1",
        legacy_val=24000.0,
        snapshot=stale_snap,
        is_live_market=True,  # Enforces stale guard
    )

    assert read_res.fallback_occurred is True
    assert read_res.fallback_reason == "STALE_SNAPSHOT"
    assert read_res.selected_value == 24000.0


def test_5_canonical_only_prohibited():
    reg = MigrationRegistry(primary_permit=True)
    reg.set_mode("EDGE_LAB", MigrationMode.CANONICAL_ONLY)
    # Blocked and defaults to DUAL_READ
    assert reg.get_mode("EDGE_LAB") == MigrationMode.DUAL_READ


def test_6_promotion_readiness_artifact_generation(tmp_path, sample_real_candles):
    service = CanonicalFeatureService(
        persistence_path=str(tmp_path / "state.json"),
        bootstrap_path=str(tmp_path / "missing.json"),
        enabled=True,
    )
    for c in sample_real_candles:
        service.publish_candle(c, is_complete=True)

    art_path = tmp_path / "canonical_promotion_readiness.json"
    art = generate_promotion_readiness_artifact(service, str(art_path))

    assert "consumers" in art
    assert "OSE" in art["consumers"]
    assert "VOB" in art["consumers"]
    assert art_path.exists()
