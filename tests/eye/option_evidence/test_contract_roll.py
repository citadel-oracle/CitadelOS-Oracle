"""E4A Contract Roll & Transition Tests."""

import pytest
from datetime import datetime, timezone
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.contracts import PriceAtom


def test_contract_roll_creates_new_contract_key():
    now = datetime(2026, 8, 6, 9, 15, tzinfo=timezone.utc)
    exp1 = datetime(2026, 8, 13, 15, 30, tzinfo=timezone.utc)
    exp2 = datetime(2026, 8, 20, 15, 30, tzinfo=timezone.utc)

    cid1 = OptionContractIdentity.create(
        exchange="NSE", segment="NSE_FO", security_id="43210",
        underlying_security_id="13", underlying_symbol="NIFTY",
        underlying_instrument_key="NSE:NIFTY:UNDERLYING_INDEX",
        derivative_instrument_type="OPTIDX", option_type="CE",
        expiry_date=exp1.date(), expiry_timestamp=exp1,
        expiry_class="WEEKLY", strike=PriceAtom(ticks=2450000),
        tick_size=PriceAtom(ticks=5), lot_size=25, source="DHAN_INSTRUMENT_MASTER",
        effective_time=now,
    )

    cid2 = OptionContractIdentity.create(
        exchange="NSE", segment="NSE_FO", security_id="43211",
        underlying_security_id="13", underlying_symbol="NIFTY",
        underlying_instrument_key="NSE:NIFTY:UNDERLYING_INDEX",
        derivative_instrument_type="OPTIDX", option_type="CE",
        expiry_date=exp2.date(), expiry_timestamp=exp2,
        expiry_class="WEEKLY", strike=PriceAtom(ticks=2450000),
        tick_size=PriceAtom(ticks=5), lot_size=25, source="DHAN_INSTRUMENT_MASTER",
        effective_time=now,
    )

    assert cid1.contract_key != cid2.contract_key
