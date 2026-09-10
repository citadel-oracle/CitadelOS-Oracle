"""E3-E Setup Revision & Identity Model Test Suite."""

import pytest
from src.eye.composer.contracts import SetupCandidateRecord, CandidateStatus, AuthorityType, ProbabilityStatus
from src.eye.composer.deduplication import generate_setup_key, generate_record_id


def test_two_identity_model_and_four_stage_lifecycle_chain():
    setup_id = "EYE_SETUP_LIQUIDITY_SWEEP_RECLAIM_V1"
    inst_key = "NSE:NIFTY:UNDERLYING_INDEX"
    direction = "BEARISH"
    atomic_keys = ("EVT_POOL_1", "EVT_SWEEP_1")

    # 1. Stable setup_key
    s_key = generate_setup_key(setup_id, inst_key, direction, atomic_keys)
    assert s_key.startswith(f"SETUP:{setup_id}:")

    # 2. Lifecycle Stage 1: PARTIAL (Rev 1)
    rec1_id = generate_record_id(s_key, 1, CandidateStatus.PARTIAL.value, ("REC_POOL_1",), None)
    c1 = SetupCandidateRecord(
        schema_version="1.0.0", setup_key=s_key, record_id=rec1_id, setup_revision=1,
        setup_id=setup_id, setup_version="1.0.0", setup_family="LIQUIDITY_SWEEP_RECLAIM",
        instrument=None, direction=None, status=CandidateStatus.PARTIAL, started_at=None,
        confirmed_at=None, invalidated_at=None, evaluation_as_of=None, atomic_event_keys=("EVT_POOL_1",),
        atomic_record_ids=("REC_POOL_1",), ordered_step_bindings=(), previous_record_id=None,
    )

    # 3. Lifecycle Stage 2: PENDING_CONFIRMATION (Rev 2)
    rec2_id = generate_record_id(s_key, 2, CandidateStatus.PENDING_CONFIRMATION.value, ("REC_POOL_1", "REC_SWEEP_1"), rec1_id)
    c2 = SetupCandidateRecord(
        schema_version="1.0.0", setup_key=s_key, record_id=rec2_id, setup_revision=2,
        setup_id=setup_id, setup_version="1.0.0", setup_family="LIQUIDITY_SWEEP_RECLAIM",
        instrument=None, direction=None, status=CandidateStatus.PENDING_CONFIRMATION, started_at=None,
        confirmed_at=None, invalidated_at=None, evaluation_as_of=None, atomic_event_keys=atomic_keys,
        atomic_record_ids=("REC_POOL_1", "REC_SWEEP_1"), ordered_step_bindings=(), previous_record_id=rec1_id,
    )

    # 4. Lifecycle Stage 3: CONFIRMED (Rev 3)
    rec3_id = generate_record_id(s_key, 3, CandidateStatus.CONFIRMED.value, ("REC_POOL_1", "REC_SWEEP_1"), rec2_id)
    c3 = SetupCandidateRecord(
        schema_version="1.0.0", setup_key=s_key, record_id=rec3_id, setup_revision=3,
        setup_id=setup_id, setup_version="1.0.0", setup_family="LIQUIDITY_SWEEP_RECLAIM",
        instrument=None, direction=None, status=CandidateStatus.CONFIRMED, started_at=None,
        confirmed_at=None, invalidated_at=None, evaluation_as_of=None, atomic_event_keys=atomic_keys,
        atomic_record_ids=("REC_POOL_1", "REC_SWEEP_1"), ordered_step_bindings=(), previous_record_id=rec2_id,
    )

    # 5. Lifecycle Stage 4: INVALIDATED (Rev 4)
    rec4_id = generate_record_id(s_key, 4, CandidateStatus.INVALIDATED.value, ("REC_POOL_1", "REC_SWEEP_1"), rec3_id)
    c4 = SetupCandidateRecord(
        schema_version="1.0.0", setup_key=s_key, record_id=rec4_id, setup_revision=4,
        setup_id=setup_id, setup_version="1.0.0", setup_family="LIQUIDITY_SWEEP_RECLAIM",
        instrument=None, direction=None, status=CandidateStatus.INVALIDATED, started_at=None,
        confirmed_at=None, invalidated_at=None, evaluation_as_of=None, atomic_event_keys=atomic_keys,
        atomic_record_ids=("REC_POOL_1", "REC_SWEEP_1"), ordered_step_bindings=(), previous_record_id=rec3_id,
    )

    # Verify invariants
    # Stable setup_key across all 4 stages
    assert c1.setup_key == c2.setup_key == c3.setup_key == c4.setup_key == s_key

    # 4 distinct record_ids
    record_ids = {c1.record_id, c2.record_id, c3.record_id, c4.record_id}
    assert len(record_ids) == 4

    # Revisions 1, 2, 3, 4
    assert [c1.setup_revision, c2.setup_revision, c3.setup_revision, c4.setup_revision] == [1, 2, 3, 4]

    # Correct previous_record_id chain
    assert c1.previous_record_id is None
    assert c2.previous_record_id == c1.record_id
    assert c3.previous_record_id == c2.record_id
    assert c4.previous_record_id == c3.record_id

    # Forbidden formula check: record_id MUST NOT equal hash(setup_key only)
    assert rec1_id != s_key
    assert rec1_id != f"REC:{s_key[:16]}"
