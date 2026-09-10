"""E4A Slow Chain Lane Adapter Tests."""

import pytest
from datetime import datetime, timezone
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.instrument_master import InstrumentMasterRegistry
from src.eye.option_evidence.chain_adapter import SlowChainLaneAdapter
from src.eye.contracts import PriceAtom


def test_slow_chain_lane_parsing():
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

    snapshot = {
        "sequence": 101,
        "data": {
            "oc": {
                "24500": {
                    "ce": {
                        "security_id": "43210",
                        "last_price": 150.25,
                        "top_bid_price": 150.00,
                        "top_ask_price": 150.50,
                        "top_bid_quantity": 500,
                        "top_ask_quantity": 400,
                        "open_interest": 120000,
                        "implied_volatility": 15.5,
                    }
                }
            }
        }
    }

    adapter = SlowChainLaneAdapter()
    obs_list = adapter.parse_chain_snapshot(snapshot, reg, now, now)
    assert len(obs_list) == 1
    obs = obs_list[0]
    assert obs.contract.security_id == "43210"
    assert obs.vendor_iv is not None
    assert obs.vendor_iv.value == 15.5
