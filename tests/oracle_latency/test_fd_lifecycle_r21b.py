"""R2.1B regression gates for bounded parent descriptors and cached health."""

from __future__ import annotations

import gc
import os
import threading
import time
from pathlib import Path

import pytest

from src.oracle.isolated_flow_worker import IsolatedOrderFlowWorker
from src.oracle.isolated_market_data_gateway import IsolatedMarketDataGateway
from src.strategy_lab.storage import ImmutableStream


class _RecorderStub:
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def read_paper_session(self, _session_id: str) -> list[dict]:
        return []

    def health(self) -> dict:
        return {"status": "READY"}


def _fd_count() -> int:
    if not os.path.isdir("/dev/fd"):
        pytest.skip("descriptor accounting requires /dev/fd")
    return len(os.listdir("/dev/fd"))


def test_isolated_proxies_share_scalar_ipc_locks_instead_of_one_semaphore_each():
    start = _fd_count()
    gateway = IsolatedMarketDataGateway(client_id="x", access_token="y")
    worker = IsolatedOrderFlowWorker(recorder=_RecorderStub())
    allocated = _fd_count() - start

    # Before R2.1B the same two singleton proxies allocated 97 descriptors on
    # macOS before either child started.  Queue capacity/semantics are retained;
    # only scalar telemetry counters and flags share synchronization now.
    assert allocated <= 75

    del worker
    del gateway
    gc.collect()
    deadline = time.monotonic() + 1.0
    while _fd_count() > start + 4 and time.monotonic() < deadline:
        gc.collect()
        time.sleep(0.01)
    assert _fd_count() <= start + 4


def test_flow_health_snapshots_mutable_rate_windows_under_lock():
    worker = IsolatedOrderFlowWorker(recorder=_RecorderStub())
    completed = threading.Event()
    result: list[dict] = []

    worker._metrics_lock.acquire()
    try:
        thread = threading.Thread(target=lambda: (result.append(worker.health()), completed.set()))
        thread.start()
        time.sleep(0.03)
        assert completed.is_set() is False
    finally:
        worker._metrics_lock.release()
    thread.join(timeout=1.0)

    assert completed.is_set() is True
    assert result[0]["FLOW_INPUT_RATE"] == 0.0


def test_repeated_flow_health_reads_do_not_allocate_descriptors():
    worker = IsolatedOrderFlowWorker(recorder=_RecorderStub())
    start = _fd_count()
    for _ in range(1_000):
        health = worker.health()
        assert health["FLOW_REQUIRED_DROPS"] == 0
    assert _fd_count() == start


def test_immutable_stream_checkpoint_handles_are_bounded_and_closeable(tmp_path: Path):
    start = _fd_count()
    streams = [ImmutableStream(tmp_path / f"stream-{index}.jsonl") for index in range(64)]

    for index, stream in enumerate(streams):
        stream.append("TEST", {"index": index}, idempotency_key=f"row-{index}")

    open_connections = sum(stream._checkpoint is not None for stream in streams)
    after_activation = _fd_count()
    assert open_connections <= ImmutableStream.CHECKPOINT_CONNECTION_CACHE_LIMIT
    # SQLite WAL uses up to three descriptors per active checkpoint. Allow a
    # small platform margin, but reject the prior one-triplet-per-stream growth.
    assert after_activation - start <= (
        ImmutableStream.CHECKPOINT_CONNECTION_CACHE_LIMIT * 3 + 12
    )

    for stream in streams:
        stream.close()
    assert _fd_count() <= start + 4
