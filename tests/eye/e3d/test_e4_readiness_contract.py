"""E3-D Phase E4 Readiness Contract Test Suite."""

import pytest
from src.eye.composer.contracts import SetupCandidateRecord, CandidateStatus, AuthorityType, ProbabilityStatus


def test_setup_candidate_has_mandatory_e4_contract_fields():
    c = SetupCandidateRecord(
        schema_version="1.0.0", setup_key="SETUP:TEST:123", record_id="REC123",
        setup_revision=1, setup_id="EYE_SETUP_LIQUIDITY_SWEEP_RECLAIM_V1", setup_version="1.0.0",
        setup_family="LIQUIDITY_SWEEP_RECLAIM", instrument=None, direction=None,
        status=CandidateStatus.CONFIRMED, started_at=None, confirmed_at=None,
        invalidated_at=None, evaluation_as_of=None, atomic_event_keys=("E1",),
        atomic_record_ids=("R1",), ordered_step_bindings=(), primary_level=None,
        setup_definition_fingerprint="FP123", authority=AuthorityType.OBSERVATION_ONLY,
        probability_status=ProbabilityStatus.NOT_ESTABLISHED,
    )

    assert c.authority == AuthorityType.OBSERVATION_ONLY
    assert c.probability_status == ProbabilityStatus.NOT_ESTABLISHED
    assert c.schema_version == "1.0.0"
