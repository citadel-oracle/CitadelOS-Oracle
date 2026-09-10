"""E4A Identity Epoch Tests."""

import pytest
from datetime import datetime, timezone
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.contracts import PriceAtom


def test_identity_epoch_does_not_change_semantic_contract_key():
    now = datetime(2026, 8, 6, 9, 15, tzinfo=timezone.utc)
    exp = datetime(2026, 8, 13, 15, 30, tzinfo=timezone.utc)

    cid1 = OptionContractIdentity.create(
        exchange="NSE", segment="NSE_FO", security_id="43210",
        underlying_security_id="13", underlying_symbol="NIFTY",
        underlying_instrument_key="NSE:NIFTY:UNDERLYING_INDEX",
        derivative_instrument_type="OPTIDX", option_type="CE",
        expiry_date=exp.date(), expiry_timestamp=exp,
        expiry_class="WEEKLY", strike=PriceAtom(ticks=2450000),
        tick_size=PriceAtom(ticks=5), lot_size=25, source="DHAN_INSTRUMENT_MASTER",
        effective_time=now, identity_epoch=1,
    )

    cid2 = OptionContractIdentity.create(
        exchange="NSE", segment="NSE_FO", security_id="43210",
        underlying_security_id="13", underlying_symbol="NIFTY",
        underlying_instrument_key="NSE:NIFTY:UNDERLYING_INDEX",
        derivative_instrument_type="OPTIDX", option_type="CE",
        expiry_date=exp.date(), expiry_timestamp=exp,
        expiry_class="WEEKLY", strike=PriceAtom(ticks=2450000),
        tick_size=PriceAtom(ticks=5), lot_size=25, source="DHAN_INSTRUMENT_MASTER",
        effective_time=now, identity_epoch=2,
    )

    # Contract key remains identical across identity epochs for the same contract
    assert cid1.contract_key == cid2.contract_key
