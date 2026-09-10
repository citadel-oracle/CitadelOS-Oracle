"""E4A Quote Synchronization & Bitemporal Alignment Tests."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.exact_history_adapter import ExactHistoryAdapter
from src.eye.option_evidence.synchronization import synchronize_option_and_underlying
from src.eye.contracts import PriceAtom


def test_quote_synchronization_and_watermark_compliance():
    t0 = datetime(2026, 8, 6, 9, 15, tzinfo=timezone.utc)
    expiry = datetime(2026, 8, 13, 15, 30, tzinfo=timezone.utc)

    cid = OptionContractIdentity.create(
        exchange="NSE", segment="NSE_FO", security_id="43210",
        underlying_security_id="13", underlying_symbol="NIFTY",
        underlying_instrument_key="NSE:NIFTY:UNDERLYING_INDEX",
        derivative_instrument_type="OPTIDX", option_type="CE",
        expiry_date=expiry.date(), expiry_timestamp=expiry,
        expiry_class="WEEKLY", strike=PriceAtom(ticks=2450000),
        tick_size=PriceAtom(ticks=5), lot_size=25, source="DHAN_INSTRUMENT_MASTER",
        effective_time=t0,
    )

    adapter = ExactHistoryAdapter()
    obs = adapter.parse_historical_candle(cid, t0, 150.0, 152.0, 149.0, 150.5)

    u_ticks = [
        (t0, 24500.0),
        (t0 + timedelta(seconds=10), 24510.0),
    ]

    # Watermark at t0
    pair = synchronize_option_and_underlying(obs, u_ticks, t0)
    assert pair is not None
    assert pair.underlying_price == 24500.0
    assert pair.is_watermark_compliant is True

    # Watermark before t0 -> rejected
    pair_early = synchronize_option_and_underlying(obs, u_ticks, t0 - timedelta(seconds=1))
    assert pair_early is None
