#!/usr/bin/env python3
"""Bounded synthetic/replay latency acceptance for canonical order flow."""

from __future__ import annotations

import json
import resource
import struct
import time

from src.broker.dhan_full_packet import DhanFullPacketDecoder
from src.order_flow.contracts import InstrumentIdentity
from src.order_flow.replay import OrderFlowReplayHarness
from src.order_flow.service import OrderFlowService


def packet(index: int) -> bytes:
    value = bytearray(162)
    ltp = 24500.0 + (index % 17) * 0.05
    bid = ltp - 0.05
    ask = ltp
    struct.pack_into("<BHBi", value, 0, 8, 162, 2, 43210)
    struct.pack_into("<fHIfIII", value, 8, ltp, 1 + index % 20, 1786083900 + index, ltp - 0.1, 1000 + index, 40_000, 50_000)
    struct.pack_into("<IIIffff", value, 34, 100_000, 101_000, 99_000, ltp - 2, ltp - 1, ltp + 2, ltp - 3)
    for level in range(5):
        struct.pack_into("<IIHHff", value, 62 + level * 20, 500 + (index % 40) - level, 450 - level, 10, 9, bid - level * 0.05, ask + level * 0.05)
    return bytes(value)


def main(count: int = 10_000) -> None:
    identity = InstrumentIdentity("NSE_FNO", "43210", "NIFTY_FUTURE", "2026-08-27")
    replay_packets = [packet(index) for index in range(400)]
    first = OrderFlowReplayHarness((identity,)).run(replay_packets)
    second = OrderFlowReplayHarness((identity,)).run(replay_packets)

    service = OrderFlowService()
    service.register_instruments((identity,))
    rows = [packet(index) for index in range(count)]
    cpu_start = time.process_time()
    wall_start = time.perf_counter()
    rss_start = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    for raw in rows:
        receive_ns = time.perf_counter_ns()
        decoded = DhanFullPacketDecoder.decode_packet(raw).to_dict()
        decoded.update({
            "feed_generation": 1,
            "feed_receive_ns": receive_ns,
            "decode_done_ns": time.perf_counter_ns(),
            "receive_wall_utc": "2026-08-07T04:45:00+00:00",
            "transport_gap_count": 0,
        })
        service.ingest_tick(decoded)
    wall_seconds = time.perf_counter() - wall_start
    cpu_seconds = time.process_time() - cpu_start
    rss_end = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(json.dumps({
        "events": count,
        "replay_run_1": first["replay_hash"],
        "replay_run_2": second["replay_hash"],
        "replay_identical": first["replay_hash"] == second["replay_hash"],
        "latency": service.telemetry()["stages_ms"],
        "wall_seconds": round(wall_seconds, 6),
        "events_per_second": round(count / wall_seconds, 2),
        "cpu_seconds": round(cpu_seconds, 6),
        "cpu_percent_one_core": round(cpu_seconds / wall_seconds * 100, 2),
        "max_rss_start": rss_start,
        "max_rss_end": rss_end,
        "max_rss_delta": max(0, rss_end - rss_start),
        "execution_influence": "ZERO",
    }, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
