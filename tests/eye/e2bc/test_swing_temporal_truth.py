"""Phase D — Swing Temporal Truth Test Suite."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.contracts import PriceAtom, InstrumentIdentity, EventType, EventFamily
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.detectors.swing_state import SwingStateDetector


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


def test_swing_causal_right_side_confirmation_no_backdating():
    # 5-bar sequence: L1, L2, PIVOT, R1, R2
    prices = [
        (24400, 24450, 24390, 24440),
        (24440, 24500, 24430, 24490),
        (24490, 24550, 24480, 24540), # Pivot high at index 2 (15:10)
        (24500, 24510, 24470, 24500), # R1 (15:15)
        (24450, 24480, 24420, 24430), # R2 (15:20) - Confirmation bar!
    ]
    bars = _build_bars(prices)
    ctx = DetectorContext(instrument=_sample_identity(), timeframe="5m", as_of=bars[-1].expected_close_time)
    detector = SwingStateDetector(left_bars=2, right_bars=2)

    # 1. Run prefix before R2 is closed -> MUST ABSTAIN
    ctx_early = DetectorContext(instrument=_sample_identity(), timeframe="5m", as_of=bars[3].expected_close_time)
    res_early = detector.detect(bars[:4], ctx_early)
    assert len(res_early.records) == 0

    # 2. Run full prefix after R2 is closed -> CONFIRMED
    res_full = detector.detect(bars, ctx)
    assert len(res_full.records) == 1
    rec = res_full.records[0]
    assert rec.event_type == EventType.SWING_HIGH
    assert rec.observed_at == bars[2].expected_close_time # Pivot market timestamp
    assert rec.detected_at == bars[4].expected_close_time # Confirmation timestamp (NO BACKDATING!)
