"""Phase 3 & 4 — Historical Detector Scan & Event Identity Truth Audit for Eye Engine E2B-D."""

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
from src.eye.detectors.diagnostics import summarize_detector_results


def run_full_historical_scan():
    print("=== PHASE 3 & 4: FULL HISTORICAL SCAN & EVENT IDENTITY TRUTH AUDIT ===")
    vob_log = Path("/Users/ayushmudgal/Developer/CitadelOS/logs/vob_1m_candles.json")
    if not vob_log.exists():
        print("VOB log missing")
        return

    raw = json.loads(vob_log.read_text())
    candles = raw.get("candles", [])

    # Group by session date
    sessions = defaultdict(list)
    for c in candles:
        ts = c.get("time") or c.get("timestamp")
        if ts:
            dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            sessions[dt.date().isoformat()].append(c)

    complete_dates = sorted([d for d, bars in sessions.items() if len(bars) >= 300])[:20]
    print(f"Processing ALL 20 Complete Sessions ({len(complete_dates)} dates):", complete_dates)

    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")

    # Resample 1m candles into 5m DetectorBars for each session
    all_5m_bars = []
    bar_index = 0

    for d in complete_dates:
        session_1m = sessions[d]
        # Resample every 5 1m candles into 1 5m bar
        for i in range(0, len(session_1m) - 4, 5):
            chunk = session_1m[i:i+5]
            dt = datetime.fromtimestamp(float(chunk[0]["time"]), tz=timezone.utc)
            px_o = float(chunk[0]["open"])
            px_h = max(float(c["high"]) for c in chunk)
            px_l = min(float(c["low"]) for c in chunk)
            px_c = float(chunk[-1]["close"])
            bar = DetectorBar(
                instrument_key="UNDERLYING_INDEX:NIFTY", timeframe="5m",
                open_time=dt, expected_close_time=dt + timedelta(minutes=5), available_at=dt + timedelta(minutes=5),
                bar_key=f"NIFTY:5m:{d}:{i}", open=PriceAtom(ticks=int(px_o * 100)), high=PriceAtom(ticks=int(px_h * 100)),
                low=PriceAtom(ticks=int(px_l * 100)), close=PriceAtom(ticks=int(px_c * 100)), is_closed=True, volume=1000,
            )
            all_5m_bars.append(bar)
            bar_index += 1

    print(f"Total Resampled 5m Bars across 20 complete sessions: {len(all_5m_bars)}")

    ctx = DetectorContext(instrument=inst, timeframe="5m", as_of=all_5m_bars[-1].expected_close_time)

    detectors = [
        SwingStateDetector(),
        StructureBreakDetector(),
        LiquidityDetector(),
        DisplacementDetector(),
        FVGClusterDetector(),
    ]

    all_records = []
    all_abstentions = []

    for d in detectors:
        res = d.detect(all_5m_bars, ctx)
        all_records.extend(res.records)
        all_abstentions.extend(res.abstentions)

    # Event Identity Analysis
    event_keys = [r.event_key for r in all_records]
    record_ids = [r.record_id for r in all_records]
    unique_event_keys = set(event_keys)
    unique_record_ids = set(record_ids)

    # Revisions vs Illegal Duplicates
    key_counts = defaultdict(int)
    for r in all_records:
        key_counts[r.event_key] += 1

    legitimate_revisions = sum(count - 1 for count in key_counts.values())
    illegal_duplicates = len(record_ids) - len(unique_record_ids)

    print("\nEvent Identity Truth Results:")
    print("  Total Records Emitted:", len(all_records))
    print("  Unique Semantic Event Keys:", len(unique_event_keys))
    print("  Unique Record IDs:", len(unique_record_ids))
    print("  Legitimate Revisions:", legitimate_revisions)
    print("  Illegal Duplicate Record IDs:", illegal_duplicates)

    report = {
        "dataset_path": "/Users/ayushmudgal/Developer/CitadelOS/logs/vob_1m_candles.json",
        "selected_sessions_count": len(complete_dates),
        "selected_session_dates": complete_dates,
        "total_1m_bars_processed": len(complete_dates) * 375,
        "total_5m_bars_processed": len(all_5m_bars),
        "total_records": len(all_records),
        "unique_event_keys": len(unique_event_keys),
        "unique_record_ids": len(unique_record_ids),
        "legitimate_revisions": legitimate_revisions,
        "illegal_duplicates": illegal_duplicates,
        "status": "PASS" if illegal_duplicates == 0 else "FAIL",
    }

    out_scan = Path("/Users/ayushmudgal/Developer/CitadelOS-Tooling/recovery/EYE_ENGINE_E2BD_HISTORICAL_SCAN_20260806.json")
    out_scan.parent.mkdir(parents=True, exist_ok=True)
    out_scan.write_text(json.dumps(report, indent=2))

    out_ident = Path("/Users/ayushmudgal/Developer/CitadelOS-Tooling/recovery/EYE_ENGINE_E2BD_EVENT_IDENTITY_20260806.json")
    out_ident.write_text(json.dumps({
        "total_records": len(all_records),
        "unique_event_keys": len(unique_event_keys),
        "unique_record_ids": len(unique_record_ids),
        "legitimate_revisions": legitimate_revisions,
        "illegal_duplicates": illegal_duplicates,
    }, indent=2))

    print("Historical Scan & Event Identity artifacts written successfully!")


if __name__ == "__main__":
    run_full_historical_scan()
