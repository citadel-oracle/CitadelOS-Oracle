import os
import time
import pytest
from unittest.mock import patch
from pathlib import Path
import tempfile

from src.argus.tactical_store import ArgusTacticalStore
from src.oracle.isolated_execution_boundary import IsolatedExecutionBoundary, WorkerState
from src.oracle.canonical_runtime_truth import CanonicalRuntimeTruth, GlobalReadinessState


def sample_calc_processor(kind, payload):
    return {"kind": kind, "data": payload, "calc_ts": time.time()}


def test_fault_a_disk_failure_simulation():
    """TEST A: Disk full/failure simulation keeps calculation loop alive and marks persistence DEGRADED."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store_path = Path(tmpdir) / "test_store.json"
        store = ArgusTacticalStore(store_path)

        # Normal publish
        assert store.publish("id-1", {"val": 10}, {"evidence": 1}) is True
        assert store.is_degraded is False

        # Injected disk error
        with patch("tempfile.mkstemp", side_effect=OSError(28, "No space left on device")):
            # Publish must succeed in-memory without raising
            assert store.publish("id-2", {"val": 20}, {"evidence": 2}) is True
            assert store.is_degraded is True
            assert "No space left on device" in str(store.last_persistence_error)
            assert store.latest()["val"] == 20

        # Disk recovery
        assert store.publish("id-3", {"val": 30}, {"evidence": 3}) is True
        assert store.is_degraded is False
        assert store.latest()["val"] == 30


def test_fault_b_analytics_child_kill_and_auto_recovery():
    """TEST B: Kill analytics child -> death detected -> cache marked stale -> auto-restarts -> rehydrates -> healthy."""
    boundary = IsolatedExecutionBoundary(
        name="test-child-kill",
        processor=sample_calc_processor,
        publish_interval_seconds=0.1,
        enable_supervision=True, # Active watchdog enabled
    )
    boundary.start()
    time.sleep(0.3)
    boundary.submit("calc", {"initial": True})
    time.sleep(0.3)

    assert boundary.is_healthy() is True
    pid1 = boundary._process.pid

    # 1. Kill the child process (Simulating crash)
    os.kill(pid1, 9)

    # 2. Watchdog detects death and triggers restart
    t_wait = time.time()
    while (boundary._process is None or boundary._process.pid == pid1) and time.time() - t_wait < 5.0:
        time.sleep(0.05)

    assert boundary._process is not None
    pid2 = boundary._process.pid
    assert pid2 != pid1
    assert boundary._process.is_alive() is True

    # 3. Submit fresh data after recovery
    boundary.submit("calc", {"recovered": True})
    time.sleep(0.3)
    assert boundary.is_healthy() is True
    assert boundary.current() is not None

    boundary.stop()


def test_fault_c_frozen_output_detection():
    """TEST C: Alive process that stops publishing is detected as STALE."""
    boundary = IsolatedExecutionBoundary(
        name="test-frozen-output",
        processor=sample_calc_processor,
        publish_interval_seconds=0.1,
        enable_supervision=True,
        max_stale_seconds=1.0, # boundary clamps stale thresholds to at least 1s
    )
    boundary.start()
    time.sleep(0.2)
    boundary.submit("calc", {"active": True})
    time.sleep(0.2)
    assert boundary.is_healthy() is True

    # Stop submitting and wait for stale threshold
    time.sleep(1.2)
    st = boundary.status()
    assert st["state"] in (WorkerState.STALE.value, WorkerState.AGING.value)
    assert boundary.current() is None # Stale output is not returned as current!

    boundary.stop()


def test_fault_d_crash_loop_bounded():
    """TEST D: Repeated failures trigger rate-limited CRASH_LOOP without infinite spawning."""
    boundary = IsolatedExecutionBoundary(
        name="test-crash-loop",
        processor=sample_calc_processor,
        publish_interval_seconds=0.1,
        max_restarts_per_minute=2,
        enable_supervision=False,
    )
    boundary.start()
    time.sleep(0.2)

    # Crash 3 times rapidly
    boundary.restart()
    time.sleep(0.05)
    boundary.restart()
    time.sleep(0.05)
    boundary.restart() # Exceeds limit
    time.sleep(0.05)

    st = boundary.status()
    assert st["state"] == WorkerState.CRASH_LOOP.value
    assert st["crash_loop"] is True
    assert boundary.current() is None

    boundary.stop()


def test_fault_e_dual_branch_independence():
    """TEST E: Analytics down does not invalidate independent healthy Futures stream."""
    truth = CanonicalRuntimeTruth()
    truth.update_market_data(futures_live=True, spot_live=True, options_live=True)
    truth.update_analytics(argus_live=False, ose_live=False, vob_live=False, worker_alive=False)

    snap = truth.evaluate()
    assert snap.futures_available is True
    assert snap.analytics_available is False
    assert snap.global_readiness == GlobalReadinessState.NOT_READY
    assert "LIVE_ANALYTICS_WORKER_DEAD" in snap.blockers
