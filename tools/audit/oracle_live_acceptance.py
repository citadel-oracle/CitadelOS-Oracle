#!/usr/bin/env python3
"""Read-only, duration-bound acceptance sampler for the next open market session."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


def path(payload: Any, dotted: str) -> Any:
    value = payload
    for part in dotted.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


FIELDS = {
    "nifty_spot": "snapshot.spot_ltp",
    "nifty_future": "snapshot.futures_ltp",
    "future_basis": "snapshot.futures_basis",
    "atm_strike": "snapshot.atm_strike",
    "active_ce_ltp": "snapshot.ce_pricing.ltp",
    "active_pe_ltp": "snapshot.pe_pricing.ltp",
    "active_ce_bid": "snapshot.ce_pricing.best_bid_price",
    "active_ce_ask": "snapshot.ce_pricing.best_ask_price",
    "active_pe_bid": "snapshot.pe_pricing.best_bid_price",
    "active_pe_ask": "snapshot.pe_pricing.best_ask_price",
    "mlofi": "snapshot.mlofi_5l",
    "atm_iv": "snapshot.atm_iv",
    "skew_25d": "snapshot.skew_25d",
    "net_gex_inr": "snapshot.net_gex_inr",
    "zero_gamma": "snapshot.zero_gamma_level",
    "banknifty_context": "snapshot.domestic_indices.BANKNIFTY",
    "midcpnifty_context": "snapshot.domestic_indices.MIDCPNIFTY",
    "sol_revision": "state_revision",
}


def collect_sse(base: str, stop: threading.Event, revisions: list[float], delivery_ms: list[float]) -> None:
    """Collect the canonical Fast Lane SSE only; never mutates runtime state."""
    try:
        with requests.get(
            base + "/v1/oracle/fast-lane/stream",
            stream=True,
            timeout=(5, 900),
            headers={"Accept": "text/event-stream"},
        ) as response:
            response.raise_for_status()
            event_name = ""
            for raw in response.iter_lines(decode_unicode=True):
                if stop.is_set():
                    return
                line = raw or ""
                if line.startswith("event:"):
                    event_name = line.partition(":")[2].strip()
                elif line.startswith("data:") and event_name == "oracle_fast_lane":
                    payload = json.loads(line.partition(":")[2].strip())
                    revision = payload.get("global_revision")
                    if isinstance(revision, (int, float)):
                        revisions.append(float(revision))
                    published_at = payload.get("published_at")
                    if isinstance(published_at, str):
                        stamp = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                        if stamp.tzinfo is not None:
                            delivery_ms.append(max(0.0, (datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds() * 1000.0))
    except (requests.RequestException, ValueError, json.JSONDecodeError):
        return


def stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"sample_count": 0, "min": None, "p50": None, "p95": None, "p99": None, "max": None, "first": None, "last": None, "distinct": 0}
    ordered = sorted(values)
    pick = lambda q: ordered[min(len(ordered) - 1, int((len(ordered) - 1) * q))]
    return {
        "sample_count": len(values), "min": min(values), "p50": pick(.5), "p95": pick(.95),
        "p99": pick(.99), "max": max(values), "first": values[0], "last": values[-1],
        "distinct": len(set(values)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-seconds", type=float, required=True)
    parser.add_argument("--sample-interval-seconds", type=float, default=1.0)
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000")
    parser.add_argument("--ui-url", default="http://127.0.0.1:3000/oracle")
    parser.add_argument("--output-dir", type=Path, default=Path.cwd())
    args = parser.parse_args()
    if args.duration_seconds <= 0 or args.sample_interval_seconds <= 0:
        parser.error("durations must be positive")

    base = args.backend_url.rstrip("/")
    first = requests.get(base + "/v1/oracle/sol/state", timeout=10).json()
    if path(first, "snapshot.system_status") == "OFF_MARKET":
        print("MARKET_CLOSED")
        return 0

    samples: dict[str, list[float]] = {name: [] for name in FIELDS}
    rest_ms: list[float] = []
    sse_revisions: list[float] = []
    sse_delivery_ms: list[float] = []
    stop_sse = threading.Event()
    sse_thread = threading.Thread(
        target=collect_sse,
        args=(base, stop_sse, sse_revisions, sse_delivery_ms),
        name="oracle-live-acceptance-sse",
        daemon=True,
    )
    sse_thread.start()
    end = time.monotonic() + args.duration_seconds
    while time.monotonic() < end:
        started = time.perf_counter_ns()
        state = requests.get(base + "/v1/oracle/sol/state", timeout=10).json()
        rest_ms.append((time.perf_counter_ns() - started) / 1_000_000.0)
        for name, dotted in FIELDS.items():
            value = path(state, dotted)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                samples[name].append(float(value))
        time.sleep(min(args.sample_interval_seconds, max(0.0, end - time.monotonic())))

    stop_sse.set()
    report = {
        "duration_seconds": args.duration_seconds,
        "fields": {name: stats(values) for name, values in samples.items()},
        "localhost_sol_rest_ms": stats(rest_ms),
        "fast_lane_sse_revision": stats(sse_revisions),
        "fast_lane_sse_publish_to_receive_ms": stats(sse_delivery_ms),
        "runtime_diagnostic": requests.get(base + "/v1/oracle/runtime-diagnostic", timeout=10).json(),
        "fast_lane_health": requests.get(base + "/v1/oracle/fast-lane/health", timeout=10).json(),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "LIVE_ORACLE_ACCEPTANCE.json").write_text(json.dumps(report, indent=2) + "\n")
    with (args.output_dir / "LIVE_ORACLE_LATENCY.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "sample_count", "min", "p50", "p95", "p99", "max", "first", "last", "distinct"])
        writer.writeheader()
        for name, summary in {
            **report["fields"],
            "localhost_sol_rest_ms": report["localhost_sol_rest_ms"],
            "fast_lane_sse_revision": report["fast_lane_sse_revision"],
            "fast_lane_sse_publish_to_receive_ms": report["fast_lane_sse_publish_to_receive_ms"],
        }.items():
            writer.writerow({"metric": name, **summary})

    from oracle_truth_audit import audit
    parity = audit(ui_url=args.ui_url, backend_url=base, output_dir=args.output_dir, timeout_seconds=30)
    source = args.output_dir / "ORACLE_TRUTH_AUDIT.csv"
    source.replace(args.output_dir / "LIVE_ORACLE_FIELD_PARITY.csv")
    print(json.dumps({"acceptance": report, "field_parity": {key: value for key, value in parity.items() if key != "rows"}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
