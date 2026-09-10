"""Phase N — Performance Benchmark Test Suite."""

import pytest
import time
from datetime import datetime, timezone, timedelta
from src.eye.contracts import PriceAtom, InstrumentIdentity
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.swing_state import SwingStateDetector


def _sample_identity():
    return InstrumentIdentity(
        raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE",
        instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE",
    )


def test_performance_500_bars():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    bars = [
        DetectorBar(
            instrument_key="UNDERLYING_INDEX:NIFTY", timeframe="5m",
            open_time=now + timedelta(minutes=5*i), expected_close_time=now + timedelta(minutes=5*(i+1)), available_at=now + timedelta(minutes=5*(i+1)),
            bar_key=f"NIFTY:5m:{i}", open=PriceAtom(ticks=2440000), high=PriceAtom(ticks=2445000),
            low=PriceAtom(ticks=2438000), close=PriceAtom(ticks=2444000), is_closed=True, volume=1000,
        )
        for i in range(500)
    ]
    ctx = DetectorContext(instrument=_sample_identity(), timeframe="5m", as_of=bars[-1].expected_close_time)
    t0 = time.time()
    res = SwingStateDetector().detect(bars, ctx)
    t1 = time.time()
    elapsed = t1 - t0
    assert elapsed < 2.0 # 500 bars processed under 2s!
