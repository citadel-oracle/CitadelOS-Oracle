"""E3-D Candidate Density & Backpressure Test Suite."""

import pytest
from src.eye.contracts import EventFamily, EventType
from src.eye.composer.contracts import SetupDefinition, PatternStep
from src.eye.composer.state import PartialMatchTracker


def test_max_active_matches_enforced():
    sd = SetupDefinition(
        setup_id="LIMITED_SETUP_V1", setup_version="1.0.0", setup_family="LIQUIDITY_SWEEP_RECLAIM",
        name="Limited Setup", status="RESEARCH", provenance="TEST",
        max_active_matches=2,
        steps=(PatternStep(step_id="S1", accepted_families=(EventFamily.LIQUIDITY,), accepted_types=(EventType.LIQUIDITY_POOL_HIGH,)),),
    )

    tracker = PartialMatchTracker(sd)
    assert len(tracker.active_matches) == 0

    # Add 2 matches
    tracker.active_matches["PM1"] = None
    tracker.active_matches["PM2"] = None

    # Adding 3rd match when limit is 2 should return False
    res = tracker.add_match(None)
    assert res is False
