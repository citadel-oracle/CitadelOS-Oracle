"""E3-D Setup Definition Semantics Test Suite."""

import pytest
from src.eye.composer.contracts import SetupDefinition, PatternStep
from src.eye.contracts import EventFamily, EventType


def test_setup_definition_immutability_and_fingerprint():
    s1 = SetupDefinition(
        setup_id="TEST_SETUP_V1", setup_version="1.0.0", setup_family="LIQUIDITY_SWEEP_RECLAIM",
        name="Test Setup", status="RESEARCH", provenance="TEST",
        steps=(
            PatternStep(step_id="S1", accepted_families=(EventFamily.LIQUIDITY,), accepted_types=(EventType.LIQUIDITY_POOL_HIGH,)),
        ),
    )

    s2 = SetupDefinition(
        setup_id="TEST_SETUP_V1", setup_version="1.0.0", setup_family="LIQUIDITY_SWEEP_RECLAIM",
        name="Test Setup", status="RESEARCH", provenance="TEST",
        steps=(
            PatternStep(step_id="S1", accepted_families=(EventFamily.LIQUIDITY,), accepted_types=(EventType.LIQUIDITY_POOL_HIGH,)),
        ),
    )

    assert s1.fingerprint == s2.fingerprint
    assert len(s1.fingerprint) == 64
