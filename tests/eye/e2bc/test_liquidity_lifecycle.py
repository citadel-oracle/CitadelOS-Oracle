"""Phase F — Liquidity Lifecycle Test Suite."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.contracts import PriceAtom, InstrumentIdentity, EventType
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.liquidity import LiquidityDetector


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
        actual_h = max(o, h, c)
        actual_l = min(o, l, c)
        bar = DetectorBar(
            instrument_key="UNDERLYING_INDEX:NIFTY", timeframe="5m",
            open_time=t, expected_close_time=t + timedelta(minutes=5), available_at=t + timedelta(minutes=5),
            bar_key=f"NIFTY:5m:{i}", open=PriceAtom(ticks=int(o * 100)), high=PriceAtom(ticks=int(actual_h * 100)),
            low=PriceAtom(ticks=int(actual_l * 100)), close=PriceAtom(ticks=int(c * 100)), is_closed=True, volume=1000,
        )
        bars.append(bar)
    return bars


def test_liquidity_pool_creation_and_sweep_lifecycle():
    prices = [
        (24400, 24500, 24390, 24440), # Touch 1 high = 24500
        (24440, 24480, 24420, 24470),
        (24470, 24500, 24450, 24490), # Touch 2 high = 24500 (Equal Highs Pool!)
        (24470, 24480, 24430, 24460),
        (24460, 24530, 24450, 24480), # Same-bar wick sweep above 24500, close 24480
    ]
    bars = _build_bars(prices)
    ctx = DetectorContext(instrument=_sample_identity(), timeframe="5m", as_of=bars[-1].expected_close_time)
    detector = LiquidityDetector(tolerance_ticks=5)

    res = detector.detect(bars, ctx)
    assert len(res.records) >= 2
    types = [r.event_type for r in res.records]
    assert EventType.LIQUIDITY_POOL_HIGH in types
    assert EventType.LIQUIDITY_SWEEP_HIGH in types
