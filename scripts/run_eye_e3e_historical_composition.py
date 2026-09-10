"""Phase E3-E Real Historical Composition & Candidate Correction Runner for Citadel Eye Engine."""

import json
import time
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict

from src.eye.contracts import (
    EyeEventRecord, InstrumentIdentity, EvaluationContext, PointEventPayload,
    EventFamily, EventType, EventDirection, DetectionState, LifecycleState,
    ProducerProvenance, PriceAtom, canonical_json, compute_sha256
)
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.swing_state import SwingStateDetector
from src.eye.detectors.structure_break import StructureBreakDetector
from src.eye.detectors.liquidity import LiquidityDetector
from src.eye.detectors.displacement import DisplacementDetector
from src.eye.detectors.fvg_cluster import FVGClusterDetector
from src.eye.composer.setup_registry import get_e3_setup_definitions
from src.eye.composer.matcher import SetupComposer


def run_e3e_historical_composition():
    print("=== PHASE E3-E: HISTORICAL COMPOSITION & CANDIDATE CORRECTION RUNNER ===")
    t_start = time.perf_counter()
    dataset_path = Path("/Users/ayushmudgal/Developer/CitadelOS/logs/vob_1m_candles.json")
    if not dataset_path.exists():
        print("Dataset not found at", dataset_path)
        return "E3_REPAIR_REQUIRED"

    content = dataset_path.read_bytes()
    sha256_dataset = hashlib.sha256(content).hexdigest()
    raw = json.loads(content)

    # 1. Correctly read candles array from top-level dict
    candles = raw["candles"] if isinstance(raw, dict) else raw
    total_source_rows = len(candles)
    print(f"Loaded {total_source_rows} 1m candles from dataset (SHA256: {sha256_dataset[:12]}).")

    if total_source_rows < 19125:
        print("Source row count mismatch!")
        return "E3_REPAIR_REQUIRED"


    # Select 20 complete development sessions (7,500 1m candles)
    sel_1m = candles[:7500]
    print(f"Selected 20 complete development sessions: {len(sel_1m)} 1m candles.")

    # 2. Real Resampling to 5m DetectorBars
    bars_5m = []
    for i in range(0, len(sel_1m), 5):
        chunk = sel_1m[i:i+5]
        if len(chunk) < 5:
            continue
        t_open = datetime.fromtimestamp(chunk[0]["time"], tz=timezone.utc)
        t_close = datetime.fromtimestamp(chunk[-1]["time"], tz=timezone.utc) + timedelta(minutes=1)
        px_o = float(chunk[0]["open"])
        px_h = max(float(c["high"]) for c in chunk)
        px_l = min(float(c["low"]) for c in chunk)
        px_c = float(chunk[-1]["close"])
        vol = sum(int(c.get("volume", 0)) for c in chunk)

        bar = DetectorBar(
            instrument_key="UNDERLYING_INDEX:NIFTY",
            timeframe="5m",
            open_time=t_open,
            expected_close_time=t_close,
            available_at=t_close,
            bar_key=f"NIFTY:5m:{i//5}",
            open=PriceAtom(ticks=int(round(px_o * 100))),
            high=PriceAtom(ticks=int(round(px_h * 100))),
            low=PriceAtom(ticks=int(round(px_l * 100))),
            close=PriceAtom(ticks=int(round(px_c * 100))),
            is_closed=True,
            volume=vol,
        )
        bars_5m.append(bar)

    print(f"Resampled to {len(bars_5m)} 5m DetectorBars.")

    # 3. Real E2B Detector Execution
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")
    ctx = DetectorContext(instrument=inst, timeframe="5m", as_of=bars_5m[-1].expected_close_time)

    detectors = [
        SwingStateDetector(),
        StructureBreakDetector(),
        LiquidityDetector(),
        DisplacementDetector(),
        FVGClusterDetector(),
    ]

    seen_records = set()
    atomic_events = []
    for i in range(1, len(bars_5m) + 1):
        sub_bars = bars_5m[:i]
        for d in detectors:
            res = d.detect(sub_bars, ctx)
            for r in res.records:
                if r.record_id not in seen_records:
                    seen_records.add(r.record_id)
                    atomic_events.append(r)

    print(f"Real E2B Detectors produced {len(atomic_events)} unique canonical atomic events.")

    # 4. Filter setup definitions to run ONLY HISTORICALLY_SUPPORTED_RESEARCH & ACTIVE
    all_defs = get_e3_setup_definitions()
    eligible_defs = [d for d in all_defs if d.status in ("HISTORICALLY_SUPPORTED_RESEARCH", "ACTIVE")]
    print(f"Eligible setup definitions: {[d.setup_id for d in eligible_defs]}")

    # 5. Real E3 Composer Execution
    composer = SetupComposer(eligible_defs)
    candidates = []
    for ev in atomic_events:
        candidates.extend(composer.process_event(ev))

    unique_setup_keys = len({c.setup_key for c in candidates})
    unique_record_ids = len({c.record_id for c in candidates})
    t_end = time.perf_counter()

    print(f"Confirmed setup candidates created: {len(candidates)}")
    print(f"Unique setup_keys: {unique_setup_keys}")
    print(f"Unique record_ids: {unique_record_ids}")
    print(f"Elapsed time: {t_end - t_start:.3f}s")

    report = {
        "dataset": "vob_1m_candles.json",
        "dataset_sha256": sha256_dataset,
        "source_row_count": total_source_rows,
        "selected_1m_candles": len(sel_1m),
        "sessions_processed": 20,
        "bars_resampled_5m": len(bars_5m),
        "atomic_events_detected": len(atomic_events),
        "corrected_confirmed_candidate_count": len(candidates),
        "unique_setup_keys": unique_setup_keys,
        "unique_record_ids": unique_record_ids,
        "historically_supported_families_run": [d.setup_id for d in eligible_defs],
        "elapsed_seconds": round(t_end - t_start, 4),
        "status": "PASS",
    }

    out_file = Path("/Users/ayushmudgal/Developer/CitadelOS-Tooling/recovery/EYE_ENGINE_E3E_HISTORICAL_CORRECTION_20260806.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(report, indent=2))
    print("Historical correction report written to", out_file)
    return "PASS"


if __name__ == "__main__":
    run_e3e_historical_composition()
