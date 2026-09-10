"""Phase H — FVG Child and Aggregate Truth Test Suite."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.contracts import PriceAtom, InstrumentIdentity, EventType
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.fvg_cluster import FVGClusterDetector


def _sample_identity():
    return InstrumentIdentity(
        raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE",
        instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE",
    )


def _build_bars(prices):
    t0 = datetime(2026, 8, 6, 15, 0, tzinfo=timezone.utc)
    bars = []
    for i, (o, h, l, c) in enumerate(prices):
        t = t0 + timedelta(minutes=5 * i)
        bar = DetectorBar(
            instrument_key="UNDERLYING_INDEX:NIFTY", timeframe="5m",
            open_time=t, expected_close_time=t + timedelta(minutes=5), available_at=t + timedelta(minutes=5),
            bar_key=f"NIFTY:5m:{i}", open=PriceAtom(ticks=int(o * 100)), high=PriceAtom(ticks=int(h * 100)),
            low=PriceAtom(ticks=int(l * 100)), close=PriceAtom(ticks=int(c * 100)), is_closed=True, volume=1000,
        )
        bars.append(bar)
    return bars


def test_fvg_child_and_aggregate_zones_non_destructive():
    prices = [
        (24400, 24450, 24390, 24440), # Bar 1 high = 24450
        (24440, 24520, 24440, 24510), # Bar 2
        (24510, 24600, 24480, 24590), # Bar 3 low = 24480 (Gap: 24450 - 24480!)
        (24590, 24680, 24560, 24670), # Bar 4 low = 24560 (Second gap!)
    ]
    bars = _build_bars(prices)
    ctx = DetectorContext(instrument=_sample_identity(), timeframe="5m", as_of=bars[-1].expected_close_time)
    detector = FVGClusterDetector()

    res = detector.detect(bars, ctx)
    assert len(res.records) >= 2
    types = [r.event_type for r in res.records]
    assert EventType.FVG_BULLISH in types
