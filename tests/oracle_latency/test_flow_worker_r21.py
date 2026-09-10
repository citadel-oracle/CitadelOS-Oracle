"""R2.1 complete-compute gates for the dedicated lossless Flow worker."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from src.broker.dhan_full_packet import DhanFullPacketDecoder
from src.oracle.isolated_flow_worker import IsolatedOrderFlowWorker
from src.order_flow.contracts import InstrumentIdentity
from src.order_flow.recorder import OrderFlowEvidenceRecorder
from src.order_flow.service import OrderFlowService

from tests.order_flow.helpers import full_packet, identity


def _identities() -> tuple[InstrumentIdentity, ...]:
    values = [identity("43210", "NIFTY_FUTURE")]
    for offset, strike in enumerate(range(24400, 24650, 50), start=1):
        values.append(identity(str(43210 + offset), f"NIFTY_{strike}_CE", "CE", float(strike)))
        values.append(identity(str(43310 + offset), f"NIFTY_{strike}_PE", "PE", float(strike)))
    return tuple(values)


def _tick(index: int, identities: tuple[InstrumentIdentity, ...]) -> dict[str, Any]:
    instrument = identities[index % len(identities)]
    security_id = int(instrument.security_id)
    packet = full_packet(
        security_id=security_id,
        ltp=24_500.0 + (index % 17) * 0.05 if instrument.option_type is None else 100.0 + (index % 13) * 0.05,
        ltt=1_786_083_900 + index,
        volume=1_000 + index,
        oi=50_000 + index,
    )
    value = DhanFullPacketDecoder.decode_packet(packet).to_dict()
    receive_ns = time.perf_counter_ns()
    value.update({
        "feed_generation": 1,
        "feed_receive_ns": receive_ns,
        "decode_done_ns": receive_ns + 10_000,
        "receive_wall_utc": "2026-08-07T04:45:00+00:00",
        "transport_gap_count": 0,
    })
    return value


def _wait_processed(worker: IsolatedOrderFlowWorker, expected: int, timeout: float = 10.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    health = worker.health()
    while int(health.get("FLOW_INPUT_PROCESSED") or 0) < expected and time.monotonic() < deadline:
        time.sleep(0.02)
        health = worker.health()
    assert int(health.get("FLOW_INPUT_PROCESSED") or 0) >= expected, health
    return health


def _semantic_projection(value: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "formula_version", "revision", "snapshot_id", "session_id", "call_strength",
        "put_strength", "directional_score", "directional_state", "action_eligible",
        "action_lock_reasons", "family_values", "confidence", "data_quality",
        "signed_flow_coverage", "profile_coverage", "reversal_state", "profile",
    )
    return {key: value.get(key) for key in keep}


def test_dedicated_worker_matches_accepted_flow_semantics(tmp_path: Path):
    identities = _identities()
    captured = [_tick(index, identities) for index in range(132)]
    accepted = OrderFlowService()
    accepted.register_instruments(identities)
    for value in captured:
        accepted.ingest_tick(value)

    recorder = OrderFlowEvidenceRecorder(tmp_path / "evidence")
    recorder.register_instruments(identities)
    worker = IsolatedOrderFlowWorker(recorder=recorder)
    worker.register_instruments(identities)
    worker.start()
    try:
        for value in captured:
            assert worker.ingest_tick(value)
        health = _wait_processed(worker, len(captured))
        deadline = time.monotonic() + 2.0
        actual = worker.latest_projection()
        while actual.get("revision") != len(captured) and time.monotonic() < deadline:
            time.sleep(0.02)
            actual = worker.latest_projection()
        assert _semantic_projection(actual) == _semantic_projection(accepted.latest_projection())
        assert health["FLOW_REQUIRED_DROPS"] == 0
        assert health["FLOW_WORKER_ALIVE"] is True
        assert health["FLOW_WORKER_PID"] != __import__("os").getpid()
    finally:
        worker.stop()


@pytest.mark.parametrize("rate", [14, 28], ids=["realistic_1x", "observed_2x"])
def test_complete_flow_worker_sustains_paced_load_without_age_drift(tmp_path: Path, rate: int):
    identities = _identities()
    recorder = OrderFlowEvidenceRecorder(tmp_path / f"evidence-{rate}")
    recorder.register_instruments(identities)
    worker = IsolatedOrderFlowWorker(recorder=recorder)
    worker.register_instruments(identities)
    worker.start()
    try:
        packet_count = rate * 3
        started = time.monotonic()
        for index in range(packet_count):
            assert worker.ingest_tick(_tick(index, identities))
            target = started + (index + 1) / rate
            remaining = target - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
        health = _wait_processed(worker, packet_count)
        ages = health["FLOW_QUEUE_AGE_MS"]
        assert health["FLOW_REQUIRED_DROPS"] == 0
        assert health["FLOW_PROCESSING_DEBT"] == 0
        assert float(ages["p99"] or 0) < 250.0
        assert float(ages["max"] or 0) < 500.0
    finally:
        worker.stop()


def test_five_x_burst_drains_without_required_loss(tmp_path: Path):
    identities = _identities()
    recorder = OrderFlowEvidenceRecorder(tmp_path / "evidence-burst")
    recorder.register_instruments(identities)
    worker = IsolatedOrderFlowWorker(recorder=recorder)
    worker.register_instruments(identities)
    worker.start()
    try:
        packet_count = 14 * 5 * 3
        for index in range(packet_count):
            assert worker.ingest_tick(_tick(index, identities))
        health = _wait_processed(worker, packet_count)
        assert health["FLOW_REQUIRED_DROPS"] == 0
        assert health["FLOW_PROCESSING_DEBT"] == 0
        assert health["FLOW_OLDEST_UNPROCESSED_AGE_MS"] == 0.0
    finally:
        worker.stop()


class _SlowDerivedRecorder(OrderFlowEvidenceRecorder):
    def submit(self, event_type: str, payload: dict[str, Any], key: str) -> bool:
        time.sleep(0.02)
        return super().submit(event_type, payload, key)


def test_parent_and_recorder_stalls_do_not_stall_flow_compute(tmp_path: Path):
    identities = _identities()
    recorder = _SlowDerivedRecorder(tmp_path / "evidence-stall")
    recorder.register_instruments(identities)
    worker = IsolatedOrderFlowWorker(recorder=recorder)
    worker.register_instruments(identities)
    worker.subscribe_flow_pulse(lambda _kind, _payload: time.sleep(0.03))
    worker.start()
    try:
        packet_count = 140
        for index in range(packet_count):
            assert worker.ingest_tick(_tick(index, identities))
        health = _wait_processed(worker, packet_count)
        assert health["FLOW_REQUIRED_DROPS"] == 0
        assert health["FLOW_PROCESSING_DEBT"] == 0
        assert int(health["FLOW_METER_COALESCES"]) > 0
    finally:
        worker.stop()


def test_worker_death_is_fail_closed_without_stopping_recorder(tmp_path: Path):
    identities = _identities()
    recorder = OrderFlowEvidenceRecorder(tmp_path / "evidence-death")
    recorder.register_instruments(identities)
    worker = IsolatedOrderFlowWorker(recorder=recorder)
    worker.register_instruments(identities)
    worker.start()
    process = worker._process
    assert process is not None
    process.terminate()
    process.join(timeout=2.0)
    projection = worker.latest_projection()
    assert worker.health()["FLOW_WORKER_ALIVE"] is False
    assert recorder.health()["RECORDER_ALIVE"] is True
    assert projection.get("status") == "UNAVAILABLE" or "FLOW_WORKER_UNAVAILABLE" in projection["action_lock_reasons"]
    worker.stop()


def test_cold_session_missing_journal_completes_recovery_and_publishes_live_flow(tmp_path: Path):
    identities = _identities()
    recorder = OrderFlowEvidenceRecorder(tmp_path / "evidence-cold-session")
    recorder.register_instruments(identities)
    worker = IsolatedOrderFlowWorker(recorder=recorder)
    worker.register_instruments(identities)
    worker.start()
    try:
        worker.begin_recovery()
        recovery = worker.restore_flow_pulse_journal(
            tmp_path / "missing-session.jsonl",
            checkpoint_path=tmp_path / "missing-checkpoint.pickle",
        )
        assert recovery["recovery_complete"] is True
        assert recovery["live_tail_attached"] is True

        assert worker.ingest_tick(_tick(0, identities))
        _wait_processed(worker, 1)
        projection = _wait_processed_projection(worker)
        assert projection.get("revision") == 1
        assert projection.get("reason") != "ORDER_FLOW_PROJECTION_NOT_READY"
    finally:
        worker.stop()


def _wait_processed_projection(worker: IsolatedOrderFlowWorker, timeout: float = 2.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    projection = worker.latest_projection()
    while projection.get("revision") is None and time.monotonic() < deadline:
        time.sleep(0.02)
        projection = worker.latest_projection()
    return projection
