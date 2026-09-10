"""R2.1L genuine-journal mature telemetry capacity benchmark."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from scripts.benchmark_flow_worker_r21 import _identity, _rows, _semantic, _tick
from src.order_flow.service import OrderFlowService


def _mature(service: OrderFlowService) -> None:
    with service._telemetry_lock:
        for values in service._latency.values():
            values.extend(float(index % 1000) for index in range(20_000))
        for name in ("packet_to_raw", "raw_to_event", "event_to_payload", "packet_to_payload"):
            service._latency[name].extend(float(index % 1000) for index in range(20_000))
    pulse = service.flow_pulse
    with pulse._telemetry_lock:
        pulse._latency_ns.extend(index % 1_000_000 for index in range(50_000))
        for name in (
            "profile_update", "microstructure_update", "semantic_commit",
            "episode_evaluation", "projection", "option_mapping",
            "payload_build", "candidate_validation",
        ):
            pulse._stage_latency_ns[name].extend(
                index % 1_000_000 for index in range(50_000)
            )


def _run(ticks: list[dict[str, Any]], identities, *, telemetry: bool) -> dict[str, Any]:
    service = OrderFlowService()
    service.register_instruments(identities)
    service.ingest_tick(ticks[0])
    _mature(service)
    if telemetry:
        service.start()
    rates: list[float] = []
    started = time.perf_counter()
    try:
        chunk_size = 100
        for offset in range(1, len(ticks), chunk_size):
            chunk = ticks[offset : offset + chunk_size]
            chunk_started = time.perf_counter()
            for tick in chunk:
                service.ingest_tick(tick)
            elapsed = time.perf_counter() - chunk_started
            rates.append(len(chunk) / elapsed)
        total = time.perf_counter() - started
        if telemetry:
            deadline = time.monotonic() + 2.0
            while (
                service.telemetry()["telemetry_refresh_count"] < 2
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
        telemetry_value = service.telemetry()
        projection = service.latest_projection()
    finally:
        service.stop()
    return {
        "packets": len(ticks) - 1,
        "elapsed_seconds": total,
        "capacity_pkt_s": (len(ticks) - 1) / total,
        "chunk_rates": rates,
        "early_pkt_s": rates[0],
        "late_pkt_s": rates[-1],
        "late_to_early_ratio": rates[-1] / rates[0],
        "telemetry": telemetry_value,
        "semantic": _semantic(projection),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("journal", type=Path)
    parser.add_argument("--packets", type=int, default=1_200)
    args = parser.parse_args()
    rows = _rows(args.journal, args.packets)
    if len(rows) < args.packets:
        raise SystemExit("insufficient genuine in-session rows")
    identities_by_role = {
        str(row["instrument_role"]): _identity(row)
        for row in rows
    }
    identities = tuple(
        sorted(identities_by_role.values(), key=lambda item: item.role)
    )
    ticks = [_tick(row) for row in rows]
    disabled = _run(ticks, identities, telemetry=False)
    enabled = _run(ticks, identities, telemetry=True)
    parity = disabled["semantic"] == enabled["semantic"]
    output = {
        "schema": "ORACLE_R2_1L_TELEMETRY_CAPACITY_V1",
        "genuine_packets": len(ticks),
        "telemetry_disabled_capacity_pkt_s": round(disabled["capacity_pkt_s"], 3),
        "telemetry_enabled_capacity_pkt_s": round(enabled["capacity_pkt_s"], 3),
        "telemetry_overhead_percent": round(
            max(
                0.0,
                100.0 * (
                    disabled["capacity_pkt_s"] - enabled["capacity_pkt_s"]
                ) / disabled["capacity_pkt_s"],
            ),
            3,
        ),
        "enabled_early_pkt_s": round(enabled["early_pkt_s"], 3),
        "enabled_late_pkt_s": round(enabled["late_pkt_s"], 3),
        "enabled_late_to_early_ratio": round(enabled["late_to_early_ratio"], 3),
        "enabled_min_chunk_pkt_s": round(min(enabled["chunk_rates"]), 3),
        "telemetry_refresh_count": enabled["telemetry"]["telemetry_refresh_count"],
        "telemetry_refresh_ms": enabled["telemetry"]["telemetry_refresh_ms"],
        "mature_service_window": 20_000,
        "mature_flow_pulse_window": 50_000,
        "semantic_parity": parity,
    }
    print(json.dumps(output, sort_keys=True))
    if (
        not parity
        or output["telemetry_enabled_capacity_pkt_s"] < 27.2
        or output["enabled_late_to_early_ratio"] < 0.5
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
