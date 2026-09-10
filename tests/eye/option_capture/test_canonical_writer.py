"""E4A-E Test for Canonical Writer."""

import pytest
from datetime import datetime, timezone
from src.eye.option_capture.canonical_writer import CanonicalWriter
from src.eye.option_capture.contracts import FieldRevisionRecord, FeedLane
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.contracts import OptionMarketObservation, QuoteState
from src.eye.option_evidence.sources import SourceProvenance, SourceType, DataClassification
from src.eye.contracts import PriceAtom


def test_canonical_writer_writes_jsonl(tmp_path):
    writer = CanonicalWriter(tmp_path)
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
        quote_state=QuoteState.TWO_SIDED_VALID, is_fresh=True
    )
    writer.write_observation(obs)

    rev = FieldRevisionRecord(
        contract_key=cid.contract_key, field_name="last_price", field_value=150.0,
        source_lane=FeedLane.FAST_LANE_WEBSOCKET, exchange_timestamp=now.isoformat(),
        received_at_utc=now.isoformat(), available_at_utc=now.isoformat(), revision_number=1
    )
    writer.write_field_revision(rev)

    assert writer.observation_count == 1
    assert writer.field_revision_count == 1
