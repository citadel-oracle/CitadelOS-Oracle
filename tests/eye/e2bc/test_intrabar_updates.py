"""Phase I — Provisional Intrabar Truth Test Suite."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.contracts import PriceAtom
from src.eye.detectors.input_model import BarUpdate


def test_bar_update_sequence_creation():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    update1 = BarUpdate(
        target_bar_key="NIFTY:5m:1530",
        update_sequence=1,
        update_time=now,
        high_so_far=PriceAtom(ticks=2450000),
        low_so_far=PriceAtom(ticks=2440000),
        close_so_far=PriceAtom(ticks=2445000),
        is_final=False,
    )
    assert update1.update_sequence == 1
    assert update1.is_final is False
