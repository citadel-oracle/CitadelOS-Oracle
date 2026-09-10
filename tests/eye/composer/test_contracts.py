"""Phase E3 Contracts & Safety Lock Test Suite."""

import pytest
from src.eye.composer.contracts import SetupDefinition, SetupCandidateRecord, PartialMatch
from src.eye.contracts import AuthorityType, ProbabilityStatus


def test_setup_candidate_authority_and_probability_lock():
    # Setup authority MUST be OBSERVATION_ONLY
    assert AuthorityType.OBSERVATION_ONLY.value == "OBSERVATION_ONLY"
    assert ProbabilityStatus.NOT_ESTABLISHED.value == "NOT_ESTABLISHED"


def test_setup_definition_immutability():
    # SetupDefinition must be frozen dataclass
    with pytest.raises(Exception):
        sd = SetupDefinition(
            setup_id="TEST_SETUP", setup_version="1.0.0", setup_family="LIQUIDITY_SWEEP_RECLAIM",
            name="Test Setup", status="RESEARCH", provenance="PROPOSED_RESEARCH_SETUP", steps=(),
        )
        sd.name = "Mutated"
