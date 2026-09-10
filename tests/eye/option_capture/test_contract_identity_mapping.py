"""E4A-E Test for Option Contract Identity Mapping."""

from datetime import datetime, date, timezone
import pytest
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.contracts import PriceAtom


def test_contract_identity_key_generation():
    now = datetime(2026, 8, 7, 9, 15, tzinfo=timezone.utc)
    exp = date(2026, 8, 13)
    cid = OptionContractIdentity.create(
        exchange="NSE", segment="NSE_FO", security_id="43210",
        underlying_security_id="13", underlying_symbol="NIFTY",
        underlying_instrument_key="NSE:NIFTY:UNDERLYING_INDEX",
        derivative_instrument_type="OPTIDX", option_type="CE",
        expiry_date=exp, expiry_timestamp=datetime(2026, 8, 13, 15, 30, tzinfo=timezone.utc),
        expiry_class="WEEKLY", strike=PriceAtom(ticks=2450000),
        tick_size=PriceAtom(ticks=5), lot_size=25, source="DHAN_INSTRUMENT_MASTER",
        effective_time=now,
    )

    assert cid.contract_key == "OPTCONTRACT:NSE:NSE_FO:43210:NSE:NIFTY:UNDERLYING_INDEX:2026-08-13:2450000:CE:OPTIDX"
    assert cid.security_id == "43210"
