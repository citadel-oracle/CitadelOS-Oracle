"""
Test Suite for Canonical Feature Engine Phase 4:
Runtime Dataflow, Bootstrap & Accounting Closure.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import pytest

from src.canonical_features.engine import CanonicalFeatureEngine
from src.canonical_features.formula_registry import FormulaProfileRegistry
from src.canonical_features.service import CanonicalFeatureService


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
            return data.get("candles", [])[:100]
    return [
        {
            "timestamp": f"2026-07-31T10:{i:02d}:00+05:30",
            "open": 24000.0 + i,
            "high": 24010.0 + i,
            "low": 23990.0 + i,
            "close": 24005.0 + i,
            "volume": 1000.0,
        }
        for i in range(50)
    ]


def test_1_authoritative_ohlcv_rejection_missing_fields(tmp_path):
    service = CanonicalFeatureService(persistence_path=str(tmp_path / "state.json"), enabled=True)

    # LTP-only payload (missing open/high/low)
    ltp_payload = {"timestamp": "2026-07-31T10:00:00+05:30", "last_price": 24000.0}
    snap = service.publish_candle(ltp_payload, is_complete=True)

    assert snap is None
    assert service.rejected_bars == 1


def test_2_no_ltp_only_completed_candle(tmp_path):
    service = CanonicalFeatureService(persistence_path=str(tmp_path / "state.json"), enabled=True)
    bad_candle = {"timestamp": "2026-07-31T10:00:00+05:30", "open": 0.0, "high": 24000.0, "low": 24000.0, "close": 24000.0}

    snap = service.publish_candle(bad_candle, is_complete=True)
    assert snap is None
    assert service.rejected_bars == 1


def test_3_bootstrap_accounting(tmp_path):
    bootstrap_file = tmp_path / "test_candles.json"
    candles = [
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
    # Add one corrupt candle
    candles.append({"timestamp": "2026-07-31T11:00:00+05:30", "open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0})

    with open(bootstrap_file, "w") as f:
        json.dump({"candles": candles}, f)

    service = CanonicalFeatureService(
        persistence_path=str(tmp_path / "non_existent_state.json"),
        bootstrap_path=str(bootstrap_file),
        enabled=True,
    )

    assert service.runtime_status == "BOOTSTRAPPED"
    assert service.bars_loaded == 61
    assert service.valid_bars == 60
    assert service.rejected_bars == 1
    assert service.bars_finalized == 60
    assert service.warmup_bars == 50


def test_4_warmup_bars_retained(tmp_path):
    bootstrap_file = tmp_path / "test_candles.json"
    candles = [
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
    with open(bootstrap_file, "w") as f:
        json.dump({"candles": candles}, f)

    service = CanonicalFeatureService(
        persistence_path=str(tmp_path / "state.json"),
        bootstrap_path=str(bootstrap_file),
        enabled=True,
    )

    # 60 total bars bootstrapped; all 60 retained in history for seeding
    assert len(service.engine._candles) == 60
    snap = service.get_latest_snapshot()
    assert snap.ema_values.get("ema_21") is not None


def test_5_startup_restore_priority(tmp_path, sample_real_candles):
    state_file = tmp_path / "valid_state.json"
    bootstrap_file = tmp_path / "test_candles.json"
    empty_bootstrap = tmp_path / "empty_bootstrap.json"

    # Save state
    service1 = CanonicalFeatureService(
        persistence_path=str(state_file),
        bootstrap_path=str(empty_bootstrap),
        enabled=True,
    )
    for c in sample_real_candles[:30]:
        service1.publish_candle(c, is_complete=True)

    with open(bootstrap_file, "w") as f:
        json.dump({"candles": sample_real_candles[:10]}, f)

    # Instantiate service2 with BOTH state file and bootstrap file
    service2 = CanonicalFeatureService(
        persistence_path=str(state_file),
        bootstrap_path=str(bootstrap_file),
        enabled=True,
    )

    # Priority 1 must win: RESTORED state, not BOOTSTRAPPED
    assert service2.runtime_status == "RESTORED"
    assert service2.restored_from_state is True
    assert service2.bars_finalized == 30


def test_6_persisted_bar_fallback_when_no_state_file(tmp_path, sample_real_candles):
    bootstrap_file = tmp_path / "test_candles.json"
    with open(bootstrap_file, "w") as f:
        json.dump({"candles": sample_real_candles[:40]}, f)

    service = CanonicalFeatureService(
        persistence_path=str(tmp_path / "missing_state.json"),
        bootstrap_path=str(bootstrap_file),
        enabled=True,
    )

    assert service.runtime_status == "BOOTSTRAPPED"
    assert service.restored_from_state is False
    assert service.bars_finalized == 40


def test_7_no_bootstrap_data_empty_fallback(tmp_path):
    service = CanonicalFeatureService(
        persistence_path=str(tmp_path / "missing_state.json"),
        bootstrap_path=str(tmp_path / "missing_bootstrap.json"),
        enabled=True,
    )

    assert service.runtime_status == "NO_BOOTSTRAP_DATA"
    assert service.bars_finalized == 0


def test_8_duplicate_last_bar_protection(tmp_path, sample_real_candles):
    state_file = tmp_path / "dup_test.json"
    empty_bootstrap = tmp_path / "empty_bootstrap.json"
    service1 = CanonicalFeatureService(
        persistence_path=str(state_file),
        bootstrap_path=str(empty_bootstrap),
        enabled=True,
    )
    for c in sample_real_candles[:20]:
        service1.publish_candle(c, is_complete=True)

    b_count1 = len(service1.engine._candles)

    # Restore in service2
    service2 = CanonicalFeatureService(
        persistence_path=str(state_file),
        bootstrap_path=str(empty_bootstrap),
        enabled=True,
    )
    service2.publish_candle(sample_real_candles[19], is_complete=True)  # duplicate last bar

    b_count2 = len(service2.engine._candles)
    assert b_count1 == b_count2 == 20


def test_9_endpoint_non_null_restored_status(tmp_path, sample_real_candles):
    bootstrap_file = tmp_path / "test_candles.json"
    with open(bootstrap_file, "w") as f:
        json.dump({"candles": sample_real_candles[:60]}, f)

    service = CanonicalFeatureService(
        persistence_path=str(tmp_path / "missing_state.json"),
        bootstrap_path=str(bootstrap_file),
        enabled=True,
    )

    status = service.get_shadow_status()
    assert status["enabled"] is True
    assert status["runtime_status"] == "BOOTSTRAPPED"
    assert status["latest_snapshot_id"] is not None
    assert status["source_revision"] > 0
    assert status["feature_revision"] > 0
    assert status["bars_finalized"] == 60
    assert status["latest_completed_bar_end"] is not None
    assert status["execution_influence"] == "ZERO"


def test_10_adapter_report_population(tmp_path, sample_real_candles):
    bootstrap_file = tmp_path / "test_candles.json"
    with open(bootstrap_file, "w") as f:
        json.dump({"candles": sample_real_candles[:60]}, f)

    service = CanonicalFeatureService(
        persistence_path=str(tmp_path / "missing_state.json"),
        bootstrap_path=str(bootstrap_file),
        enabled=True,
    )

    status = service.get_shadow_status()
    reports = status["active_reports"]

    assert len(reports) >= 4
    assert "OSE:ema_50" in reports
    assert "VOB:atr_value" in reports
    assert "TACTICAL_EDGE:supertrend" in reports
    assert "EDGE_LAB:vwap_value" in reports


def test_11_zero_execution_influence(tmp_path):
    service = CanonicalFeatureService(persistence_path=str(tmp_path / "state.json"), enabled=True)
    status = service.get_shadow_status()
    assert status["execution_influence"] == "ZERO"


def test_12_restore_hydrates_all_four_profiles_no_false_warmup_missing(tmp_path, sample_real_candles):
    state_file = tmp_path / "full_restore_state.json"
    bootstrap_file = tmp_path / "test_candles.json"
    with open(bootstrap_file, "w") as f:
        json.dump({"candles": sample_real_candles[:60]}, f)

    # Initial bootstrap service
    service1 = CanonicalFeatureService(
        persistence_path=str(state_file),
        bootstrap_path=str(bootstrap_file),
        enabled=True,
    )
    # Perform checkpoint
    service1.checkpoint(reason="TEST")

    # Restore in service2
    service2 = CanonicalFeatureService(
        persistence_path=str(state_file),
        bootstrap_path=str(bootstrap_file),
        enabled=True,
    )

    status = service2.get_shadow_status()
    reports = status["active_reports"]

    assert status["runtime_status"] == "RESTORED"
    assert status["restored_from_state"] is True
    assert len(reports) >= 4

    # Verify all 4 canonical values are non-null and zero WARMUP_MISSING
    for key in ("OSE:ema_50", "VOB:atr_value", "TACTICAL_EDGE:supertrend", "EDGE_LAB:vwap_value"):
        assert key in reports, f"Missing report key {key}"
        rep = reports[key]
        assert rep["canonical_value"] is not None, f"Canonical value for {key} is null"
        assert rep["classification"] != "WARMUP_MISSING", f"Unexpected WARMUP_MISSING for {key}"
        assert rep["execution_influence"] == "ZERO"


def test_13_pre_post_checkpoint_roundtrip_parity(tmp_path, sample_real_candles):
    state_file = tmp_path / "roundtrip_state.json"
    bootstrap_file = tmp_path / "test_candles.json"
    with open(bootstrap_file, "w") as f:
        json.dump({"candles": sample_real_candles[:60]}, f)

    service1 = CanonicalFeatureService(
        persistence_path=str(state_file),
        bootstrap_path=str(bootstrap_file),
        enabled=True,
    )
    snap1 = service1.get_latest_snapshot()
    service1.checkpoint(reason="ROUNDTRIP")

    service2 = CanonicalFeatureService(
        persistence_path=str(state_file),
        bootstrap_path=str(bootstrap_file),
        enabled=True,
    )
    snap2 = service2.get_latest_snapshot()

    assert snap1.ema_values["ema_50"] == snap2.ema_values["ema_50"]
    assert snap1.atr_value == snap2.atr_value
    assert snap1.supertrend.value == snap2.supertrend.value
    assert snap1.vwap_value == snap2.vwap_value

