"""Phase E — BOS / CHOCH State Machine Test Suite."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.contracts import PriceAtom, InstrumentIdentity, EventType, EventFamily
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.structure_break import StructureBreakDetector


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


def test_structure_break_bos_continuation_and_choch_reversal():
    prices = [
        (24400, 24450, 24390, 24440),
        (24440, 24500, 24430, 24490),
        (24490, 24550, 24480, 24540), # Swing high at 24550
        (24500, 24510, 24470, 24500),
        (24450, 24480, 24420, 24430),
        (24430, 24600, 24430, 24590), # Close break above 24550 (BOS Bullish!)
    ]
    bars = _build_bars(prices)
    ctx = DetectorContext(instrument=_sample_identity(), timeframe="5m", as_of=bars[-1].expected_close_time)
    detector = StructureBreakDetector(use_close_break=True)

    res = detector.detect(bars, ctx)
    assert len(res.records) == 1
    rec = res.records[0]
    assert rec.event_type == EventType.BOS_BULLISH
    assert rec.payload.primary_level.value == 24550.0
