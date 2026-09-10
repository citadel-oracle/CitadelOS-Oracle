"""E3-E Phase E4 Eligibility Test Suite."""

import pytest
from src.eye.composer.setup_registry import get_e3_setup_definitions


def test_only_historically_supported_research_and_active_families_are_e4_eligible():
    defs = get_e3_setup_definitions()
    eligible = [d for d in defs if d.status in ("HISTORICALLY_SUPPORTED_RESEARCH", "ACTIVE")]
    assert len(eligible) == 4

    unresolved = [d for d in defs if d.status == "UNRESOLVED"]
    assert len(unresolved) == 2

    # Option families MUST be UNRESOLVED and excluded from E4 eligibility
    for u in unresolved:
        assert "OPTION" in u.setup_family
        assert u not in eligible
