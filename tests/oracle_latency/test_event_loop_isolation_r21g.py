from __future__ import annotations

import asyncio
import threading
import time

from src.api.event_loop_watchdog import EventLoopWatchdog
from src.oracle.isolated_market_data_gateway import IsolatedMarketDataGateway


def test_event_loop_watchdog_records_a_bounded_stall_signature():
    async def exercise():
        monitor = EventLoopWatchdog(
            interval_seconds=0.01,
            capture_cooldown_seconds=1.0,
        )
        monitor.start()
        await asyncio.sleep(0.03)
        time.sleep(0.08)
        await asyncio.sleep(0.05)
        snapshot = monitor.snapshot()
        await monitor.stop()
        return snapshot

    snapshot = asyncio.run(exercise())

    assert snapshot["status"] == "RUNNING"
    assert snapshot["stall_counts"]["over_50ms"] >= 1
    assert snapshot["lag_ms"]["max"] >= 50.0
    assert snapshot["recent_stalls"] == []  # stack capture starts at 250 ms


def test_transport_snapshot_does_not_calculate_parent_lane_distributions():
    gateway = object.__new__(IsolatedMarketDataGateway)
    gateway._state_lock = threading.RLock()
    gateway._health = {
        "BASKET_HEALTH": "LIVE",
        "FRESH_INSTRUMENTS": 11,
        "instruments": [{"security_id": "58072", "role": "NIFTY_FUTURE"}],
    }
    gateway._drain_health = lambda: None

    value = gateway.transport_snapshot()
    value["instruments"][0]["security_id"] = "mutated"

    assert gateway._health["instruments"][0]["security_id"] == "58072"
    assert "PARENT_DATA_PLANE" not in value
