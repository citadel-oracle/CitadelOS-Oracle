"""E3 Safety & Authority Lock Test Suite."""

import pytest
from src.eye.composer.contracts import SetupCandidateRecord, CandidateStatus
from src.eye.contracts import AuthorityType, ProbabilityStatus, InstrumentIdentity
from datetime import datetime, timezone


def test_safety_locks_no_trade_or_probability_fields():
    now = datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc)
    inst = InstrumentIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE", instrument_type="UNDERLYING_INDEX", underlying="NIFTY", source="DHAN", market="NSE")

    cand = SetupCandidateRecord(
        schema_version="1.0.0", setup_key="SETUP:TEST", record_id="REC:1",
        setup_revision=1, setup_id="TEST_SETUP", setup_version="1.0.0",
        setup_family="LIQUIDITY_SWEEP_RECLAIM", instrument=inst, direction=1,
        status=CandidateStatus.CONFIRMED, started_at=now, confirmed_at=now,
        invalidated_at=None, evaluation_as_of=now, atomic_event_keys=("E1", "E2"),
        atomic_record_ids=("R1", "R2"), ordered_step_bindings=(),
    )

    # Invariants
    assert cand.authority == AuthorityType.OBSERVATION_ONLY
    assert cand.probability_status == ProbabilityStatus.NOT_ESTABLISHED
    assert not hasattr(cand, "entry_price")
    assert not hasattr(cand, "stop_loss")
    assert not hasattr(cand, "target")
    assert not hasattr(cand, "option_strike")
    assert not hasattr(cand, "option_type")
