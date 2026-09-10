"""E4A-C Test for Prefix Temporal as_of Alignment."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.detectors.input_model import DetectorBar, DetectorContext
from src.eye.contracts import PriceAtom, InstrumentIdentity


def test_prefix_context_as_of_equals_current_bar_time():
    t_bar = datetime(2026, 8, 6, 9, 20, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")

    ctx = DetectorContext(instrument=inst, timeframe="5m", as_of=t_bar)

    assert ctx.as_of == t_bar
