import os
import time
import pytest
from unittest.mock import MagicMock

from src.oracle.isolated_execution_boundary import IsolatedExecutionBoundary, WorkerState


def sample_processor(kind, payload):
    if kind == "error":
        raise ValueError("simulated processor crash")
    return {"processed_kind": kind, "data": payload, "processed_at": time.time()}


def test_t2_t3_t4_t5_worker_supervision_death_detection_and_cache_invalidation():
    """T2-T5: Death detection, listener EOF, cache invalidation, and dead worker not ready."""
    boundary = IsolatedExecutionBoundary(
        name="test-worker",
        processor=sample_processor,
        publish_interval_seconds=0.1,
        enable_supervision=False, # manual control for unit test
    )
    started = boundary.start()
    assert started is True
    time.sleep(0.3)

    # 1. Initial healthy state
    submitted = boundary.submit("normal", {"val": 100})
    assert submitted is True
    time.sleep(0.3)

    st = boundary.status()
    assert st["alive"] is True
    assert st["state"] == WorkerState.HEALTHY.value
    curr = boundary.current()
    assert curr is not None
    assert curr.get("data") == {"val": 100}

    # 2. Kill the child process (Simulate unhandled crash / kill -9)
    pid = boundary._process.pid
    os.kill(pid, 9)
    time.sleep(0.4)

    # Check that death is detected
    boundary._check_liveness()
    st_dead = boundary.status()
    assert st_dead["alive"] is False
    assert st_dead["state"] in (WorkerState.FAILED.value, WorkerState.STOPPED.value)

    # T4: CURRENT must be None / invalid, but LAST_GOOD is preserved
    assert boundary.current() is None
    last_good = boundary.last_good()
    assert last_good is not None
    assert last_good.get("data") == {"val": 100}
    assert boundary.is_fresh(max_age_seconds=1.0) is False

    boundary.stop()


def test_t6_t7_t8_restart_no_duplicates_and_crash_loop():
    """T6-T8: Bounded restart, single process guarantee, and crash loop protection."""
    boundary = IsolatedExecutionBoundary(
        name="test-restart-worker",
        processor=sample_processor,
        publish_interval_seconds=0.1,
        max_restarts_per_minute=3,
        enable_supervision=False,
    )
    boundary.start()
    time.sleep(0.3)
    p1 = boundary._process
    pid1 = p1.pid

    # 1. First restart
    boundary.restart()
    time.sleep(0.3)
    p2 = boundary._process
    pid2 = p2.pid
    assert pid1 != pid2
    assert p2.is_alive() is True
    # T7: Ensure old process is dead (no duplicates)
    assert not p1.is_alive()

    # 2. Trigger repeated crashes to test crash loop protection (T8)
    for _ in range(4):
        boundary.restart()
        time.sleep(0.05)

    # After exceeding max_restarts_per_minute (3), worker must enter CRASH_LOOP
    st = boundary.status()
    assert st["state"] == WorkerState.CRASH_LOOP.value
    assert st["crash_loop"] is True

    boundary.stop()


def test_t9_t10_rehydration_before_healthy():
    """T9-T10: Worker is REHYDRATING after restart and becomes HEALTHY only after fresh output."""
    boundary = IsolatedExecutionBoundary(
        name="test-rehydrate-worker",
        processor=sample_processor,
        publish_interval_seconds=0.1,
        enable_supervision=False,
    )
    boundary.start()
    time.sleep(0.2)

    # Force transition to REHYDRATING upon restart
    boundary.mark_rehydrating()
    assert boundary.status()["state"] == WorkerState.REHYDRATING.value
    # T9: Even though process is alive, state is NOT HEALTHY
    assert boundary.is_healthy() is False

    # T10: Submit fresh data; once processed, transitions to HEALTHY
    boundary.submit("rehydrate_payload", {"key": "ready"})
    time.sleep(0.3)
    assert boundary.status()["state"] == WorkerState.HEALTHY.value
    assert boundary.is_healthy() is True

    boundary.stop()
