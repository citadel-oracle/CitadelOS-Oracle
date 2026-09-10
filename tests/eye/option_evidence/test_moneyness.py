"""E4A Moneyness Classification Tests."""

import pytest
from datetime import datetime, timezone
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.moneyness import classify_moneyness, MoneynessState
from src.eye.contracts import PriceAtom


def test_moneyness_classification_and_decomposition():
    now = datetime(2026, 8, 6, 9, 15, tzinfo=timezone.utc)
    expiry = datetime(2026, 8, 13, 15, 30, tzinfo=timezone.utc)

    cid_ce = OptionContractIdentity.create(
        exchange="NSE", segment="NSE_FO", security_id="43210",
        underlying_security_id="13", underlying_symbol="NIFTY",
        underlying_instrument_key="NSE:NIFTY:UNDERLYING_INDEX",
        derivative_instrument_type="OPTIDX", option_type="CE",
        expiry_date=expiry.date(), expiry_timestamp=expiry,
        expiry_class="WEEKLY", strike=PriceAtom(ticks=2450000),
        tick_size=PriceAtom(ticks=5), lot_size=25, source="DHAN_INSTRUMENT_MASTER",
        effective_time=now,
    )

    # 1. Spot 24600 vs Strike 24500 CE -> ITM (Intrinsic = 100)
    res_itm = classify_moneyness(cid_ce, 24600.0, option_price=120.0)
    assert res_itm.moneyness_state == MoneynessState.ITM
    assert res_itm.intrinsic_value == 100.0
    assert res_itm.time_value == 20.0

    # 2. Spot 24400 vs Strike 24500 CE -> OTM (Intrinsic = 0)
    res_otm = classify_moneyness(cid_ce, 24400.0, option_price=30.0)
    assert res_otm.moneyness_state == MoneynessState.OTM
    assert res_otm.intrinsic_value == 0.0
    assert res_otm.time_value == 30.0
