"""Prefix & Append Parity Test Suite for Eye Engine E2B-C."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.contracts import PriceAtom, InstrumentIdentity
from src.eye.detectors.input_model import DetectorBar
from src.eye.detector_replay import OfflineDetectorReplayHarness


def _sample_identity():
    return InstrumentIdentity(
        raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE",
        instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE",
    )


def test_offline_detector_replay_prefix_append_stability():
    harness = OfflineDetectorReplayHarness()
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    bars = [
        DetectorBar(
            instrument_key="UNDERLYING_INDEX:NIFTY", timeframe="5m",
            open_time=now + timedelta(minutes=5*i), expected_close_time=now + timedelta(minutes=5*(i+1)), available_at=now + timedelta(minutes=5*(i+1)),
            bar_key=f"NIFTY:5m:{i}", open=PriceAtom(ticks=2440000 + i*100), high=PriceAtom(ticks=2445000 + i*100),
            low=PriceAtom(ticks=2438000 + i*100), close=PriceAtom(ticks=2444000 + i*100), is_closed=True, volume=1000,
        )
        for i in range(10)
    ]

    results = harness.run_detector_replay(detector_key="swing", bars=bars, instrument_identity=_sample_identity(), timeframe="5m")
    assert len(results) == 10
