"""E3-E Complete Trace Classifier Test Suite."""

import pytest
from src.eye.composer.contracts import CandidateStatus, PartialMatchStatus


def test_classifier_status_enums():
    assert CandidateStatus.CONFIRMED.value == "CONFIRMED"
    assert CandidateStatus.INVALIDATED.value == "INVALIDATED"
    assert PartialMatchStatus.CANCELLED.value == "CANCELLED"
    assert PartialMatchStatus.EXPIRED.value == "EXPIRED"
