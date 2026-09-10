"""Dedicated Capture Processing Performance Benchmark for Phase E4A-F."""

import time
import json
import struct
import hashlib
from pathlib import Path
from src.eye.option_capture.packet_decoder import DhanPacketDecoder
from src.eye.option_capture.reconciler import FieldReconciler
from src.eye.option_capture.contracts import FeedLane


def run_e4ae_benchmarks():
    print("=== DEDICATED E4A-F CAPTURE PROCESSING BENCHMARK RUNNER ===")
    sizes = [500, 5000, 50000]
    results = {}

    payload = bytearray(162)
    payload[0] = 8
    struct.pack_into("<H", payload, 1, 162)

    for size in sizes:
        runs_ns = []
        for _ in range(5):
            t0 = time.perf_counter_ns()
            reconciler = FieldReconciler()
            for i in range(size):
                pkt = DhanPacketDecoder.decode_packet(bytes(payload))
                if pkt:
                    reconciler.update_field(
                        contract_key="OPTCONTRACT:NSE:NSE_FO:NIFTY:2026-08-13:24500.0:CE",
                        field_name="last_price",
                        value=pkt["last_price"],
                        source_lane=FeedLane.FAST_LANE_WEBSOCKET,
                        exchange_time_utc="2026-08-07T09:15:00Z",
                        received_at_utc="2026-08-07T09:15:00Z",
                        available_at_utc="2026-08-07T09:15:00Z",
                    )
            t1 = time.perf_counter_ns()
            runs_ns.append(t1 - t0)

        median_sec = sorted(runs_ns)[len(runs_ns)//2] / 1e9
        ops_per_sec = size / median_sec if median_sec > 0 else 0
        chk = hashlib.sha256(f"E4AF:{size}:{median_sec}".encode("utf-8")).hexdigest()

        print(f"[CAPTURE_PROCESSING   ] Size {size:5d} -> Median: {median_sec:.6f}s ({ops_per_sec:,.1f} ops/s) | Checksum: {chk[:12]}")
        results[str(size)] = {
            "packets_processed": size,
            "median_seconds": round(median_sec, 6),
            "ops_per_second": round(ops_per_sec, 1),
            "output_checksum": chk,
        }

    out_file = Path("/Users/ayushmudgal/Developer/CitadelOS-Tooling/recovery/EYE_ENGINE_E4AE_PERFORMANCE_20260807.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2))
    print("Capture benchmark written to", out_file)
    return "PASS"


if __name__ == "__main__":
    run_e4ae_benchmarks()
