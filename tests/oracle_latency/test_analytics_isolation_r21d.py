from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from src.oracle.isolated_execution_boundary import IsolatedExecutionBoundary
from src.strategy_lab.service import StrategyLabService


def _processor(kind, payload):
    if kind == "stall":
        time.sleep(float(payload))
        return {"state": "STALE_AFTER_STALL"}
    if kind == "fail":
        raise RuntimeError("fixture failure")
    return {"sequence": int(payload), "pid": os.getpid()}


def _wait(predicate, timeout=4.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_boundary_is_a_separate_process_and_preserves_ordered_input():
    snapshots = []
    boundary = IsolatedExecutionBoundary(
        name="r21d-test-analytics",
        processor=_processor,
        on_snapshot=snapshots.append,
        publish_interval_seconds=0.05,
    )
    try:
        assert boundary.start()
        for sequence in range(20):
            assert boundary.submit("echo", sequence)
        assert _wait(lambda: boundary.status()["processed"] == 20)
        assert _wait(lambda: bool(snapshots) and snapshots[-1]["sequence"] == 19)
        assert boundary.status()["pid"] != os.getpid()
        assert boundary.status()["required_event_drops"] == 0
        assert snapshots[-1]["sequence"] == 19
        assert snapshots[-1]["pid"] == boundary.status()["pid"]
    finally:
        boundary.stop()


def test_worker_stall_cannot_stall_parent_thread():
    boundary = IsolatedExecutionBoundary(
        name="r21d-test-stall",
        processor=_processor,
        publish_interval_seconds=0.05,
    )
    try:
        boundary.start()
        assert boundary.submit("stall", 0.5)
        started = time.perf_counter()
        # This represents parent cache/health work while the analytical child
        # is deliberately CPU/sleep stalled.
        parent_health = {"process_alive": True, "analytics": "STALE"}
        elapsed = time.perf_counter() - started
        assert parent_health["process_alive"] is True
        assert elapsed < 0.05
        assert _wait(lambda: boundary.status()["processed"] == 1)
    finally:
        boundary.stop()


def test_latest_snapshot_coalescing_is_not_a_required_event_drop():
    boundary = IsolatedExecutionBoundary(
        name="r21d-test-latest",
        processor=_processor,
        # Intentionally omit a listener until all outputs have been produced.
        publish_interval_seconds=0.01,
    )
    try:
        boundary.start(start_listener=False)
        for sequence in range(10):
            assert boundary.submit("echo", sequence)
        assert _wait(lambda: boundary._process is not None and boundary._process.is_alive())
        time.sleep(0.2)
        boundary.start_listener()
        assert _wait(lambda: boundary.status()["processed"] == 10)
        status = boundary.status()
        assert status["required_event_drops"] == 0
        assert status["child_snapshot_coalesces"] > 0
        assert _wait(lambda: boundary.latest() is not None and boundary.latest()["sequence"] == 9)
        assert boundary.latest()["sequence"] == 9
    finally:
        boundary.stop()


def test_strategy_lab_has_one_shared_bounded_catchup_gate(tmp_path):
    service = StrategyLabService(tmp_path, max_simultaneous_catchup=2)
    assert service._max_simultaneous_catchup == 2
    assert service._catchup_semaphore.acquire(blocking=False)
    assert service._catchup_semaphore.acquire(blocking=False)
    assert not service._catchup_semaphore.acquire(blocking=False)
    service._catchup_semaphore.release()
    service._catchup_semaphore.release()


def test_boundary_failure_is_visible_without_parent_failure():
    boundary = IsolatedExecutionBoundary(
        name="r21d-test-failure",
        processor=_processor,
        publish_interval_seconds=0.05,
    )
    try:
        boundary.start()
        assert boundary.submit("fail", None)
        assert _wait(lambda: not boundary.status()["alive"])
        assert "RuntimeError:fixture failure" in str(boundary.status()["last_error"])
    finally:
        boundary.stop()


def test_abrupt_parent_exit_cannot_leave_pid1_adopted_boundary_worker(tmp_path):
    pid_file = tmp_path / "child.pid"
    script = f"""
import os
from pathlib import Path
from src.oracle.isolated_execution_boundary import IsolatedExecutionBoundary

def processor(kind, payload):
    return {{"kind": kind, "payload": payload}}

boundary = IsolatedExecutionBoundary(name="r21d-owner-death", processor=processor)
boundary.start(start_listener=False)
Path({str(pid_file)!r}).write_text(str(boundary.status()["pid"]))
os._exit(0)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        check=False,
        timeout=10.0,
    )
    assert completed.returncode == 0
    child_pid = int(pid_file.read_text())

    def child_is_gone() -> bool:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            return True
        status = subprocess.run(
            ["ps", "-p", str(child_pid), "-o", "stat="],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        return not status or status.startswith("Z")

    assert _wait(child_is_gone, timeout=4.0)
