"""E3-D Registry Status Truth Test Suite."""

import pytest
from src.eye.composer.setup_registry import get_e3_setup_definitions


def test_unresolved_setup_definitions_do_not_emit_candidates():
    defs = get_e3_setup_definitions()
    unresolved = [d for d in defs if d.status == "UNRESOLVED"]
    assert len(unresolved) == 2
    for u in unresolved:
        assert len(u.steps) == 0
