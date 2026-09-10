"""E4A Price Reference Policy Tests."""

import pytest
from src.eye.contracts import PriceAtom
from src.eye.option_evidence.contracts import PriceReference
from src.eye.option_evidence.mark_prices import get_reference_price


def test_price_reference_policy_resolutions():
    bid = PriceAtom(ticks=15000)  # 150.00
    ask = PriceAtom(ticks=15050)  # 150.50
    ltp = PriceAtom(ticks=15020)  # 150.20

    # Best Ask
    p_ask = get_reference_price(bid, ask, ltp, PriceReference.BEST_ASK)
    assert p_ask == 150.50

    # Best Bid
    p_bid = get_reference_price(bid, ask, ltp, PriceReference.BEST_BID)
    assert p_bid == 150.00

    # Midpoint
    p_mid = get_reference_price(bid, ask, ltp, PriceReference.MIDPOINT)
    assert p_mid == 150.25

    # LTP
    p_ltp = get_reference_price(bid, ask, ltp, PriceReference.LAST_TRADED_PRICE)
    assert p_ltp == 150.20
