import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.oracle_certification.harness import (
    DynamicProcessMonitor,
    RotatingJsonlFollower,
    create_run_directory,
    evaluate_pre_soak_gate,
    finalize_run,
    launch_one_shot,
    write_once,
)


def projection(revision):
    return {
        "event_type": "FLOW_PROJECTION", "recorded_at": f"2026-08-12T04:00:0{revision}Z",
        "payload": {"revision": revision, "generated_at": f"2026-08-12T04:00:0{revision}Z",
                    "snapshot_id": f"flow-{revision}", "source_security_id": "58072"},
    }


def append(path, row):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def test_projection_capture_attaches_before_t0_and_survives_rotation(tmp_path):
    journal = tmp_path / "projections.jsonl"
    journal.touch()
    follower = RotatingJsonlFollower(journal, required_projection_fields=True)
    follower.start(from_end=True)
    t0 = time.perf_counter_ns()
    append(journal, projection(1))
    rotated = tmp_path / "projections.jsonl.1"
    journal.rename(rotated)
    journal.touch()
    append(journal, projection(2))
    time.sleep(.1)
    follower.stop()
    assert follower.attached_at_ns <= t0
    assert [row["payload"]["revision"] for row in follower.rows] == [1, 2]
    assert follower.errors == []


def test_finalized_run_cannot_be_reused_or_overwritten(tmp_path):
    run_id, output = create_run_directory(tmp_path, prefix="smoke", run_id="smoke-1")
    write_once(output / "PID.json", {"pid": 123})
    finalize_run(output, run_id=run_id, started_at="a", ended_at="b", pid=123, exit_code=0)
    with pytest.raises(FileExistsError):
        finalize_run(output, run_id=run_id, started_at="a", ended_at="b", pid=123, exit_code=0)
    with pytest.raises(FileExistsError):
        create_run_directory(tmp_path, prefix="smoke", run_id="smoke-1")


def test_one_shot_process_exits_once_and_metadata_remains_final(tmp_path):
    log = tmp_path / "collector.log"
    child = launch_one_shot([sys.executable, "-c", "print('done')"], cwd=tmp_path, stdout=log)
    pid = child.pid
    assert child.wait(timeout=5) == 0
    final = log.read_bytes()
    time.sleep(.5)
    assert log.read_bytes() == final
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_preflight_failure_never_arms_certified_clock():
    evidence = {key: True for key in evaluate_pre_soak_gate.__globals__["HARD_GATE_KEYS"]}
    evidence["BROWSER_FAST_LANE_FETCH"] = False
    result = evaluate_pre_soak_gate(evidence)
    assert result["oracle_ready"] is False
    assert result["certified_clock_armed"] is False


def test_stale_pid_monitor_reports_dead_instead_of_reusing_history():
    monitor = DynamicProcessMonitor({"backend": lambda: (_ for _ in ()).throw(RuntimeError("dead"))})
    sample = monitor.sample()
    assert sample["processes"]["backend"]["status"] == "DEAD_OR_UNRESOLVED"
