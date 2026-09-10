import json
import time
from threading import Event, Thread

from src.order_flow.recorder import OrderFlowEvidenceRecorder


def test_recorder_persists_explicit_accounting_and_true_queue_age(tmp_path):
    recorder = OrderFlowEvidenceRecorder(tmp_path, queue_size=8, batch_size=2, coalesce_ms=1)
    recorder.start()
    assert recorder.submit("FLOW_PROJECTION", {"packet_receive_ns": time.perf_counter_ns()}, "one")
    assert recorder.submit("FLOW_PROJECTION", {"packet_receive_ns": time.perf_counter_ns()}, "two")
    recorder.stop()
    health = recorder.health()
    assert health["metrics_schema"] == "ORDER_FLOW_RECORDER_METRICS_V2"
    assert health["accounting_identity"] == "ENQUEUED = WRITTEN + QUEUED + IN_FLIGHT + DROPPED"
    assert health["accounting_valid"] is True
    assert health["enqueue_count"] == 2
    assert health["write_count"] == 2
    assert health["queue_depth"] == health["in_flight"] == health["dropped_count"] == 0
    assert health["fsync_count"] >= 1
    assert health["durable_write_completions"] >= 1
    persisted = json.loads((tmp_path / "recorder_health.json").read_text())
    assert persisted["oldest_queue_age_ms"] == 0.0
    assert persisted["accounting_valid"] is True
    for metric in ("receive_to_enqueue", "queue_wait", "serialization", "write", "receive_to_durable"):
        assert metric in persisted["persistence_latency_ms"]


def test_recorder_health_can_snapshot_during_concurrent_metric_writes(tmp_path):
    recorder = OrderFlowEvidenceRecorder(tmp_path, queue_size=4096, batch_size=16, coalesce_ms=1)
    recorder.start()
    finished = Event()
    writing = Event()
    allow_finish = Event()

    def submitter():
        for index in range(500):
            recorder.submit("FLOW_PROJECTION", {"packet_receive_ns": time.perf_counter_ns()}, str(index))
            if index == 0:
                writing.set()
                allow_finish.wait(timeout=1.0)
        finished.set()

    worker = Thread(target=submitter)
    worker.start()
    assert writing.wait(timeout=1.0)
    snapshots = 0
    while snapshots < 1:
        value = recorder.health()
        assert value["RECORDER_LAST_ERROR"] is None
        snapshots += 1
    allow_finish.set()
    while not finished.is_set():
        value = recorder.health()
        assert value["RECORDER_LAST_ERROR"] is None
        snapshots += 1
    worker.join(timeout=1.0)
    recorder.stop()
    health = recorder.health()
    assert snapshots >= 1
    assert health["worker_last_error"] is None
    assert health["RECORDER_DROPS"] == 0
    assert health["write_count"] == 500


def test_recorder_worker_failure_is_explicitly_visible(tmp_path):
    recorder = OrderFlowEvidenceRecorder(tmp_path)
    recorder._record_worker_error(RuntimeError("fixture failure"), fatal=True)
    health = recorder.health()
    assert health["RECORDER_ALIVE"] is False
    assert health["RECORDER_LAST_ERROR"].startswith("RuntimeError:")
