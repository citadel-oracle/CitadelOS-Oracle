"""E4A-D Test for Metadata Fail-Closed Verification."""

import pytest
from datetime import datetime, timezone
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.contracts import PriceAtom


def test_metadata_missing_fails_closed():
    now = datetime(2026, 8, 6, 9, 15, tzinfo=timezone.utc)
    expiry = datetime(2026, 8, 13, 15, 30, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="LOT_SIZE_UNRESOLVED"):
        OptionContractIdentity.create(
            exchange="NSE", segment="NSE_FO", security_id="43210",
            underlying_security_id="13", underlying_symbol="NIFTY",
            underlying_instrument_key="NSE:NIFTY:UNDERLYING_INDEX",
            derivative_instrument_type="OPTIDX", option_type="CE",
            expiry_date=expiry.date(), expiry_timestamp=expiry,
            expiry_class="WEEKLY", strike=PriceAtom(ticks=2450000),
            tick_size=PriceAtom(ticks=5), lot_size=0, source="DHAN_INSTRUMENT_MASTER",
            effective_time=now,
        )
