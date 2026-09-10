"""R1: prove downstream work cannot run on the Dhan receive loop."""

from __future__ import annotations

import queue
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.oracle.market_data_gateway import MarketDataGateway


def _tick(index: int = 1) -> dict:
    return {
        "exchange_segment": 2,
        "security_id": str(index),
        "response_code": 8,
        "cumulative_volume": index,
        "decode_done_ns": time.perf_counter_ns(),
    }


@pytest.mark.parametrize("consumer_name", ["fast_lane", "argus", "flow", "forecast"])
def test_slow_downstream_consumer_cannot_block_receive_handoff(consumer_name: str):
    consumed: list[str] = []

    def slow_consumer(_: dict) -> None:
        time.sleep(0.15)
        consumed.append(consumer_name)

    gateway = MarketDataGateway(on_tick=slow_consumer, queue_size=16)
    gateway._start_dispatch_workers()
    try:
        started = time.perf_counter()
        for index in range(12):
            gateway._enqueue_tick(_tick(index + 1))
        handoff_ms = (time.perf_counter() - started) * 1_000.0
        # The fanout worker is deliberately sleeping.  A receive handler must
        # still return in bounded time rather than wait on its callback chain.
        assert handoff_ms < 75.0
        assert gateway._tick_queue.qsize() >= 1
        time.sleep(0.02)
        assert gateway.health()["FANOUT_CALLBACK_FAILURES"] == 0
    finally:
        gateway._stop_dispatch_workers()


def test_slow_recorder_callback_cannot_block_raw_receive_handoff():
    raw_received: list[str] = []

    def slow_recorder(tick: dict) -> None:
        time.sleep(0.15)
        raw_received.append(str(tick["security_id"]))

    gateway = MarketDataGateway(on_raw_packet=slow_recorder, queue_size=16)
    gateway._start_dispatch_workers()
    try:
        started = time.perf_counter()
        for index in range(12):
            gateway._enqueue_tick(_tick(index + 1))
        handoff_ms = (time.perf_counter() - started) * 1_000.0
        assert handoff_ms < 75.0
        assert gateway.health()["RECORDER_INGRESS_QUEUE_DEPTH"] >= 1
    finally:
        gateway._stop_dispatch_workers()


def test_recorder_ingress_pressure_is_explicit_while_receive_handoff_survives():
    gateway = MarketDataGateway(on_raw_packet=lambda _: None, queue_size=16)
    gateway._recorder_queue = queue.Queue(maxsize=1)
    gateway._enqueue_tick(_tick(1))
    gateway._enqueue_tick(_tick(2))

    health = gateway.health()
    assert health["RECORDER_INGRESS_DROPS"] == 1
    assert gateway._tick_queue.qsize() == 2


@pytest.mark.asyncio
async def test_old_generation_cannot_clear_or_resubscribe_new_socket():
    gateway = MarketDataGateway(client_id="x", access_token="y")
    old_ws = AsyncMock()
    new_ws = AsyncMock()
    gateway.ws = new_ws
    gateway._generation = 2
    gateway._receive_loop_alive = True
    gateway.subscribe([{"exchange_segment": "NSE_FNO", "security_id": "58072"}])

    gateway._finish_generation(old_ws, 1)
    await gateway._send_subscriptions(ws=old_ws, generation=1)

    assert gateway.ws is new_ws
    assert gateway.health()["CONNECTION_GENERATION"] == 2
    assert gateway.health()["RECEIVE_LOOP_ALIVE"] is True
    assert old_ws.send.await_count == 0


def test_runtime_diagnostic_is_cached_state_only_and_includes_r1_boundaries():
    gateway = MarketDataGateway(client_id="x", access_token="y")
    gateway.ws = SimpleNamespace(closed=False, latency=0.012)
    gateway._generation = 3
    gateway._connection_state = "LIVE"

    started = time.perf_counter()
    snapshots = [gateway.health() for _ in range(100)]
    elapsed_ms = (time.perf_counter() - started) * 1_000.0

    assert elapsed_ms < 100.0
    snapshot = snapshots[-1]
    assert snapshot["CONNECTION_GENERATION"] == 3
    assert snapshot["DHAN_CONNECTION_STATE"] == "LIVE"
    assert snapshot["PONG_LATENCY_MS"] == 12.0
    assert set(snapshot["EVENT_LOOP_LAG_MS"]) == {"count", "p50", "p95", "p99", "max"}
