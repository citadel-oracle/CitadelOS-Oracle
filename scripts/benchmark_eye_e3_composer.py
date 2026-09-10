"""Phase 36 — Composer Performance Benchmark & Complexity Profiler for Eye Engine E3."""

import json
import time
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List

from src.eye.contracts import EyeEventRecord, InstrumentIdentity, EvaluationContext, PointEventPayload, EventFamily, EventType, EventDirection, DetectionState, LifecycleState, ProducerProvenance, PriceAtom
from src.eye.composer.setup_registry import get_e3_setup_definitions
from src.eye.composer.matcher import SetupComposer


def generate_benchmark_events(count: int) -> List[EyeEventRecord]:
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")
    prov = ProducerProvenance(engine_name="TestEngine", source_file="test.py", source_symbol="test", source_commit="8632791", producer_version="1.0.0", rule_id="R1", rule_version="1.0.0")

    events = []
    for i in range(count):
        t = now + timedelta(seconds=i)
        ctx = EvaluationContext(market_time=t, available_at=t, detected_at=t, as_of=t)
        payload = PointEventPayload(primary_level=PriceAtom(ticks=2450000), direction=EventDirection.BEARISH)
        # Alternate pool and sweep on the same level to trigger LIQUIDITY_SWEEP_RECLAIM
        ev_type = EventType.LIQUIDITY_POOL_HIGH if (i % 2 == 0) else EventType.LIQUIDITY_SWEEP_HIGH
        ev = EyeEventRecord.create(
            family=EventFamily.LIQUIDITY, event_type=ev_type,
            direction=EventDirection.BEARISH, instrument=inst, timeframe="5m",
            payload=payload, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
            lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx,
            observed_at=t, detected_at=t, source_bars=(), producer=prov,
        )
        events.append(ev)
    return events


def run_composer_benchmarks():
    print("=== PHASE 36: COMPOSER PERFORMANCE BENCHMARK & COMPLEXITY PROFILER ===")

    results = {}
    sizes = [500, 5000, 50000]

    for size in sizes:
        events = generate_benchmark_events(size)
        defs = get_e3_setup_definitions()

        # Warmup pass
        composer_warm = SetupComposer(defs)
        for e in events[:50]:
            composer_warm.process_event(e)

        # Minimum 5 repetitions
        runs_ns = []
        cands_counts = []
        checksums = []

        for _ in range(5):
            composer = SetupComposer(defs)
            t0 = time.perf_counter_ns()
            cands = []
            for e in events:
                c = composer.process_event(e)
                cands.extend(c)
            t1 = time.perf_counter_ns()

            elapsed_ns = t1 - t0
            runs_ns.append(elapsed_ns)
            cands_counts.append(len(composer.candidates))
            keys_str = "".join(c.setup_key for c in composer.candidates)
            checksum = hashlib.sha256(keys_str.encode("utf-8")).hexdigest()
            checksums.append(checksum)

        median_ns = sorted(runs_ns)[len(runs_ns)//2]
        elapsed_sec = median_ns / 1e9
        events_per_sec = size / elapsed_sec if elapsed_sec > 0 else 0

        print(f"Size {size:5d} events -> Median: {elapsed_sec:.6f}s ({events_per_sec:,.1f} events/sec) | Candidates: {cands_counts[0]} | Checksum: {checksums[0][:12]}")

        results[str(size)] = {
            "size": size,
            "median_seconds": round(elapsed_sec, 6),
            "min_seconds": round(min(runs_ns) / 1e9, 6),
            "max_seconds": round(max(runs_ns) / 1e9, 6),
            "events_per_second": round(events_per_sec, 1),
            "candidates_count": cands_counts[0],
            "output_checksum": checksums[0],
        }

    ratio_5k_500 = results["5000"]["median_seconds"] / max(results["500"]["median_seconds"], 1e-6)
    ratio_50k_5k = results["50000"]["median_seconds"] / max(results["5000"]["median_seconds"], 1e-6)

    print("\nEmpirical Complexity Ratios:")
    print(f"  T(5,000) / T(500)   [10x input]: {ratio_5k_500:.2f}x")
    print(f"  T(50,000) / T(5,000) [10x input]: {ratio_50k_5k:.2f}x")

    complexity_class = "APPROXIMATELY_LINEAR" if ratio_50k_5k < 25.0 else "MODERATELY_SUPERLINEAR"
    print(f"  Empirical Complexity Classification: {complexity_class}")

    out_perf = Path("/Users/ayushmudgal/Developer/CitadelOS-Tooling/recovery/EYE_ENGINE_E3_PERFORMANCE_20260806.json")
    out_perf.parent.mkdir(parents=True, exist_ok=True)
    out_perf.write_text(json.dumps(results, indent=2))

    print("Composer benchmark report written to", out_perf)


if __name__ == "__main__":
    run_composer_benchmarks()
