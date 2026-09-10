from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.strategy_lab.state_truth import (
    CANDLE_SCHEMA_VERSION,
    CandleIdentity,
    CanonicalCandleStore,
    reset_state_truth_runtime_metrics,
    state_truth_runtime_metrics,
)


ROOT = Path(__file__).resolve().parents[2]


def _closed_candle() -> dict:
    return {
        "timestamp": "2026-08-14T09:15:00+05:30",
        "open": 24500.0,
        "high": 24510.0,
        "low": 24495.0,
        "close": 24505.0,
        "volume": 100.0,
        "source": "FIXTURE",
        "closed": True,
        "is_closed": True,
    }


def test_canonical_truth_hashes_once_then_serves_100_same_revision_reads(tmp_path):
    identity = CandleIdentity("NIFTY", "13", "5m")
    writer = CanonicalCandleStore(tmp_path, identity)
    writer.merge([_closed_candle()], fetch_timestamp=datetime.now(timezone.utc).isoformat())

    # A new owner performs one validated recovery read. Consumers of the same
    # file revision then use the immutable verified cache without more I/O or
    # full-state hashing.
    owner = CanonicalCandleStore(tmp_path, identity)
    reset_state_truth_runtime_metrics()
    first = owner.load()
    before = state_truth_runtime_metrics()
    for _ in range(100):
        assert owner.load() == first
    after = state_truth_runtime_metrics()

    assert first and first[0]["schema_version"] == CANDLE_SCHEMA_VERSION
    assert before["canonical_disk_loads"] == 1
    assert before["canonical_full_state_hashes"] == 1
    assert after["canonical_disk_loads"] == before["canonical_disk_loads"]
    assert after["canonical_full_state_hashes"] == before["canonical_full_state_hashes"]
    assert after["canonical_cache_hits"] - before["canonical_cache_hits"] == 100


def test_parent_steady_state_owns_no_eye_condition_or_development_loops():
    source = (ROOT / "app/main.py").read_text(encoding="utf-8")
    noncritical = source[source.index("def _start_noncritical_oracle_services") : source.index("@app.on_event(\"shutdown\")")]
    child_start = source[source.index("def _strategy_child_start") : source.index("def _strategy_child_stop")]

    assert "eye_scanner.start" not in noncritical
    assert "oracle_condition_monitor.start" not in noncritical
    assert "development_orchestrator.start" not in noncritical
    assert "eye_scanner.start" in child_start
    assert "oracle_condition_monitor.start" in child_start
    assert "development_orchestrator.start" in child_start
    assert 'return _strategy_cached("development")' in source
    assert '"condition_monitor": _strategy_cached("condition_monitor")' in source


def test_strategy_truth_hash_is_revision_driven_and_parent_exposes_only_metrics():
    source = (ROOT / "app/main.py").read_text(encoding="utf-8")
    snapshotter = source[source.index("def _strategy_child_snapshot") : source.index("def _apply_strategy_snapshot")]
    health = source[source.index("def health_ready") : source.index("@app.get(\"/v1/oracle/runtime-diagnostic\")")]

    assert "if truth_token != _strategy_child_truth_token:" in snapshotter
    assert "_strategy_child_truth_hash_count += 1" in snapshotter
    assert '"semantic_hash": _strategy_child_truth_hash' in snapshotter
    assert '"owner": _strategy_cached("truth")' in health
    assert "state_truth_runtime_metrics()" in health
    assert "storage_runtime_metrics()" in health


def test_eye_history_hydration_occurs_only_inside_strategy_owner():
    source = (ROOT / "app/main.py").read_text(encoding="utf-8")
    child_start = source[source.index("def _strategy_child_start") : source.index("def _strategy_child_stop")]
    construction = source[source.index("eye_runtime = EyeRuntime") : source.index("chronos_2_scheduler =")]

    assert "hydrate_option_history" in child_start
    assert "option_chart_feed.subscribe(_eye_option_chart_bridge)" in child_start
    assert "hydrate_option_history" not in construction
    assert "option_chart_feed.subscribe(_eye_option_chart_bridge)" not in construction
