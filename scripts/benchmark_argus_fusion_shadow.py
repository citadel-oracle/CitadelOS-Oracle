#!/usr/bin/env python3
"""Small deterministic hot-path benchmark for ARGUS_FUSION_SHADOW_V0."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.argus.fusion_shadow import FusionShadowEngine


class _LedgerSink:
    """In-memory sink that measures the existing recorder submission boundary only."""

    def submit(self, _event_type: str, _payload: dict, _key: str) -> bool:
        return True


def _flow(ltp: float) -> dict:
    return {
        "data_quality": "GOOD",
        "directional_state": "NEUTRAL",
        "flow_pulse": {
            "source_timestamp": "2026-08-12T09:15:00+05:30",
            "futures": {"ltp": ltp, "invalidation": None, "target_1": None, "target_2": None},
            "semantic": {"pressure": "BUYING STRONG", "result": "PRICE RISING WITH BUYERS"},
            "reaction": {"state": "BUYERS WORKING"},
            "what_happened": "TREND CONTINUES",
            "live_health": {"status": "LIVE"},
        },
    }


def _argus(ce: float, pe: float) -> dict:
    return {
        "data": {
            "underlying": {"atm_strike": 24400.0, "ltp": 24400.0, "expiry": "2026-08-18", "source_event_time": "2026-08-12T09:15:00+05:30"},
            "atm_window": [{
                "strike": 24400.0,
                "ce": {"security_id": "ce", "top_bid_price": ce - 0.2, "top_ask_price": ce + 0.2, "ltp": ce, "oi": 1000, "volume": 1000},
                "pe": {"security_id": "pe", "top_bid_price": pe - 0.2, "top_ask_price": pe + 0.2, "ltp": pe, "oi": 1000, "volume": 1000},
            }],
        }
    }


def _distribution(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    def at(fraction: float) -> float:
        return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))], 4)
    return {"p50": at(0.50), "p95": at(0.95), "p99": at(0.99), "max": round(ordered[-1], 4)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    subject = FusionShadowEngine(
        recorder=_LedgerSink(),
        now=lambda: "2026-08-12T09:15:00+05:30",
    )
    subject.ingest_argus(_argus(100.0, 100.0))
    subject.ingest_flow(_flow(24400.0))
    samples: list[float] = []
    for index in range(max(1, args.iterations)):
        started = perf_counter()
        subject.ingest_flow(_flow(24400.0 + index * 0.01))
        if index % 4 == 0:
            subject.ingest_argus(_argus(100.0 + index * 0.001, 100.0 - index * 0.001))
        samples.append((perf_counter() - started) * 1_000.0)
    projection = subject.projection()
    # State-event persistence is intentionally sparse.  Measure that distinct
    # append-only enqueue path independently rather than pretending every tick
    # is a ledger event.
    ledger_samples: list[float] = []
    for _ in range(min(max(64, args.iterations // 10), 1_000)):
        probe = FusionShadowEngine(
            recorder=_LedgerSink(),
            now=lambda: "2026-08-12T09:15:00+05:30",
        )
        started = perf_counter()
        probe.ingest_flow(_flow(24400.0))
        ledger_samples.append((perf_counter() - started) * 1_000.0)
    result = {
        "benchmark": "ARGUS_FUSION_SHADOW_V0_HOT_PATH",
        "iterations": len(samples),
        "end_to_end_loop_ms": _distribution(samples),
        "ledger_state_event_enqueue_path_ms": _distribution(ledger_samples),
        "engine_telemetry_ms": projection["telemetry"],
        "execution_influence": projection["execution_influence"],
        "network_calls": 0,
        "second_dhan_owner": False,
    }
    encoded = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
