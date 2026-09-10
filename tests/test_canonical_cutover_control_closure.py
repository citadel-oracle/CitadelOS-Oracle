"""
Test Suite for Canonical Feature Engine Phase 9:
Final Weekend Cutover Control Closure Wave.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import pytest

from src.canonical_features.models import CanonicalFeatureSnapshot
from src.canonical_features.service import CanonicalFeatureService
from src.canonical_features.migration import MigrationRegistry, MigrationMode
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


def test_1_hot_reload_without_restart(tmp_path):
    ctrl_path = tmp_path / "control.json"
    reg = MigrationRegistry(control_path=str(ctrl_path))

    # Initial mode: DUAL_READ
    assert reg.get_mode("OSE") == MigrationMode.DUAL_READ

    # Modify control file externally on disk
    with open(ctrl_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "version": "1.0.0",
                "primary_permit": False,
                "modes": {"OSE": "LEGACY_ONLY"},
                "history": [],
            },
            f,
        )

    # Hot reload detects mtime change without process restart!
    reg.refresh_if_stale()
    assert reg.get_mode("OSE") == MigrationMode.LEGACY_ONLY


def test_2_closed_market_approval_refused(tmp_path):
    ctrl_path = tmp_path / "control.json"
    reg = MigrationRegistry(control_path=str(ctrl_path), primary_permit=False)

    # Attempt setting primary mode when permit is False
    reg.set_mode("VOB", MigrationMode.CANONICAL_PRIMARY_WITH_LEGACY_FALLBACK)
    assert reg.get_mode("VOB") == MigrationMode.DUAL_READ


def test_3_rollback_all_control_file_update(tmp_path):
    ctrl_path = tmp_path / "control.json"
    reg = MigrationRegistry(control_path=str(ctrl_path))

    # Write LEGACY_ONLY for all consumers
    with open(ctrl_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "version": "1.0.0",
                "primary_permit": False,
                "modes": {
                    "OSE": "LEGACY_ONLY",
                    "VOB": "LEGACY_ONLY",
                    "TACTICAL_EDGE": "LEGACY_ONLY",
                    "EDGE_LAB": "LEGACY_ONLY",
                },
                "history": [],
            },
            f,
        )

    reg.refresh_if_stale()
    assert reg.get_mode("OSE") == MigrationMode.LEGACY_ONLY
    assert reg.get_mode("VOB") == MigrationMode.LEGACY_ONLY
    assert reg.get_mode("TACTICAL_EDGE") == MigrationMode.LEGACY_ONLY
    assert reg.get_mode("EDGE_LAB") == MigrationMode.LEGACY_ONLY


def test_4_real_consumer_replay_accounting(tmp_path, sample_real_candles):
    service = CanonicalFeatureService(
        persistence_path=str(tmp_path / "state.json"),
        bootstrap_path=str(tmp_path / "missing.json"),
        enabled=True,
    )
    for c in sample_real_candles:
        service.publish_candle(c, is_complete=True)

    status = service.get_shadow_status()
    assert status["bars_finalized"] == 60
    assert status["execution_influence"] == "ZERO"


def test_5_zero_execution_influence(tmp_path):
    reg = MigrationRegistry(control_path=str(tmp_path / "ctrl.json"))
    status = reg.get_migration_status()
    assert status["safety"]["execution_influence"] == "ZERO"
