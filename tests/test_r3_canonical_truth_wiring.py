import pytest
from src.oracle.canonical_runtime_truth import (
    CanonicalRuntimeTruth,
    GlobalReadinessState,
    StoragePersistenceState,
)


def test_canonical_runtime_truth_wiring_and_semantics():
    """Verify CanonicalRuntimeTruth multi-dimensional evaluation and consistency."""
    truth = CanonicalRuntimeTruth()

    # 1. Nominal Ready State
    truth.update_process(process_live=True)
    truth.update_market_data(futures_live=True, spot_live=True, options_live=True, order_flow_live=True)
    truth.update_analytics(argus_live=True, ose_live=True, vob_live=True, strategy_lab_live=True, worker_alive=True)
    truth.update_persistence(persistence_live=True, free_gb=20.0)
    truth.update_safety(paper_only=True, live_trading_enabled=False, execution_influence="ZERO", broker_submission=False)

    snap = truth.evaluate()
    assert snap.global_readiness == GlobalReadinessState.READY
    assert snap.is_ready is True
    assert snap.persistence_state == StoragePersistenceState.PERSISTENCE_HEALTHY
    assert len(snap.blockers) == 0

    # 2. Dead Worker blocks readiness
    truth.update_analytics(worker_alive=False)
    snap_dead = truth.evaluate()
    assert snap_dead.global_readiness == GlobalReadinessState.NOT_READY
    assert snap_dead.is_ready is False
    assert "LIVE_ANALYTICS_WORKER_DEAD" in snap_dead.blockers

    # 3. Persistence Degradation does NOT kill analytics worker
    truth.update_analytics(worker_alive=True)
    truth.update_persistence(persistence_live=False, degraded_reason="DISK_IO_SIMULATED_FAILURE")
    snap_degraded = truth.evaluate()
    assert snap_degraded.global_readiness == GlobalReadinessState.DEGRADED
    assert snap_degraded.is_ready is False
    assert snap_degraded.persistence_state == StoragePersistenceState.PERSISTENCE_DEGRADED
    assert snap_degraded.analytics_available is True  # Analytics worker remains available!
    assert len(snap_degraded.blockers) == 0  # No hard blockers, degraded state

    # 4. Safety Invariant Breach creates hard blocker
    truth.update_safety(live_trading_enabled=True)
    snap_unsafe = truth.evaluate()
    assert snap_unsafe.global_readiness == GlobalReadinessState.NOT_READY
    assert "SAFETY_INVARIANT_BREACH" in snap_unsafe.blockers


def test_vob_freshness_uses_evaluation_time_not_formation():
    """Verify VOB freshness evaluates against engine calculation time, not zone formation time."""
    truth = CanonicalRuntimeTruth()
    import time

    now_mono = time.monotonic()
    
    # Old zone formation time (e.g. 3 hours ago) with fresh engine evaluation (0.1s ago)
    is_fresh = truth.check_vob_engine_freshness(
        zone_formation_timestamp="2026-08-18T09:15:00.000000+05:30",
        last_evaluated_monotonic=now_mono - 0.1,
        max_evaluation_age_seconds=5.0
    )
    assert is_fresh is True

    # Stale engine evaluation (10s ago)
    is_stale = truth.check_vob_engine_freshness(
        zone_formation_timestamp="2026-08-18T09:15:00.000000+05:30",
        last_evaluated_monotonic=now_mono - 10.0,
        max_evaluation_age_seconds=5.0
    )
    assert is_stale is False


def test_canonical_truth_sole_authority_across_surfaces():
    """Verify that CanonicalRuntimeTruth is the sole readiness authority across all public shapes."""
    truth = CanonicalRuntimeTruth()
    
    # Degraded state
    truth.update_market_data(futures_live=True, spot_live=True, options_live=False, order_flow_live=True)
    snap = truth.evaluate()
    
    snap_dict = snap.to_dict()
    assert snap_dict["global_readiness"] == "DEGRADED"
    assert snap_dict["is_ready"] is False
    assert snap_dict["full_oracle_ready"] is False
    
    # Ready state
    truth.update_market_data(futures_live=True, spot_live=True, options_live=True, order_flow_live=True)
    snap_ready = truth.evaluate().to_dict()
    assert snap_ready["global_readiness"] == "READY"
    assert snap_ready["is_ready"] is True
    assert snap_ready["full_oracle_ready"] is True
