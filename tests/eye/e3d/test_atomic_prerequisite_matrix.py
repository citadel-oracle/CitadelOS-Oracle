"""E3-D Atomic Prerequisite Matrix Test Suite."""

import pytest
from src.eye.composer.setup_registry import get_e3_setup_definitions


def test_atomic_prerequisite_matrix_classifications():
    defs = get_e3_setup_definitions()
    by_family = {d.setup_family: d for d in defs}

    # Verify historically supported families
    assert by_family["LIQUIDITY_SWEEP_RECLAIM"].status == "HISTORICALLY_SUPPORTED_RESEARCH"
    assert by_family["DISPLACEMENT_FVG_RETEST"].status == "HISTORICALLY_SUPPORTED_RESEARCH"
    assert by_family["BREAKAWAY_FVG_CONTINUATION"].status == "HISTORICALLY_SUPPORTED_RESEARCH"
    assert by_family["ZONE_FVG_CONFLUENCE"].status == "HISTORICALLY_SUPPORTED_RESEARCH"

    # Verify synthetically testable families (lacking real E2B detectors)
    assert by_family["BREAKOUT_ACCEPTANCE_RETEST"].status == "SYNTHETICALLY_TESTABLE_RESEARCH"
    assert by_family["FAILED_BREAKOUT_REVERSAL"].status == "SYNTHETICALLY_TESTABLE_RESEARCH"
    assert by_family["TREND_PULLBACK"].status == "SYNTHETICALLY_TESTABLE_RESEARCH"
    assert by_family["COMPRESSION_DISPLACEMENT"].status == "SYNTHETICALLY_TESTABLE_RESEARCH"

    # Verify unresolved families
    assert by_family["OPTION_PREMIUM_CONFIRMED_CONTINUATION"].status == "UNRESOLVED"
    assert by_family["OPTION_PREMIUM_CONFIRMED_REVERSAL"].status == "UNRESOLVED"
