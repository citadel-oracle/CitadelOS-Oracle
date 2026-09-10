"""E3-D Historical Family Counts Test Suite."""

import pytest
from src.eye.composer.setup_registry import get_e3_setup_definitions


def test_ten_setup_definitions_registered():
    defs = get_e3_setup_definitions()
    assert len(defs) == 10
    families = {d.setup_family for d in defs}
    assert len(families) == 10
    assert "LIQUIDITY_SWEEP_RECLAIM" in families
    assert "OPTION_PREMIUM_CONFIRMED_CONTINUATION" in families
