"""E4A-E Test for Synchronized Underlying & Option Observations."""

from datetime import datetime, timezone
import pytest
from src.eye.option_evidence.synchronization import synchronize_option_and_underlying
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.contracts import OptionMarketObservation, QuoteState
from src.eye.option_evidence.sources import SourceProvenance, SourceType, DataClassification
from src.eye.contracts import PriceAtom


def test_underlying_option_synchronization():
    now = datetime(2026, 8, 7, 9, 15, tzinfo=timezone.utc)
    cid = OptionContractIdentity.create(
        exchange="NSE", segment="NSE_FO", security_id="43210",
        underlying_security_id="13", underlying_symbol="NIFTY",
        underlying_instrument_key="NSE:NIFTY:UNDERLYING_INDEX",
        derivative_instrument_type="OPTIDX", option_type="CE",
        expiry_date=now.date(), expiry_timestamp=now,
        expiry_class="WEEKLY", strike=PriceAtom(ticks=2450000),
        tick_size=PriceAtom(ticks=5), lot_size=25, source="DHAN_INSTRUMENT_MASTER",
        effective_time=now,
    )
    prov = SourceProvenance(source_type=SourceType.DHAN_MARKET_QUOTE, data_classification=DataClassification.EXACT_OPTION_QUOTE)
    obs = OptionMarketObservation(
        observation_id="OBS:1", contract=cid, provenance=prov,
        observed_at=now, available_at=now, evaluation_as_of=now, received_at=now, parsed_at=now,
        last_price=PriceAtom(ticks=15000), quote_state=QuoteState.TWO_SIDED_VALID, is_fresh=True
    )

    underlying_ticks = [(now, 24500.0)]
    pair = synchronize_option_and_underlying(obs, underlying_ticks, watermark=now)

    assert pair is not None
    assert pair.underlying_price == 24500.0
    assert pair.is_watermark_compliant is True
