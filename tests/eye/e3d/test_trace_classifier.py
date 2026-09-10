"""E3-D Trace Classifier Test Suite."""

import pytest
from src.eye.composer.contracts import SetupCandidateRecord, CandidateStatus


def test_candidate_status_enum_values():
    assert CandidateStatus.CONFIRMED.value == "CONFIRMED"
    assert CandidateStatus.EXPIRED.value == "EXPIRED"
    assert CandidateStatus.INVALIDATED.value == "INVALIDATED"
