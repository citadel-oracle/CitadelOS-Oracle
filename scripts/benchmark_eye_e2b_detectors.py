"""Phase N — Performance and Benchmark Profiling Script for Eye Engine E2B-C."""

import json
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

from src.eye.contracts import PriceAtom, InstrumentIdentity
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.swing_state import SwingStateDetector
from src.eye.detectors.displacement import DisplacementDetector


def benchmark_detectors():
    print("=== PHASE N: PERFORMANCE AND BENCHMARK PROFILING ===")
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")

    benchmarks = {}
    for size in (500, 5000, 50000):
        bars = [
            DetectorBar(
                instrument_key="UNDERLYING_INDEX:NIFTY", timeframe="5m",
                open_time=now + timedelta(minutes=5*i), expected_close_time=now + timedelta(minutes=5*(i+1)), available_at=now + timedelta(minutes=5*(i+1)),
                bar_key=f"NIFTY:5m:{i}", open=PriceAtom(ticks=2440000), high=PriceAtom(ticks=2445000),
                low=PriceAtom(ticks=2438000), close=PriceAtom(ticks=2444000), is_closed=True, volume=1000,
            )
            for i in range(size)
        ]
        ctx = DetectorContext(instrument=inst, timeframe="5m", as_of=bars[-1].expected_close_time)

        t0 = time.time()
        res = DisplacementDetector().detect(bars, ctx)
        t1 = time.time()
        elapsed = t1 - t0
        bars_per_sec = size / float(elapsed) if elapsed > 0 else 0
        print(f"Size {size:5d} bars -> Elapsed: {elapsed:.4f}s | Speed: {bars_per_sec:.1f} bars/sec")
        benchmarks[str(size)] = {
            "elapsed_seconds": round(elapsed, 4),
            "bars_per_second": round(bars_per_sec, 1),
            "records_count": len(res.records),
        }

    out_path = Path("/Users/ayushmudgal/Developer/CitadelOS-Tooling/recovery/EYE_ENGINE_E2BC_PERFORMANCE_20260806.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(benchmarks, indent=2))
    print("Performance benchmark saved to", out_path)


if __name__ == "__main__":
    benchmark_detectors()
