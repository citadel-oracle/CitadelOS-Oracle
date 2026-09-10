"""E3-E Historical Eligible Families Test Suite."""

import pytest
from src.eye.composer.setup_registry import get_e3_setup_definitions


def test_historically_supported_families_have_two_or_more_mandatory_steps():
    defs = get_e3_setup_definitions()
    eligible = [d for d in defs if d.status == "HISTORICALLY_SUPPORTED_RESEARCH"]
    assert len(eligible) == 4
    eligible_ids = {d.setup_id for d in eligible}
    assert "EYE_SETUP_LIQUIDITY_SWEEP_RECLAIM_V1" in eligible_ids
    assert "EYE_SETUP_DISPLACEMENT_FVG_RETEST_V1" in eligible_ids
    assert "EYE_SETUP_BREAKAWAY_FVG_CONTINUATION_V1" in eligible_ids
    assert "EYE_SETUP_ZONE_FVG_CONFLUENCE_V1" in eligible_ids
    for d in eligible:
        assert len([s for s in d.steps if not s.optional_step]) >= 2
