"""Phase 6 & 7 — Real Performance Benchmark & Complexity Profiler for Eye Engine E2B-D."""

import json
import time
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any

from src.eye.contracts import PriceAtom, InstrumentIdentity
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.displacement import DisplacementDetector
from src.eye.detectors.swing_state import SwingStateDetector
from src.eye.detector_replay import OfflineDetectorReplayHarness


def generate_benchmark_bars(count: int) -> List[DetectorBar]:
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    bars = []
    for i in range(count):
        t = now - timedelta(minutes=5 * (count - i))
        px = 24500.0 + (i % 7 - 3) * 15.0
        bar = DetectorBar(
            instrument_key="UNDERLYING_INDEX:NIFTY", timeframe="5m",
            open_time=t, expected_close_time=t + timedelta(minutes=5), available_at=t + timedelta(minutes=5),
            bar_key=f"NIFTY:5m:{i}", open=PriceAtom(ticks=int(px * 100)), high=PriceAtom(ticks=int((px + 38) * 100)),
            low=PriceAtom(ticks=int((px - 2) * 100)), close=PriceAtom(ticks=int((px + 35) * 100)), is_closed=True, volume=1500,
        )
        bars.append(bar)
    return bars


def run_real_benchmarks():
    print("=== PHASE 6 & 7: REAL PERFORMANCE BENCHMARK & COMPLEXITY PROFILER ===")
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")

    results = {}
    sizes = [500, 5000, 50000]

    for size in sizes:
        bars = generate_benchmark_bars(size)
        ctx = DetectorContext(instrument=inst, timeframe="5m", as_of=bars[-1].expected_close_time)

        # 1. Warmup pass
        _ = SwingStateDetector().detect(bars[:50], ctx)

        # 2. Minimum 5 repetitions using time.perf_counter_ns()
        runs_ns = []
        rec_counts = []
        checksums = []

        for _ in range(5):
            t0 = time.perf_counter_ns()
            res = SwingStateDetector().detect(bars, ctx)
            t1 = time.perf_counter_ns()
            elapsed_ns = t1 - t0
            runs_ns.append(elapsed_ns)

            rec_counts.append(len(res.records))
            # Verify work done by consuming output fingerprint
            keys_str = "".join(r.event_key for r in res.records)
            checksum = hashlib.sha256(keys_str.encode("utf-8")).hexdigest()
            checksums.append(checksum)

        median_ns = sorted(runs_ns)[len(runs_ns)//2]
        elapsed_sec = median_ns / 1e9
        bars_per_sec = size / elapsed_sec if elapsed_sec > 0 else 0

        print(f"Size {size:5d} bars -> Median: {elapsed_sec:.6f}s ({bars_per_sec:,.1f} bars/sec) | Records: {rec_counts[0]} | Checksum: {checksums[0][:12]}")

        results[str(size)] = {
            "size": size,
            "median_seconds": round(elapsed_sec, 6),
            "min_seconds": round(min(runs_ns) / 1e9, 6),
            "max_seconds": round(max(runs_ns) / 1e9, 6),
            "bars_per_second": round(bars_per_sec, 1),
            "records_count": rec_counts[0],
            "output_checksum": checksums[0],
        }

    # Complexity ratios
    ratio_5k_500 = results["5000"]["median_seconds"] / max(results["500"]["median_seconds"], 1e-6)
    ratio_50k_5k = results["50000"]["median_seconds"] / max(results["5000"]["median_seconds"], 1e-6)

    print("\nEmpirical Complexity Ratios:")
    print(f"  T(5,000) / T(500)   [10x input]: {ratio_5k_500:.2f}x")
    print(f"  T(50,000) / T(5,000) [10x input]: {ratio_50k_5k:.2f}x")

    complexity_class = "APPROXIMATELY_LINEAR" if ratio_50k_5k < 25.0 else "MODERATELY_SUPERLINEAR"
    print(f"  Empirical Complexity Classification: {complexity_class}")

    out_perf = Path("/Users/ayushmudgal/Developer/CitadelOS-Tooling/recovery/EYE_ENGINE_E2BD_PERFORMANCE_20260806.json")
    out_perf.parent.mkdir(parents=True, exist_ok=True)
    out_perf.write_text(json.dumps(results, indent=2))

    out_comp = Path("/Users/ayushmudgal/Developer/CitadelOS-Tooling/recovery/EYE_ENGINE_E2BD_COMPLEXITY_20260806.json")
    out_comp.write_text(json.dumps({
        "ratio_5k_500": round(ratio_5k_500, 2),
        "ratio_50k_5k": round(ratio_50k_5k, 2),
        "classification": complexity_class,
    }, indent=2))

    print("Benchmark artifacts written successfully!")


if __name__ == "__main__":
    run_real_benchmarks()
