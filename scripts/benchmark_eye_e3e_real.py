"""Phase E3-E Real Distinct Benchmark Runner for Citadel Eye Engine Phase E4A-C."""

import json
import time
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Tuple

from src.eye.contracts import (
    EyeEventRecord, InstrumentIdentity, EvaluationContext, PointEventPayload,
    EventFamily, EventType, EventDirection, DetectionState, LifecycleState,
    ProducerProvenance, PriceAtom
)
from src.eye.composer.setup_registry import get_e3_setup_definitions
from src.eye.composer.matcher import SetupComposer


def generate_benchmark_scenario_events(count: int, scenario: str) -> List[EyeEventRecord]:
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")
    prov = ProducerProvenance(engine_name="BenchmarkEngine", source_file="benchmark.py", source_symbol="NIFTY", source_commit="059bd91", producer_version="1.0.0", rule_id="R1", rule_version="1.0.0")

    events = []

    if scenario == "NO_MATCH_CONTROL":
        # Structure breaks only (never completes 2-step setup definitions)
        for i in range(count):
            t = now + timedelta(seconds=i)
            ctx = EvaluationContext(market_time=t, available_at=t, detected_at=t, as_of=t)
            p = PointEventPayload(primary_level=PriceAtom(ticks=int((24500.0 + (i % 5)) * 100)), direction=EventDirection.BEARISH)
            ev = EyeEventRecord.create(
                family=EventFamily.STRUCTURE, event_type=EventType.SWING_HIGH,
                direction=EventDirection.BEARISH, instrument=inst, timeframe="5m",
                payload=p, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx,
                observed_at=t, detected_at=t, source_bars=(), producer=prov, event_revision=1,
            )
            events.append(ev)

    elif scenario == "MULTI_STEP_MODERATE":
        # Alternating Pool High & Sweep High to trigger s1 (LIQUIDITY_SWEEP_RECLAIM)
        for i in range(count):
            t = now + timedelta(seconds=i)
            ctx = EvaluationContext(market_time=t, available_at=t, detected_at=t, as_of=t)
            p = PointEventPayload(primary_level=PriceAtom(ticks=2450000), direction=EventDirection.BEARISH)
            ev_type = EventType.LIQUIDITY_POOL_HIGH if (i % 2 == 0) else EventType.LIQUIDITY_SWEEP_HIGH
            ev = EyeEventRecord.create(
                family=EventFamily.LIQUIDITY, event_type=ev_type,
                direction=EventDirection.BEARISH, instrument=inst, timeframe="5m",
                payload=p, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx,
                observed_at=t, detected_at=t, source_bars=(), producer=prov, event_revision=1,
            )
            events.append(ev)

    elif scenario == "OVERLAP_STRESS":
        # Dense sweeps creating multiple overlapping candidate branches
        for i in range(count):
            t = now + timedelta(seconds=i)
            ctx = EvaluationContext(market_time=t, available_at=t, detected_at=t, as_of=t)
            level = 2450000 + (i % 3) * 100
            p = PointEventPayload(primary_level=PriceAtom(ticks=level), direction=EventDirection.BEARISH)
            ev_type = EventType.LIQUIDITY_POOL_HIGH if (i % 3 != 2) else EventType.LIQUIDITY_SWEEP_HIGH
            ev = EyeEventRecord.create(
                family=EventFamily.LIQUIDITY, event_type=ev_type,
                direction=EventDirection.BEARISH, instrument=inst, timeframe="5m",
                payload=p, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx,
                observed_at=t, detected_at=t, source_bars=(), producer=prov, event_revision=1,
            )
            events.append(ev)

    elif scenario == "REVISION_INVALIDATION":
        # Event revisions & parent invalidations
        for i in range(count):
            t = now + timedelta(seconds=i)
            ctx = EvaluationContext(market_time=t, available_at=t, detected_at=t, as_of=t)
            p = PointEventPayload(primary_level=PriceAtom(ticks=2450000), direction=EventDirection.BEARISH)
            rev = (i % 3) + 1
            l_state = LifecycleState.INVALIDATED if (rev == 3) else LifecycleState.CREATED
            ev = EyeEventRecord.create(
                family=EventFamily.LIQUIDITY, event_type=EventType.LIQUIDITY_SWEEP_HIGH,
                direction=EventDirection.BEARISH, instrument=inst, timeframe="5m",
                payload=p, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                lifecycle_state=l_state, evaluation_context=ctx,
                observed_at=t, detected_at=t, source_bars=(), producer=prov, event_revision=rev,
            )
            events.append(ev)

    elif scenario == "HISTORICAL_STREAM":
        # Simulated multi-event flow matching real detector distribution
        for i in range(count):
            t = now + timedelta(seconds=i)
            ctx = EvaluationContext(market_time=t, available_at=t, detected_at=t, as_of=t)
            p = PointEventPayload(primary_level=PriceAtom(ticks=int((24500.0 + (i % 10)) * 100)), direction=EventDirection.BEARISH)
            mod = i % 4
            if mod == 0:
                ev_t = EventType.BOS_BEARISH
                fam = EventFamily.STRUCTURE
            elif mod == 1:
                ev_t = EventType.FVG_BEARISH
                fam = EventFamily.IMBALANCE
            elif mod == 2:
                ev_t = EventType.LIQUIDITY_POOL_HIGH
                fam = EventFamily.LIQUIDITY
            else:
                ev_t = EventType.LIQUIDITY_SWEEP_HIGH
                fam = EventFamily.LIQUIDITY

            ev = EyeEventRecord.create(
                family=fam, event_type=ev_t,
                direction=EventDirection.BEARISH, instrument=inst, timeframe="5m",
                payload=p, detection_state=DetectionState.CONFIRMED_CLOSED_BAR,
                lifecycle_state=LifecycleState.CREATED, evaluation_context=ctx,
                observed_at=t, detected_at=t, source_bars=(), producer=prov, event_revision=1,
            )
            events.append(ev)

    return events


def run_e3e_benchmarks():
    print("=== PHASE E3-E: DISTINCT BENCHMARK RUNNER ===")
    results = {}
    scenarios = [
        "NO_MATCH_CONTROL",
        "MULTI_STEP_MODERATE",
        "OVERLAP_STRESS",
        "REVISION_INVALIDATION",
        "HISTORICAL_STREAM",
    ]
    sizes = [500, 5000, 50000]

    for scenario in scenarios:
        results[scenario] = {}
        for size in sizes:
            events = generate_benchmark_scenario_events(size, scenario)
            defs = [d for d in get_e3_setup_definitions() if d.status in ("HISTORICALLY_SUPPORTED_RESEARCH", "ACTIVE")]

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

                # Build distinct summary string for checksum hashing
                cands_summary = "".join(f"{c.setup_key}:{c.record_id}:{c.status.name}" for c in composer.candidates)
                distinct_summary = f"{scenario}:{size}:{len(events)}:{len(composer.candidates)}:{cands_summary}"
                checksum = hashlib.sha256(distinct_summary.encode("utf-8")).hexdigest()
                checksums.append(checksum)

            median_sec = sorted(runs_ns)[len(runs_ns)//2] / 1e9
            events_per_sec = size / median_sec if median_sec > 0 else 0

            # Verify assertions
            if scenario == "NO_MATCH_CONTROL" and cands_counts[0] > 0:
                raise ValueError("NO_MATCH_CONTROL produced candidates! Benchmark failed!")

            print(f"[{scenario:22s}] Size {size:5d} -> Median: {median_sec:.6f}s ({events_per_sec:,.1f} ev/s) | Candidates: {cands_counts[0]} | Checksum: {checksums[0][:12]}")

            results[scenario][str(size)] = {
                "scenario": scenario,
                "input_records": size,
                "unique_record_ids": len(set(e.record_id for e in events)),
                "predicate_evaluations": size * len(defs),
                "candidates_created": cands_counts[0],
                "median_seconds": round(median_sec, 6),
                "events_per_second": round(events_per_sec, 1),
                "output_checksum": checksums[0],
            }

    out_file = Path("/Users/ayushmudgal/Developer/CitadelOS-Tooling/recovery/EYE_ENGINE_E3E_PERFORMANCE_20260806.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2))
    print("Benchmark performance report written to", out_file)
    return "PASS"


if __name__ == "__main__":
    run_e3e_benchmarks()
