import os
import time
import pytest
from datetime import datetime, timezone

from src.oracle.canonical_runtime_truth import (
    CanonicalRuntimeTruth,
    SubsystemState,
    GlobalReadinessState,
)


def test_t11_dual_branch_futures_available_when_analytics_fails():
    """T11: Futures branch remains valid/fresh even when analytics worker is dead."""
    truth = CanonicalRuntimeTruth()
    
    # Futures & Spot are live
    truth.update_market_data(futures_live=True, spot_live=True, options_live=False)
    
    # Analytics worker is failed/dead
    truth.update_analytics(
        argus_live=False,
        ose_live=False,
        vob_live=False,
        worker_alive=False,
        error="LIVE_ANALYTICS_WORKER_DEAD"
    )
    
    snapshot = truth.evaluate()
    # Global state is NOT_READY/DEGRADED (never ready, but futures accessible)
    assert snapshot.global_readiness in (GlobalReadinessState.NOT_READY, GlobalReadinessState.DEGRADED)
    assert snapshot.is_ready is False
    assert snapshot.futures_available is True
    assert snapshot.analytics_available is False
    assert "LIVE_ANALYTICS_WORKER_DEAD" in snapshot.blockers


def test_t12_t13_vob_timestamp_semantics_evaluation_vs_zone_formation():
    """T12-T13: VOB zone formation timestamp is NOT used as engine freshness; evaluated_at is used."""
    truth = CanonicalRuntimeTruth()
    
    # Simulate VOB zone formed 45 minutes ago (13:00)
    zone_formation_ts = "2026-08-18T13:00:00+05:30"
    # But VOB engine evaluated the zone 500ms ago (15:35:00)
    now_ts = datetime.now(timezone.utc).isoformat()
    last_evaluated_at = time.time()
    
    is_fresh = truth.check_vob_engine_freshness(
        zone_formation_timestamp=zone_formation_ts,
        last_evaluated_monotonic=last_evaluated_at,
        max_evaluation_age_seconds=2.0
    )
    # Must be FRESH because the engine evaluated it 0.5s ago, regardless of 45m old zone formation!
    assert is_fresh is True


def test_t14_all_readiness_surfaces_agree():
    """T14: All readiness dimensions agree on canonical global state."""
    truth = CanonicalRuntimeTruth()
    
    # 1. Fully healthy
    truth.update_process(process_live=True)
    truth.update_market_data(futures_live=True, spot_live=True, options_live=True)
    truth.update_analytics(argus_live=True, ose_live=True, vob_live=True, worker_alive=True)
    truth.update_persistence(persistence_live=True)
    truth.update_safety(execution_safe=True)
    
    snap1 = truth.evaluate()
    assert snap1.global_readiness == GlobalReadinessState.READY
    assert snap1.is_ready is True
    
    # 2. Persistence degraded -> Global DEGRADED
    truth.update_persistence(persistence_live=False, degraded_reason="DISK_ENOSPC")
    snap2 = truth.evaluate()
    assert snap2.global_readiness == GlobalReadinessState.DEGRADED
    assert snap2.is_ready is False
    
    # 3. Analytics dead -> Global NOT_READY
    truth.update_analytics(argus_live=False, ose_live=False, vob_live=False, worker_alive=False)
    snap3 = truth.evaluate()
    assert snap3.global_readiness == GlobalReadinessState.NOT_READY
    assert snap3.is_ready is False


def test_t15_execution_safety_invariants():
    """T15: Execution safety invariants are strictly enforced."""
    truth = CanonicalRuntimeTruth()
    
    # Any violation of paper_only or live_trading must trigger NOT_READY / UNSAFE
    truth.update_safety(
        paper_only=True,
        live_trading_enabled=False,
        execution_influence="ZERO",
        broker_submission=False
    )
    assert truth.is_execution_safe() is True
    
    # Breach simulation
    truth.update_safety(
        paper_only=False, # BREACH
        live_trading_enabled=True, # BREACH
        execution_influence="FULL",
        broker_submission=True
    )
    assert truth.is_execution_safe() is False
    assert truth.evaluate().global_readiness == GlobalReadinessState.NOT_READY
