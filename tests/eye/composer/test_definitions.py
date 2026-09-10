"""E3 Setup Definitions & Registry Test Suite."""

import pytest
from src.eye.composer.setup_registry import get_e3_setup_definitions, get_setup_definition_by_id


def test_setup_registry_count_and_statuses():
    defs = get_e3_setup_definitions()
    assert len(defs) == 10

    # Families 1-8 MUST be RESEARCH (HISTORICALLY_SUPPORTED_RESEARCH or SYNTHETICALLY_TESTABLE_RESEARCH)
    for d in defs[:8]:
        assert "RESEARCH" in d.status

    # Families 9-10 MUST be UNRESOLVED (Option evidence reserved for E4)
    assert defs[8].status == "UNRESOLVED"
    assert defs[9].status == "UNRESOLVED"
