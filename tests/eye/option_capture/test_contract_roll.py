"""E4A-E Test for Contract Roll Identity Isolation."""

from datetime import datetime, date, timezone
import pytest
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.contracts import PriceAtom


def test_contract_roll_creates_distinct_keys():
    now = datetime(2026, 8, 7, 9, 15, tzinfo=timezone.utc)
    cid_aug = OptionContractIdentity.create(
        exchange="NSE", segment="NSE_FO", security_id="43210",
        underlying_security_id="13", underlying_symbol="NIFTY",
        underlying_instrument_key="NSE:NIFTY:UNDERLYING_INDEX",
        derivative_instrument_type="OPTIDX", option_type="CE",
        expiry_date=date(2026, 8, 13), expiry_timestamp=datetime(2026, 8, 13, 15, 30, tzinfo=timezone.utc),
        expiry_class="WEEKLY", strike=PriceAtom(ticks=2450000),
        tick_size=PriceAtom(ticks=5), lot_size=25, source="DHAN_INSTRUMENT_MASTER",
        effective_time=now,
    )
    cid_sep = OptionContractIdentity.create(
        exchange="NSE", segment="NSE_FO", security_id="43290",
        underlying_security_id="13", underlying_symbol="NIFTY",
        underlying_instrument_key="NSE:NIFTY:UNDERLYING_INDEX",
        derivative_instrument_type="OPTIDX", option_type="CE",
        expiry_date=date(2026, 8, 20), expiry_timestamp=datetime(2026, 8, 20, 15, 30, tzinfo=timezone.utc),
        expiry_class="WEEKLY", strike=PriceAtom(ticks=2450000),
        tick_size=PriceAtom(ticks=5), lot_size=25, source="DHAN_INSTRUMENT_MASTER",
        effective_time=now,
    )

    assert cid_aug.contract_key != cid_sep.contract_key
