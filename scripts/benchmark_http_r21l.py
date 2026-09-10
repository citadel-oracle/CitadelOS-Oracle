"""Bounded post-market HTTP cache-reuse benchmark for R2.1L."""

from __future__ import annotations

import json
import statistics
import time
import urllib.request


BASE = "http://127.0.0.1:8000"


def get(path: str):
    started = time.perf_counter()
    with urllib.request.urlopen(BASE + path, timeout=5.0) as response:
        body = response.read()
    return (time.perf_counter() - started) * 1000.0, body


def percentiles(values):
    ordered = sorted(values)
    point = lambda p: ordered[min(len(ordered) - 1, int((len(ordered) - 1) * p))]
    return {
        "p50": round(point(0.50), 3),
        "p95": round(point(0.95), 3),
        "p99": round(point(0.99), 3),
        "max": round(ordered[-1], 3),
    }


def main() -> None:
    _, before_raw = get("/v1/oracle/fast-lane/health")
    before = json.loads(before_raw)
    _, ready_before_raw = get("/health/ready")
    ready_before = json.loads(ready_before_raw)
    latency = []
    body = b""
    for _ in range(100):
        elapsed, body = get("/v1/oracle/fast-lane")
        latency.append(elapsed)
    _, after_raw = get("/v1/oracle/fast-lane/health")
    after = json.loads(after_raw)
    chart_latency = []
    chart_body = b""
    for _ in range(100):
        elapsed, chart_body = get(
            "/v1/oracle-development/chart-data?timeframe=5m"
        )
        chart_latency.append(elapsed)
    _, ready_after_raw = get("/health/ready")
    ready_after = json.loads(ready_after_raw)
    price_before = ready_before.get("price_action") or {}
    price_after = ready_after.get("price_action") or {}
    print(json.dumps({
        "context": "POST_MARKET_RUNTIME_CACHE_REUSE",
        "requests": 100,
        "latency_ms": percentiles(latency),
        "payload_bytes": len(body),
        "revision_before": before.get("revision"),
        "revision_after": after.get("revision"),
        "full_builds_delta": int(after.get("full_builds") or 0) - int(before.get("full_builds") or 0),
        "full_serializations_delta": (
            int(after.get("full_serializations") or 0)
            - int(before.get("full_serializations") or 0)
        ),
        "http_serves_delta": int(after.get("http_serves") or 0) - int(before.get("http_serves") or 0),
        "chart": {
            "requests": 100,
            "latency_ms": percentiles(chart_latency),
            "payload_bytes": len(chart_body),
            "price_action_analyses_delta": (
                int(price_after.get("analysis_count") or 0)
                - int(price_before.get("analysis_count") or 0)
            ),
            "structure_scans_delta": (
                int(price_after.get("structure_scan_count") or 0)
                - int(price_before.get("structure_scan_count") or 0)
            ),
        },
    }, sort_keys=True))


if __name__ == "__main__":
    main()
