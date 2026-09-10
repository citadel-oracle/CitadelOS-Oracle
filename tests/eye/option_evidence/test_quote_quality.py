"""E4A Quote Quality Classifier Tests."""

import pytest
from datetime import datetime, timezone
from src.eye.contracts import PriceAtom
from src.eye.option_evidence.contracts import QuoteState
from src.eye.option_evidence.quote_quality import classify_quote_quality


def test_quote_quality_classification_states():
    now = datetime(2026, 8, 6, 9, 15, tzinfo=timezone.utc)

    # 1. Two-sided valid
    bid = PriceAtom(ticks=15000)
    ask = PriceAtom(ticks=15050)
    m1 = classify_quote_quality(bid, ask, 100, 100, observed_at=now, evaluation_time=now)
    assert m1.quote_state == QuoteState.TWO_SIDED_VALID
    assert m1.spread_absolute == 0.50
    assert m1.midpoint == 150.25
    assert m1.is_executable is True

    # 2. Crossed quote (bid > ask)
    bid_c = PriceAtom(ticks=15100)
    ask_c = PriceAtom(ticks=15000)
    m2 = classify_quote_quality(bid_c, ask_c, 100, 100)
    assert m2.quote_state == QuoteState.CROSSED
    assert m2.is_executable is False

    # 3. Locked quote (bid == ask)
    bid_l = PriceAtom(ticks=15000)
    ask_l = PriceAtom(ticks=15000)
    m3 = classify_quote_quality(bid_l, ask_l, 100, 100)
    assert m3.quote_state == QuoteState.LOCKED
    assert m3.is_executable is False

    # 4. Bid only
    m4 = classify_quote_quality(bid, None)
    assert m4.quote_state == QuoteState.BID_ONLY

    # 5. Ask only
    m5 = classify_quote_quality(None, ask)
    assert m5.quote_state == QuoteState.ASK_ONLY
