"""Historical Detector Scan Script for Eye Engine E2B."""

import json
from datetime import datetime, timezone, timedelta

from src.eye.contracts import PriceAtom, InstrumentIdentity
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.swing_state import SwingStateDetector
from src.eye.detectors.structure_break import StructureBreakDetector
from src.eye.detectors.liquidity import LiquidityDetector
from src.eye.detectors.displacement import DisplacementDetector
from src.eye.detectors.fvg_cluster import FVGClusterDetector
from src.eye.detectors.diagnostics import summarize_detector_results


def run_historical_scan():
    print("=== RUNNING E2B HISTORICAL DETECTOR SCAN ===")
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")

    # Generate 50 synthetic 5m bars
    bars = []
    base_price = 24500.0
    for i in range(50):
        t = now - timedelta(minutes=5 * (50 - i))
        px = base_price + (i % 7 - 3) * 15.0
        bar = DetectorBar(
            instrument_key="UNDERLYING_INDEX:NIFTY", timeframe="5m",
            open_time=t, expected_close_time=t + timedelta(minutes=5), available_at=t + timedelta(minutes=5),
            bar_key=f"NIFTY:5m:{i}", open=PriceAtom(ticks=int(px * 100)), high=PriceAtom(ticks=int((px + 20) * 100)),
            low=PriceAtom(ticks=int((px - 20) * 100)), close=PriceAtom(ticks=int((px + 10) * 100)), is_closed=True, volume=1500,
        )
        bars.append(bar)

    ctx = DetectorContext(instrument=inst, timeframe="5m", as_of=now)

    detectors = [
        SwingStateDetector(),
        StructureBreakDetector(),
        LiquidityDetector(),
        DisplacementDetector(),
        FVGClusterDetector(),
    ]

    results = [d.detect(bars, ctx) for d in detectors]
    summary = summarize_detector_results(results)

    print("Historical Scan Summary:")
    print("  Total Records Detected:", summary.total_records)
    print("  Total Abstentions:", summary.total_abstentions)
    print("  Detector Families Audited:", summary.families_detected)
    print("HISTORICAL SCAN SUCCESS!")


if __name__ == "__main__":
    run_historical_scan()
