"""R2.1L regression gates for Flow telemetry eviction.

The tests deliberately mature the exact 20k/50k bounded windows that caused
R2.1K's duration-growing late-session debt.  Trading inputs/formulas are not
changed.
"""

from __future__ import annotations

import time
import threading
from pathlib import Path

from src.api.oracle_fast_lane import OracleFastLane
from src.oracle.isolated_execution_boundary import IsolatedExecutionBoundary
from src.oracle.isolated_flow_worker import IsolatedOrderFlowWorker
from src.order_flow.recorder import OrderFlowEvidenceRecorder
from src.order_flow.service import OrderFlowService
from tests.oracle_latency.test_flow_worker_r21 import (
    _identities,
    _semantic_projection,
    _tick,
)


def _latest_state_processor(kind, payload):
    return {"kind": kind, "payload": payload}


def _mature_windows(service: OrderFlowService) -> None:
    with service._telemetry_lock:
        for name in (
            "packet_to_raw",
            "raw_to_event",
            "event_to_payload",
            "packet_to_payload",
        ):
            service._latency[name].extend(float(index % 1000) for index in range(20_000))
    pulse = service.flow_pulse
    with pulse._telemetry_lock:
        pulse._latency_ns.extend(index % 1_000_000 for index in range(50_000))
        for name in (
            "profile_update",
            "microstructure_update",
            "semantic_commit",
            "episode_evaluation",
            "projection",
            "option_mapping",
            "payload_build",
            "candidate_validation",
        ):
            pulse._stage_latency_ns[name].extend(
                index % 1_000_000 for index in range(50_000)
            )


def test_one_hundred_same_revision_telemetry_reads_are_cache_only(monkeypatch):
    service = OrderFlowService()
    _mature_windows(service)

    monkeypatch.setattr(
        "src.order_flow.service._distribution",
        lambda _values: (_ for _ in ()).throw(
            AssertionError("cache read performed percentile calculation")
        ),
    )
    monkeypatch.setattr(
        service.flow_pulse,
        "telemetry",
        lambda: (_ for _ in ()).throw(
            AssertionError("cache read reached Flow Pulse windows")
        ),
    )

    first = service.telemetry()
    for _ in range(99):
        assert service.telemetry()["telemetry_refresh_count"] == 0
    assert first["telemetry_mode"] == "ASYNC_CACHED_EXACT"


def test_mature_exact_percentiles_refresh_off_packet_path():
    service = OrderFlowService()
    _mature_windows(service)

    value = service.refresh_telemetry()

    assert value["telemetry_mode"] == "ASYNC_CACHED_EXACT"
    assert value["telemetry_refresh_count"] == 1
    assert value["stages_ms"]["packet_to_payload"]["count"] == 20_000
    assert value["flow_pulse"]["count"] == 50_000
    assert value["flow_pulse"]["stages"]["candidate_validation"]["max_ms"] == 0.049999
    assert value["telemetry_last_error"] is None


def test_telemetry_failure_isolated_from_packet_processing(monkeypatch):
    identities = _identities()
    service = OrderFlowService()
    service.register_instruments(identities)
    service._telemetry_refresh_seconds = 0.01
    monkeypatch.setattr(
        service.flow_pulse,
        "telemetry",
        lambda: (_ for _ in ()).throw(RuntimeError("telemetry-only failure")),
    )
    service.start()
    try:
        for index in range(100):
            assert service.ingest_tick(_tick(index, identities)) is not None
        deadline = time.monotonic() + 1.0
        value = service.telemetry()
        while value["telemetry_last_error"] is None and time.monotonic() < deadline:
            time.sleep(0.01)
            value = service.telemetry()
        assert "RuntimeError:telemetry-only failure" == value["telemetry_last_error"]
        assert service.latest_projection()["revision"] == 100
    finally:
        service.stop()
    assert service._telemetry_thread is None


def test_mature_telemetry_does_not_cause_progressive_capacity_decay():
    identities = _identities()
    ticks = [_tick(index, identities) for index in range(601)]

    accepted = OrderFlowService()
    accepted.register_instruments(identities)
    for value in ticks:
        accepted.ingest_tick(value)

    service = OrderFlowService()
    service.register_instruments(identities)
    service.ingest_tick(ticks[0])
    _mature_windows(service)
    # Exercise more frequently than production's documented one-second cadence.
    service._telemetry_refresh_seconds = 0.05
    service.start()
    chunk_rates: list[float] = []
    try:
        for start in range(1, 601, 100):
            began = time.perf_counter()
            for value in ticks[start : start + 100]:
                service.ingest_tick(value)
            elapsed = time.perf_counter() - began
            chunk_rates.append(100.0 / elapsed)
        deadline = time.monotonic() + 2.0
        telemetry = service.telemetry()
        while telemetry["telemetry_refresh_count"] < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
            telemetry = service.telemetry()
    finally:
        service.stop()

    assert telemetry["telemetry_refresh_count"] >= 2
    assert telemetry["telemetry_thread_alive"] is True
    assert min(chunk_rates) > 27.2  # >= 2x the accepted 13.6 packet/s live peak
    assert chunk_rates[-1] >= chunk_rates[0] * 0.50
    assert _semantic_projection(service.latest_projection()) == _semantic_projection(
        accepted.latest_projection()
    )


def test_full_concurrent_topology_replay_has_no_required_loss_or_serving_debt(
    tmp_path: Path,
):
    identities = _identities()
    recorder = OrderFlowEvidenceRecorder(tmp_path / "evidence")
    recorder.register_instruments(identities)
    flow = IsolatedOrderFlowWorker(recorder=recorder)
    flow.register_instruments(identities)
    analytics = IsolatedExecutionBoundary(
        name="r21l-live-analytics",
        processor=_latest_state_processor,
        publish_interval_seconds=0.05,
    )
    strategy = IsolatedExecutionBoundary(
        name="r21l-strategy",
        processor=_latest_state_processor,
        publish_interval_seconds=0.05,
    )
    price_action = IsolatedExecutionBoundary(
        name="r21l-price-action",
        processor=_latest_state_processor,
        publish_interval_seconds=0.05,
    )
    lane = OracleFastLane(base_provider=lambda: {"feeds": {}}, providers={})
    http_reads = 0
    sse_reads = 0
    stop_readers = threading.Event()

    def http_reader() -> None:
        nonlocal http_reads
        while not stop_readers.is_set():
            try:
                lane.response()
                http_reads += 1
            except RuntimeError:
                pass
            time.sleep(0.001)

    def sse_reader() -> None:
        nonlocal sse_reads
        after = None
        while not stop_readers.is_set():
            events = lane.wait_for_events(after, 0.02)
            if events:
                after = events[-1]["event_id"]
                sse_reads += len(events)
            # A deliberately slow UI consumer must not create upstream debt.
            time.sleep(0.01)

    readers = [
        threading.Thread(target=http_reader, daemon=True),
        threading.Thread(target=sse_reader, daemon=True),
    ]
    try:
        lane.start()
        assert lane.publish_provider_value(
            "order_flow", {"revision": 0, "status": "AVAILABLE"}
        )
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            try:
                lane.response()
                break
            except RuntimeError:
                time.sleep(0.01)
        else:
            raise AssertionError("Fast Lane publisher did not produce initial snapshot")
        flow.subscribe_flow_pulse(lane.publish_flow_pulse)
        flow.start()
        analytics.start()
        strategy.start()
        price_action.start()
        for reader in readers:
            reader.start()
        packet_count = 350
        for index in range(packet_count):
            assert flow.ingest_tick(_tick(index, identities))
            if index < 40:
                assert analytics.submit("FLOW", index)
                assert strategy.submit("RESEARCH", index)
                assert price_action.submit("CHART", index)
        deadline = time.monotonic() + 12.0
        health = flow.health()
        while (
            int(health.get("FLOW_INPUT_PROCESSED") or 0) < packet_count
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
            health = flow.health()
        assert int(health.get("FLOW_INPUT_PROCESSED") or 0) == packet_count
        assert health["FLOW_PROCESSING_DEBT"] == 0
        assert health["FLOW_REQUIRED_DROPS"] == 0
        assert health["FLOW_TELEMETRY_THREAD_ALIVE"] is True
        for boundary in (analytics, strategy, price_action):
            deadline = time.monotonic() + 4.0
            while boundary.status()["processed"] < 40 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert boundary.status()["processed"] == 40
            assert boundary.status()["required_event_drops"] == 0
        assert recorder.health()["RECORDER_DROPS"] == 0
        assert http_reads > 0
        assert sse_reads > 0
        lane_health = lane.health()
        assert lane_health["full_builds"] >= 1
        assert lane_health["full_serializations"] == lane_health["full_builds"]
    finally:
        stop_readers.set()
        for reader in readers:
            reader.join(timeout=1.0)
        flow.stop()
        analytics.stop()
        strategy.stop()
        price_action.stop()
        lane.stop()
