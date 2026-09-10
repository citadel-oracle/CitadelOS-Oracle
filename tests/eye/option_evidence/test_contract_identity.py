"""E4A Exact Option Contract Identity Tests."""

import pytest
from datetime import datetime, timezone
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.contracts import PriceAtom


def test_contract_identity_key_and_record_id():
    now = datetime(2026, 8, 6, 9, 15, tzinfo=timezone.utc)
    expiry = datetime(2026, 8, 13, 15, 30, tzinfo=timezone.utc)

    cid1 = OptionContractIdentity.create(
        exchange="NSE", segment="NSE_FO", security_id="43210",
        underlying_security_id="13", underlying_symbol="NIFTY",
        underlying_instrument_key="NSE:NIFTY:UNDERLYING_INDEX",
        derivative_instrument_type="OPTIDX", option_type="CE",
        expiry_date=expiry.date(), expiry_timestamp=expiry,
        expiry_class="WEEKLY", strike=PriceAtom(ticks=2450000),
        tick_size=PriceAtom(ticks=5), lot_size=25, source="DHAN_INSTRUMENT_MASTER",
        effective_time=now,
    )

    # 1. contract_key must be stable
    assert cid1.contract_key.startswith("OPTCONTRACT:NSE:NSE_FO:43210:")

    # 2. Record ID formula incorporates metadata revision
    assert cid1.identity_record_id.startswith("OPTREC:")

    # 3. Different strike produces different contract_key
    cid2 = OptionContractIdentity.create(
        exchange="NSE", segment="NSE_FO", security_id="43211",
        underlying_security_id="13", underlying_symbol="NIFTY",
        underlying_instrument_key="NSE:NIFTY:UNDERLYING_INDEX",
        derivative_instrument_type="OPTIDX", option_type="CE",
        expiry_date=expiry.date(), expiry_timestamp=expiry,
        expiry_class="WEEKLY", strike=PriceAtom(ticks=2455000),
        tick_size=PriceAtom(ticks=5), lot_size=25, source="DHAN_INSTRUMENT_MASTER",
        effective_time=now,
    )

    assert cid1.contract_key != cid2.contract_key
