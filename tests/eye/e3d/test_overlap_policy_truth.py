"""E3-D Overlap Policy Truth Test Suite."""

import pytest
from src.eye.composer.contracts import SetupCandidateRecord, OverlapPolicy, CandidateStatus, AuthorityType, ProbabilityStatus
from src.eye.composer.deduplication import filter_overlapping_candidates


def test_suppress_identical_filters_duplicate_setup_keys():
    c1 = SetupCandidateRecord(
        schema_version="1.0.0", setup_key="SETUP:KEY_1", record_id="REC1",
        setup_revision=1, setup_id="S1", setup_version="1.0.0", setup_family="FAMILY1",
        instrument=None, direction=None, status=CandidateStatus.CONFIRMED,
        started_at=None, confirmed_at=None, invalidated_at=None, evaluation_as_of=None,
        atomic_event_keys=("E1",), atomic_record_ids=("R1",), ordered_step_bindings=(),
        primary_level=None, setup_definition_fingerprint="FP1", authority=AuthorityType.OBSERVATION_ONLY,
        probability_status=ProbabilityStatus.NOT_ESTABLISHED,
    )
    c2 = SetupCandidateRecord(
        schema_version="1.0.0", setup_key="SETUP:KEY_1", record_id="REC2",
        setup_revision=1, setup_id="S1", setup_version="1.0.0", setup_family="FAMILY1",
        instrument=None, direction=None, status=CandidateStatus.CONFIRMED,
        started_at=None, confirmed_at=None, invalidated_at=None, evaluation_as_of=None,
        atomic_event_keys=("E1",), atomic_record_ids=("R1",), ordered_step_bindings=(),
        primary_level=None, setup_definition_fingerprint="FP1", authority=AuthorityType.OBSERVATION_ONLY,
        probability_status=ProbabilityStatus.NOT_ESTABLISHED,
    )

    filtered = filter_overlapping_candidates([c1, c2], OverlapPolicy.SUPPRESS_IDENTICAL)
    assert len(filtered) == 1
    assert filtered[0].record_id == "REC1"
