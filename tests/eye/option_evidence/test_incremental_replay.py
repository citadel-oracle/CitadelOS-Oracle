"""E4A Incremental vs Full Replay Parity Tests."""

import pytest
from datetime import datetime, timezone
from src.eye.contracts import InstrumentIdentity, PriceAtom
from src.eye.composer.contracts import SetupCandidateRecord, CandidateStatus, AuthorityType, ProbabilityStatus
from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.option_evidence.exact_history_adapter import ExactHistoryAdapter
from src.eye.option_evidence.replay import OptionEvidenceReplayEngine


def test_incremental_replay_parity():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
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
        effective_time=now,
    )

    adapter = ExactHistoryAdapter()
    obs = adapter.parse_historical_candle(cid, now, 150.0, 152.0, 149.0, 150.5)

    cand = SetupCandidateRecord(
        schema_version="1.0.0", setup_key="SETUP:LIQUIDITY:NIFTY", record_id="REC1",
        setup_revision=1, setup_id="S1", setup_version="1.0.0",
        setup_family="LIQUIDITY_SWEEP_RECLAIM", instrument=inst, direction=None,
        status=CandidateStatus.CONFIRMED, started_at=now, confirmed_at=now,
        invalidated_at=None, evaluation_as_of=now, atomic_event_keys=("E1", "E2"),
        atomic_record_ids=("R1", "R2"), ordered_step_bindings=(),
        primary_level=PriceAtom(ticks=2450000), setup_definition_fingerprint="FP1",
        authority=AuthorityType.OBSERVATION_ONLY, probability_status=ProbabilityStatus.NOT_ESTABLISHED,
    )

    # Replay 1
    engine1 = OptionEvidenceReplayEngine()
    recs1 = engine1.process_setup_and_evidence(cand, [obs], [(now, 24500.0)])

    # Replay 2
    engine2 = OptionEvidenceReplayEngine()
    recs2 = engine2.process_setup_and_evidence(cand, [obs], [(now, 24500.0)])

    assert len(recs1) == len(recs2)
    assert recs1[0].evidence_id == recs2[0].evidence_id
