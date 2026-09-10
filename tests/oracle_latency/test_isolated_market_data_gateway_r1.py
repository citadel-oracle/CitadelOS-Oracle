"""R1 process-boundary tests without making a provider connection."""

from __future__ import annotations

import time

from src.oracle.isolated_market_data_gateway import IsolatedMarketDataGateway


def _tick(index: int) -> dict:
    return {
        "exchange_segment": "NSE_FNO",
        "security_id": str(index),
        "response_code": 8,
        "cumulative_volume": index,
    }


def test_parent_proxy_reports_no_socket_owner_until_child_is_started():
    gateway = IsolatedMarketDataGateway(client_id="x", access_token="y")
    gateway.subscribe([{"exchange_segment": "NSE_FNO", "security_id": "58072", "role": "NIFTY_FUTURE"}])

    health = gateway.health()

    assert health["ISOLATION_TIER"] == "SEPARATE_PROCESS"
    assert health["WS_OWNER_COUNT"] == 0
    assert health["EXPECTED_INSTRUMENTS"] == 1


def test_slow_parent_analytics_cannot_block_child_to_parent_ipc_handoff():
    received: list[str] = []

    def slow_tick(tick: dict) -> None:
        time.sleep(0.15)
        received.append(str(tick["security_id"]))

    gateway = IsolatedMarketDataGateway(client_id="x", access_token="y", on_tick=slow_tick)
    gateway._parent_stop.clear()
    gateway._start_parent_dispatch()
    try:
        started = time.perf_counter()
        for index in range(12):
            gateway._analytical_ticks.put_nowait(_tick(index + 1))
        enqueue_ms = (time.perf_counter() - started) * 1_000.0
        # A producer on the child side only puts to IPC.  Slow parent work is
        # allowed to queue, but cannot make the producer wait on the callback.
        assert enqueue_ms < 75.0
        assert len(received) <= 1
    finally:
        gateway._parent_stop.set()
        for thread in (gateway._raw_thread, gateway._tick_thread, gateway._transport_thread):
            if thread is not None:
                thread.join(timeout=1.0)


def test_child_health_sample_is_a_cached_parent_read():
    gateway = IsolatedMarketDataGateway(client_id="x", access_token="y")
    gateway._health_samples.put_nowait({
        "status": "UP",
        "WS_CONNECTED": True,
        "CONNECTION_GENERATION": 4,
        "FRESH_INSTRUMENTS": 11,
        "BASKET_HEALTH": "FULLY_FRESH",
    })

    started = time.perf_counter()
    snapshots = [gateway.health() for _ in range(100)]
    elapsed_ms = (time.perf_counter() - started) * 1_000.0

    assert elapsed_ms < 100.0
    assert snapshots[-1]["CONNECTION_GENERATION"] == 4
    assert snapshots[-1]["WS_CONNECTED"] is True
    assert snapshots[-1]["WS_OWNER_COUNT"] == 0
