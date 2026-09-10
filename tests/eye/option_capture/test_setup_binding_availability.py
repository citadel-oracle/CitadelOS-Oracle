"""E4A-E Test for Offline Setup Binding Availability."""

from datetime import datetime, timezone
import pytest
from src.eye.option_evidence.replay import OptionEvidenceReplayEngine
from src.eye.composer.contracts import SetupCandidateRecord, CandidateStatus, AuthorityType, ProbabilityStatus
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.contracts import OptionMarketObservation, QuoteState
from src.eye.option_evidence.sources import SourceProvenance, SourceType, DataClassification
from src.eye.contracts import PriceAtom, InstrumentIdentity, EventDirection


def test_setup_binding_no_future_data():
    now = datetime(2026, 8, 7, 9, 15, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")

    cand = SetupCandidateRecord(
        schema_version="1.0.0",
        setup_key="SETUP:TEST:1",
        record_id="REC:TEST:1",
        setup_revision=1,
        setup_id="EYE_SETUP_DISPLACEMENT_FVG_RETEST_V1",
        setup_version="1.0.0",
        setup_family="DISPLACEMENT_FVG_RETEST",
        instrument=inst,
        direction=EventDirection.BEARISH,
        status=CandidateStatus.CONFIRMED,
        started_at=now,
        confirmed_at=now,
        invalidated_at=None,
        evaluation_as_of=now,
        atomic_event_keys=("EV1",),
        atomic_record_ids=("REC1",),
        ordered_step_bindings=(),
        authority=AuthorityType.OBSERVATION_ONLY,
        probability_status=ProbabilityStatus.NOT_ESTABLISHED,
    )

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

    engine = OptionEvidenceReplayEngine()
    records = engine.process_setup_and_evidence(cand, [obs], [(now, 24500.0)])
    assert len(records) == 1
    assert records[0].evidence_link.link_status == "BOUND"
