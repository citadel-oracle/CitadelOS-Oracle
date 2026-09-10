"""Phase M — Event Density and Burst Audit Test Suite."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.contracts import PriceAtom, InstrumentIdentity
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.swing_state import SwingStateDetector
from src.eye.detectors.diagnostics import summarize_detector_results


def _sample_identity():
    return InstrumentIdentity(
        raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE",
        instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE",
    )


def test_event_density_and_duplicate_control():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    bars = [
        DetectorBar(
            instrument_key="UNDERLYING_INDEX:NIFTY", timeframe="5m",
            open_time=now + timedelta(minutes=5*i), expected_close_time=now + timedelta(minutes=5*(i+1)), available_at=now + timedelta(minutes=5*(i+1)),
            bar_key=f"NIFTY:5m:{i}", open=PriceAtom(ticks=2440000), high=PriceAtom(ticks=2445000),
            low=PriceAtom(ticks=2438000), close=PriceAtom(ticks=2444000), is_closed=True, volume=1000,
        )
        for i in range(10)
    ]
    ctx = DetectorContext(instrument=_sample_identity(), timeframe="5m", as_of=now + timedelta(minutes=50))
    res = SwingStateDetector().detect(bars, ctx)
    summary = summarize_detector_results([res])

    # Unique event keys
    event_keys = set(r.event_key for r in res.records)
    assert len(event_keys) == len(res.records) # NO DUPLICATE EVENT KEYS!
