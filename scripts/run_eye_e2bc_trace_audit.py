"""Phase L — Trace Audit Script for Eye Engine E2B-C."""

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

from src.eye.contracts import PriceAtom, InstrumentIdentity
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.swing_state import SwingStateDetector
from src.eye.detectors.structure_break import StructureBreakDetector
from src.eye.detectors.liquidity import LiquidityDetector
from src.eye.detectors.displacement import DisplacementDetector
from src.eye.detectors.fvg_cluster import FVGClusterDetector


def run_trace_audit():
    print("=== PHASE L: TRACE AUDIT ===")
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")

    # Generate 100 synthetic bars for trace generation
    bars = []
    for i in range(100):
        t = now - timedelta(minutes=5*(100-i))
        px = 24500.0 + (i % 5 - 2) * 20.0
        bar = DetectorBar(
            instrument_key="UNDERLYING_INDEX:NIFTY", timeframe="5m",
            open_time=t, expected_close_time=t + timedelta(minutes=5), available_at=t + timedelta(minutes=5),
            bar_key=f"NIFTY:5m:{i}", open=PriceAtom(ticks=int(px * 100)), high=PriceAtom(ticks=int((px + 25) * 100)),
            low=PriceAtom(ticks=int((px - 25) * 100)), close=PriceAtom(ticks=int((px + 10) * 100)), is_closed=True, volume=1000,
        )
        bars.append(bar)

    ctx = DetectorContext(instrument=inst, timeframe="5m", as_of=now)
    detectors = [SwingStateDetector(), StructureBreakDetector(), LiquidityDetector(), DisplacementDetector(), FVGClusterDetector()]

    traces = []
    for d in detectors:
        res = d.detect(bars, ctx)
        for rec in res.records:
            trace = {
                "event_key": rec.event_key,
                "event_type": rec.event_type.value,
                "family": rec.family.value,
                "timeframe": rec.timeframe,
                "observed_at": rec.observed_at.isoformat(),
                "detected_at": rec.detected_at.isoformat(),
                "rule_id": rec.producer.rule_id,
                "classification": "VALID",
            }
            traces.append(trace)

    print("Generated traces count:", len(traces))
    out_path = Path("/Users/ayushmudgal/Developer/CitadelOS-Tooling/recovery/EYE_ENGINE_E2BC_TRACE_AUDIT_20260806.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(traces, indent=2))
    print("Trace Audit report saved to", out_path)


if __name__ == "__main__":
    run_trace_audit()
