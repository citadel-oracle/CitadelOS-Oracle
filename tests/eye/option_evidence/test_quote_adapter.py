"""E4A Fast Quote Lane Adapter Tests."""

import pytest
from datetime import datetime, timezone
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.instrument_master import InstrumentMasterRegistry
from src.eye.option_evidence.quote_adapter import FastQuoteLaneAdapter
from src.eye.contracts import PriceAtom


def test_fast_quote_lane_parsing():
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

    raw_q = {
        "security_id": "43210",
        "last_price": 150.30,
        "best_bid": 150.10,
        "best_ask": 150.40,
        "bid_quantity": 250,
        "ask_quantity": 300,
        "volume": 4500,
    }

    adapter = FastQuoteLaneAdapter()
    obs = adapter.parse_market_quote(raw_q, reg, now, now)
    assert obs is not None
    assert obs.contract.security_id == "43210"
    assert obs.best_bid.ticks == 15010
    assert obs.best_ask.ticks == 15040
