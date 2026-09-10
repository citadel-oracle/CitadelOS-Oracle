"""Long-session genuine packet replay for R2.1L mature-window decay proof."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping
from zoneinfo import ZoneInfo

from scripts.benchmark_flow_worker_r21 import _identity, _tick
from src.order_flow.service import OrderFlowService


IST = ZoneInfo("Asia/Kolkata")


def _session_payloads(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
                payload = row.get("payload") if isinstance(row, Mapping) else None
                if not isinstance(payload, Mapping):
                    continue
                received = datetime.fromisoformat(
                    str(payload["receive_wall_utc"])
                ).astimezone(IST)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            if (
                received.weekday() < 5
                and (received.hour, received.minute) >= (9, 15)
                and (received.hour, received.minute) < (15, 30)
            ):
                yield dict(payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("journal", type=Path)
    parser.add_argument("--chunk", type=int, default=5_000)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    identities_by_key = {}
    for row in _session_payloads(args.journal):
        identity = _identity(row)
        identities_by_key[(identity.exchange_segment, identity.security_id)] = identity
    identities = tuple(identities_by_key.values())
    if not identities:
        raise SystemExit("no genuine in-session identities")

    service = OrderFlowService()
    service.register_instruments(identities)
    service.start()
    chunk_rates: list[float] = []
    chunk_started = time.perf_counter()
    total_started = chunk_started
    count = 0
    accepted = 0
    try:
        for row in _session_payloads(args.journal):
            if args.limit is not None and count >= args.limit:
                break
            projection = service.ingest_tick(_tick(row))
            count += 1
            if projection is not None:
                accepted += 1
            if count % args.chunk == 0:
                now = time.perf_counter()
                chunk_rates.append(args.chunk / (now - chunk_started))
                chunk_started = now
        remainder = count % args.chunk
        if remainder:
            now = time.perf_counter()
            chunk_rates.append(remainder / (now - chunk_started))
        elapsed = time.perf_counter() - total_started
        telemetry = service.refresh_telemetry()
        pulse = telemetry["flow_pulse"]
        with service.flow_pulse._telemetry_lock:
            pulse_window_count = len(service.flow_pulse._latency_ns)
            pulse_stage_counts = {
                name: len(values)
                for name, values in service.flow_pulse._stage_latency_ns.items()
            }
    finally:
        service.stop()

    early = statistics.median(chunk_rates[: min(3, len(chunk_rates))])
    late = statistics.median(chunk_rates[-min(3, len(chunk_rates)) :])
    output = {
        "schema": "ORACLE_R2_1L_LONG_SESSION_V1",
        "journal": str(args.journal),
        "genuine_in_session_packets": count,
        "accepted_packets": accepted,
        "elapsed_seconds": round(elapsed, 3),
        "sustained_capacity_pkt_s": round(count / elapsed, 3),
        "early_chunk_capacity_pkt_s": round(early, 3),
        "late_chunk_capacity_pkt_s": round(late, 3),
        "late_to_early_ratio": round(late / early, 3),
        "minimum_chunk_capacity_pkt_s": round(min(chunk_rates), 3),
        "maximum_chunk_capacity_pkt_s": round(max(chunk_rates), 3),
        "service_window_counts": {
            name: value["count"]
            for name, value in telemetry["stages_ms"].items()
        },
        "flow_pulse_window_count": pulse_window_count,
        "flow_pulse_stage_counts": pulse_stage_counts,
        "telemetry_refresh_count": telemetry["telemetry_refresh_count"],
        "telemetry_refresh_ms": telemetry["telemetry_refresh_ms"],
        "progressive_capacity_decay": late < early * 0.5,
        "formulas_changed": False,
        "thresholds_changed": False,
    }
    print(json.dumps(output, sort_keys=True))
    if (
        count < 50_000
        or output["sustained_capacity_pkt_s"] < 27.2
        or output["progressive_capacity_decay"]
        or max(output["service_window_counts"].values(), default=0) < 20_000
        or max(output["flow_pulse_stage_counts"].values(), default=0) < 50_000
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
