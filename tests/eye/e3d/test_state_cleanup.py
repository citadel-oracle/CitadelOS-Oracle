"""E3-D / E3-E State Cleanup & Memory Bounds Test Suite."""

import pytest
from src.eye.composer.setup_registry import get_e3_setup_definitions
from src.eye.composer.state import PartialMatchTracker


def test_partial_match_tracker_active_matches_are_bounded():
    sd = get_e3_setup_definitions()[0]
    tracker = PartialMatchTracker(sd)
    assert tracker.definition.max_active_matches == 50
    assert len(tracker.active_matches) == 0
