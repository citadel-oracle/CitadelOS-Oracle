"""E4A No-Look-Ahead Enforcement Tests."""

import pytest
from datetime import datetime, timezone, timedelta
from src.eye.contracts import InstrumentIdentity, PriceAtom
from src.eye.composer.contracts import SetupCandidateRecord, CandidateStatus, AuthorityType, ProbabilityStatus
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.exact_history_adapter import ExactHistoryAdapter
from src.eye.option_evidence.replay import OptionEvidenceReplayEngine


def test_no_lookahead_rejects_future_observations():
    t0 = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    t_future = t0 + timedelta(minutes=5)
    expiry = datetime(2026, 8, 13, 15, 30, tzinfo=timezone.utc)

    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")

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
    # Observation occurring in the future relative to setup watermark t0
    obs_future = adapter.parse_historical_candle(cid, t_future, 150.0, 152.0, 149.0, 150.5)

    cand = SetupCandidateRecord(
        schema_version="1.0.0", setup_key="SETUP:LIQUIDITY:NIFTY", record_id="REC1",
        setup_revision=1, setup_id="S1", setup_version="1.0.0",
        setup_family="LIQUIDITY_SWEEP_RECLAIM", instrument=inst, direction=None,
        status=CandidateStatus.CONFIRMED, started_at=t0, confirmed_at=t0,
        invalidated_at=None, evaluation_as_of=t0, atomic_event_keys=("E1", "E2"),
        atomic_record_ids=("R1", "R2"), ordered_step_bindings=(),
        primary_level=PriceAtom(ticks=2450000), setup_definition_fingerprint="FP1",
        authority=AuthorityType.OBSERVATION_ONLY, probability_status=ProbabilityStatus.NOT_ESTABLISHED,
    )

    replay = OptionEvidenceReplayEngine()
    recs = replay.process_setup_and_evidence(cand, [obs_future], [(t0, 24500.0)])

    # Future observation MUST be rejected under No-Look-Ahead rules!
    assert len(recs) == 0
