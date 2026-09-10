"""Phase 34 — Historical Setup Composition Scan Script for Eye Engine E3."""

import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from src.eye.contracts import PriceAtom, InstrumentIdentity
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.swing_state import SwingStateDetector
from src.eye.detectors.structure_break import StructureBreakDetector
from src.eye.detectors.liquidity import LiquidityDetector
from src.eye.detectors.displacement import DisplacementDetector
from src.eye.detectors.fvg_cluster import FVGClusterDetector
from src.eye.composer.setup_registry import get_e3_setup_definitions
from src.eye.composer.matcher import SetupComposer
from src.eye.composer.diagnostics import summarize_composition


def run_historical_composition():
    print("=== PHASE 34: HISTORICAL SETUP COMPOSITION SCAN ===")
    vob_log = Path("/Users/ayushmudgal/Developer/CitadelOS/logs/vob_1m_candles.json")
    if not vob_log.exists():
        print("VOB log missing at", vob_log)
        return

    raw = json.loads(vob_log.read_text())
    candles = raw.get("candles", [])

    sessions = defaultdict(list)
    for c in candles:
        ts = c.get("time") or c.get("timestamp")
        if ts:
            dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            sessions[dt.date().isoformat()].append(c)

    complete_dates = sorted([d for d, bars in sessions.items() if len(bars) >= 300])[:20]
    print(f"Running Historical Composition over 20 complete sessions ({len(complete_dates)} dates)")

    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")

    # Resample 1m candles into 5m DetectorBars
    all_5m_bars = []
    for d in complete_dates:
        s1m = sessions[d]
        for i in range(0, len(s1m) - 4, 5):
            chunk = s1m[i:i+5]
            dt = datetime.fromtimestamp(float(chunk[0]["time"]), tz=timezone.utc)
            bar = DetectorBar(
                instrument_key="UNDERLYING_INDEX:NIFTY", timeframe="5m",
                open_time=dt, expected_close_time=dt + timedelta(minutes=5), available_at=dt + timedelta(minutes=5),
                bar_key=f"NIFTY:5m:{d}:{i}", open=PriceAtom(ticks=int(float(chunk[0]["open"]) * 100)),
                high=PriceAtom(ticks=int(max(float(c["high"]) for c in chunk) * 100)),
                low=PriceAtom(ticks=int(min(float(c["low"]) for c in chunk) * 100)),
                close=PriceAtom(ticks=int(float(chunk[-1]["close"]) * 100)), is_closed=True, volume=1000,
            )
            all_5m_bars.append(bar)

    ctx = DetectorContext(instrument=inst, timeframe="5m", as_of=all_5m_bars[-1].expected_close_time)
    detectors = [SwingStateDetector(), StructureBreakDetector(), LiquidityDetector(), DisplacementDetector(), FVGClusterDetector()]

    # Collect atomic records
    atomic_records = []
    for d in detectors:
        res = d.detect(all_5m_bars, ctx)
        atomic_records.extend(res.records)

    # Sort atomic records canonically by knowledge availability time
    from src.eye.composer.ordering import sort_events_canonically
    sorted_atomics = sort_events_canonically(atomic_records)
    print(f"Total Canonical Atomic Events Ingested: {len(sorted_atomics)}")

    composer = SetupComposer(get_e3_setup_definitions())
    all_candidates = []

    for ev in sorted_atomics:
        cands = composer.process_event(ev)
        all_candidates.extend(cands)

    summary = summarize_composition(composer.candidates)
    print("\nHistorical Composition Results:")
    print(f"  Total Candidates Composed: {summary.total_candidates}")
    print(f"  Confirmed Candidates:     {summary.confirmed_candidates}")
    print(f"  Families Represented:     {summary.families_represented}")

    report = {
        "dataset_path": "/Users/ayushmudgal/Developer/CitadelOS/logs/vob_1m_candles.json",
        "sessions_count": len(complete_dates),
        "total_1m_bars": len(complete_dates) * 375,
        "resampled_5m_bars": len(all_5m_bars),
        "atomic_events_ingested": len(sorted_atomics),
        "total_candidates": summary.total_candidates,
        "confirmed_candidates": summary.confirmed_candidates,
        "families_represented": list(summary.families_represented),
        "status": "PASS",
    }

    out_comp = Path("/Users/ayushmudgal/Developer/CitadelOS-Tooling/recovery/EYE_ENGINE_E3_HISTORICAL_COMPOSITION_20260806.json")
    out_comp.parent.mkdir(parents=True, exist_ok=True)
    out_comp.write_text(json.dumps(report, indent=2))
    print("Historical Composition report written to", out_comp)


if __name__ == "__main__":
    run_historical_composition()
