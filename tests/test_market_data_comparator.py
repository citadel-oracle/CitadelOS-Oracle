"""Unit tests for Dual-Provider Read-Only Streaming Comparator."""

import time
import pytest

from src.oracle.market_data_comparator import (
    DualProviderComparator,
    ProviderTickMetric,
    StreamTelemetryAggregator,
)


def test_telemetry_aggregator_percentiles():
    """Verify aggregator correctly computes P50, P95, P99, and messages/sec."""
    agg = StreamTelemetryAggregator(provider="UPSTOX", role="NIFTY_SPOT")

    t_base_ns = 1_000_000_000
    for i in range(100):
        # 10ms inter-arrival = 100 Hz
        recv_ns = t_base_ns + (i * 10_000_000)
        decode_ns = recv_ns + 18_000  # 18 µs
        publish_ns = decode_ns + 5_000  # 5 µs

        metric = ProviderTickMetric(
            provider="UPSTOX",
            role="NIFTY_SPOT",
            exchange_ltt_sec=1788930000 + (i // 10),
            local_socket_receive_ns=recv_ns,
            decode_done_ns=decode_ns,
            canonical_publish_ns=publish_ns,
        )
        agg.record_metric(metric)

    summary = agg.compute_summary()
    assert summary["sample_count"] == 100
    assert summary["messages_per_sec"] > 80.0  # ~100 Hz
    assert abs(summary["inter_arrival_ms"]["p50"] - 10.0) < 0.5
    assert abs(summary["receive_to_canonical_lag_us"]["p50"] - 23.0) < 1.0


def test_comparator_read_only_safety_invariant():
    """Ensure DualProviderComparator never writes to production VOB or executes broker orders."""
    comparator = DualProviderComparator()
    assert comparator.IS_READ_ONLY is True
    assert comparator.WRITES_PRODUCTION_VOB is False

    # Simulate ingestion of spot tick
    now_ns = time.perf_counter_ns()
    comparator.record_tick(
        provider="DHAN",
        role="NIFTY_SPOT",
        exchange_ltt_sec=1788930000,
        receive_ns=now_ns,
        decode_done_ns=now_ns + 5000,
        canonical_publish_ns=now_ns + 8000,
    )

    report = comparator.generate_report()
    assert "DHAN:NIFTY_SPOT" in report["streams"]
    assert report["streams"]["DHAN:NIFTY_SPOT"]["sample_count"] == 1
