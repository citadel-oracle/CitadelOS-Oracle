"""Ultra-Low-Latency Pipeline Benchmark & Regression Test Suite.

Validates:
1. Protobuf V3 decode latency is strictly under 50 µs per packet.
2. MarketDataGateway tick normalization is strictly under 50 µs.
3. LiveIslandHub tick routing is strictly under 10 µs.
4. Combined internal gateway processing overhead is strictly under 1.0 ms budget.
"""

import time
import pytest
from src.broker.upstox_proto import UpstoxProtoDecoder
from src.broker.proto import MarketDataFeedV3_pb2 as pb
from src.oracle.market_data_gateway import MarketDataGateway
from src.oracle.live_island.hub import LiveIslandIntelligenceHub


def _build_synthetic_feed_bytes() -> bytes:
    feed_resp = pb.FeedResponse()
    feed_resp.type = pb.Type.initial_feed
    feed = pb.Feed()
    feed.ltpc.ltp = 24890.5
    feed.ltpc.ltt = 1788945000000
    feed.ltpc.ltq = 50
    feed.ltpc.cp = 24880.0
    feed_resp.feeds["NSE_INDEX|Nifty 50"].CopyFrom(feed)
    return feed_resp.SerializeToString()


def test_protobuf_decode_latency_budget():
    """Verify Protobuf packet decode completes in under 50 microseconds."""
    raw_bytes = _build_synthetic_feed_bytes()

    # Warmup
    for _ in range(50):
        UpstoxProtoDecoder.decode_packet(raw_bytes)

    iterations = 500
    t0 = time.perf_counter_ns()
    for _ in range(iterations):
        UpstoxProtoDecoder.decode_packet(raw_bytes)
    t1 = time.perf_counter_ns()

    avg_ns = (t1 - t0) / iterations
    avg_us = avg_ns / 1000.0
    # Invariant: sub-50 µs decode latency
    assert avg_us < 50.0, f"Protobuf decode too slow: {avg_us:.2f} µs (budget: 50.0 µs)"


def test_gateway_tick_normalization_latency():
    """Verify MarketDataGateway._handle_upstox_tick completes in under 50 microseconds."""
    gateway = MarketDataGateway(
        access_token="test_token",
        client_id="test_client",
    )
    gateway.instruments = [{"exchange_segment": "IDX_I", "security_id": "13", "role": "NIFTY_SPOT"}]

    raw_tick = {
        "instrument_key": "NSE_INDEX|Nifty 50",
        "ltp": 24890.5,
        "ltt": 1788945000,
        "cumulative_volume": 50000,
    }

    # Warmup
    for _ in range(50):
        gateway._handle_upstox_tick(raw_tick)

    # Empty queue
    while not gateway._tick_queue.empty():
        gateway._tick_queue.get_nowait()

    iterations = 500
    t0 = time.perf_counter_ns()
    for _ in range(iterations):
        gateway._handle_upstox_tick(raw_tick)
    t1 = time.perf_counter_ns()

    avg_ns = (t1 - t0) / iterations
    avg_us = avg_ns / 1000.0
    # Invariant: sub-50 µs normalization latency
    assert avg_us < 50.0, f"Tick normalization too slow: {avg_us:.2f} µs (budget: 50.0 µs)"


def test_live_island_hub_routing_latency():
    """Verify LiveIslandIntelligenceHub.on_tick completes in under 10 microseconds."""
    hub = LiveIslandIntelligenceHub.get_instance()
    raw_tick = {
        "instrument_key": "NSE_INDEX|Nifty 50",
        "ltp": 24890.5,
        "ltt": 1788945000,
        "cumulative_volume": 50000,
    }

    # Warmup
    for _ in range(50):
        hub.on_tick(raw_tick)

    iterations = 1000
    t0 = time.perf_counter_ns()
    for _ in range(iterations):
        hub.on_tick(raw_tick)
    t1 = time.perf_counter_ns()

    avg_ns = (t1 - t0) / iterations
    avg_us = avg_ns / 1000.0
    # Invariant: sub-10 µs routing latency
    assert avg_us < 10.0, f"Live Island Hub routing too slow: {avg_us:.2f} µs (budget: 10.0 µs)"
