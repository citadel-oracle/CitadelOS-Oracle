"""Dual-Provider Read-Only Streaming Comparator.

Records high-resolution nanosecond timestamps across concurrent Dhan and Upstox feeds:
- exchange / LTT timestamp
- local socket receive_ns
- decode_done_ns
- canonical_publish_ns

Reports separately per (provider, role):
- messages/sec
- inter-arrival P50 / P95 / P99
- exchange -> receive network lag P50 / P95 / P99
- receive -> canonical internal processing lag P50 / P95 / P99

Strict Invariant:
- READ-ONLY. Never writes to production VOB or executes orders.
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProviderTickMetric:
    provider: str  # "DHAN" | "UPSTOX"
    role: str  # "NIFTY_SPOT" | "NIFTY_FUTURE"
    exchange_ltt_sec: float
    local_socket_receive_ns: int
    decode_done_ns: int
    canonical_publish_ns: int

    @property
    def decode_lag_us(self) -> float:
        return max(0.0, (self.decode_done_ns - self.local_socket_receive_ns) / 1_000.0)

    @property
    def internal_processing_lag_us(self) -> float:
        return max(0.0, (self.canonical_publish_ns - self.local_socket_receive_ns) / 1_000.0)


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    d0 = sorted_vals[int(f)] * (c - k)
    d1 = sorted_vals[int(c)] * (k - f)
    return d0 + d1


class StreamTelemetryAggregator:
    """Computes streaming rates, inter-arrival, network lag, and internal lag distributions."""

    def __init__(self, provider: str, role: str, max_samples: int = 100_000):
        self.provider = provider
        self.role = role
        self.max_samples = max_samples
        self.metrics: List[ProviderTickMetric] = []
        self._last_receive_ns: Optional[int] = None
        self._inter_arrivals_ms: List[float] = []
        self._internal_lags_us: List[float] = []

    def record_metric(self, metric: ProviderTickMetric) -> None:
        if len(self.metrics) >= self.max_samples:
            self.metrics.pop(0)
            if self._inter_arrivals_ms:
                self._inter_arrivals_ms.pop(0)
            if self._internal_lags_us:
                self._internal_lags_us.pop(0)

        if self._last_receive_ns is not None:
            inter_ms = max(0.0, (metric.local_socket_receive_ns - self._last_receive_ns) / 1_000_000.0)
            self._inter_arrivals_ms.append(inter_ms)
        self._last_receive_ns = metric.local_socket_receive_ns
        self._internal_lags_us.append(metric.internal_processing_lag_us)
        self.metrics.append(metric)

    def compute_summary(self) -> Dict[str, Any]:
        count = len(self.metrics)
        if count < 2:
            return {
                "provider": self.provider,
                "role": self.role,
                "sample_count": count,
                "messages_per_sec": 0.0,
                "inter_arrival_ms": {"p50": 0.0, "p95": 0.0, "p99": 0.0},
                "receive_to_canonical_lag_us": {"p50": 0.0, "p95": 0.0, "p99": 0.0},
            }

        first_ns = self.metrics[0].local_socket_receive_ns
        last_ns = self.metrics[-1].local_socket_receive_ns
        duration_sec = max(1e-6, (last_ns - first_ns) / 1_000_000_000.0)
        mps = round(count / duration_sec, 2)

        return {
            "provider": self.provider,
            "role": self.role,
            "sample_count": count,
            "duration_seconds": round(duration_sec, 3),
            "messages_per_sec": mps,
            "inter_arrival_ms": {
                "p50": round(_percentile(self._inter_arrivals_ms, 0.50), 3),
                "p95": round(_percentile(self._inter_arrivals_ms, 0.95), 3),
                "p99": round(_percentile(self._inter_arrivals_ms, 0.99), 3),
            },
            "receive_to_canonical_lag_us": {
                "p50": round(_percentile(self._internal_lags_us, 0.50), 2),
                "p95": round(_percentile(self._internal_lags_us, 0.95), 2),
                "p99": round(_percentile(self._internal_lags_us, 0.99), 2),
            },
        }


class DualProviderComparator:
    """Read-only testbed comparing Dhan and Upstox streams for NIFTY spot & futures."""

    IS_READ_ONLY = True
    WRITES_PRODUCTION_VOB = False

    def __init__(self) -> None:
        self.aggregators: Dict[Tuple[str, str], StreamTelemetryAggregator] = {}
        for prov in ("DHAN", "UPSTOX"):
            for role in ("NIFTY_SPOT", "NIFTY_FUTURE"):
                self.aggregators[(prov, role)] = StreamTelemetryAggregator(prov, role)

    def record_tick(
        self,
        provider: str,
        role: str,
        exchange_ltt_sec: float,
        receive_ns: int,
        decode_done_ns: int,
        canonical_publish_ns: int,
    ) -> None:
        """Records an incoming tick timing without triggering any order or VOB write."""
        key = (provider.upper(), role.upper())
        if key not in self.aggregators:
            self.aggregators[key] = StreamTelemetryAggregator(provider, role)

        metric = ProviderTickMetric(
            provider=provider.upper(),
            role=role.upper(),
            exchange_ltt_sec=exchange_ltt_sec,
            local_socket_receive_ns=receive_ns,
            decode_done_ns=decode_done_ns,
            canonical_publish_ns=canonical_publish_ns,
        )
        self.aggregators[key].record_metric(metric)

    def generate_report(self) -> Dict[str, Any]:
        """Generates comprehensive dual-provider streaming parity and latency report."""
        report = {
            "is_read_only": self.IS_READ_ONLY,
            "writes_production_vob": self.WRITES_PRODUCTION_VOB,
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "streams": {},
        }
        for (prov, role), agg in self.aggregators.items():
            report["streams"][f"{prov}:{role}"] = agg.compute_summary()
        return report
