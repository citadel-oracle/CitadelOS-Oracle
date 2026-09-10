"""Phase J — Multi-Timeframe Completion Test Suite."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.contracts import PriceAtom, InstrumentIdentity
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.detector_result import DetectorAbstentionReason
from src.eye.detectors.mtf_coordinator import MultiTimeframeCoordinator


def _sample_identity():
    return InstrumentIdentity(
        raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE",
        instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE",
    )


def test_mtf_coordinator_rejects_incomplete_htf_bar():
    coordinator = MultiTimeframeCoordinator()
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    bar1 = DetectorBar(
        instrument_key="UNDERLYING_INDEX:NIFTY", timeframe="1m",
        open_time=now, expected_close_time=now + timedelta(minutes=1), available_at=now + timedelta(minutes=1),
        bar_key="NIFTY:1m:0", open=PriceAtom(ticks=2440000), high=PriceAtom(ticks=2445000),
        low=PriceAtom(ticks=2439000), close=PriceAtom(ticks=2444000), is_closed=True, volume=100,
    )
    ctx = DetectorContext(instrument=_sample_identity(), timeframe="5m", as_of=now)

    is_valid, abst = coordinator.validate_htf_completion([bar1], "5m", ctx)
    assert is_valid is False
    assert abst.code == DetectorAbstentionReason.INCOMPLETE_HIGHER_TIMEFRAME
