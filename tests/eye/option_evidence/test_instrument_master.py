"""E4A Instrument Master Tests."""

import pytest
from datetime import datetime, timezone
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.instrument_master import InstrumentMasterRegistry
from src.eye.contracts import PriceAtom


def test_instrument_master_resolution_and_registration():
    now = datetime(2026, 8, 6, 9, 15, tzinfo=timezone.utc)
    expiry = datetime(2026, 8, 13, 15, 30, tzinfo=timezone.utc)

    cid = OptionContractIdentity.create(
        exchange="NSE", segment="NSE_FO", security_id="43210",
        underlying_security_id="13", underlying_symbol="NIFTY",
        underlying_instrument_key="NSE:NIFTY:UNDERLYING_INDEX",
        derivative_instrument_type="OPTIDX", option_type="CE",
        expiry_date=expiry.date(), expiry_timestamp=expiry,
        expiry_class="WEEKLY", strike=PriceAtom(ticks=2450000),
        tick_size=PriceAtom(ticks=5), lot_size=25, source="DHAN_INSTRUMENT_MASTER",
        effective_time=now,
    )

    reg = InstrumentMasterRegistry()
    reg.register(cid)

    # 1. Lookup by security ID
    found_sec = reg.get_by_security_id("43210")
    assert found_sec is not None
    assert found_sec.contract_key == cid.contract_key

    # 2. Resolve contract by underlying, expiry, strike, option_type
    res = reg.resolve_option_contract("NIFTY", expiry.date(), PriceAtom(ticks=2450000), "CE")
    assert res is not None
    assert res.security_id == "43210"
