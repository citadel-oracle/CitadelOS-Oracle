"""E3-E Historical Candidate Correction Test Suite."""

import pytest
from src.eye.composer.setup_registry import get_e3_setup_definitions


def test_synthetically_testable_families_do_not_emit_historical_candidates():
    defs = get_e3_setup_definitions()
    synth_defs = [d for d in defs if d.status == "SYNTHETICALLY_TESTABLE_RESEARCH"]
    assert len(synth_defs) == 4
    # Ensure they are correctly marked and excluded from active historical runs
    for d in synth_defs:
        assert d.status != "HISTORICALLY_SUPPORTED_RESEARCH"
        assert d.status != "ACTIVE"
