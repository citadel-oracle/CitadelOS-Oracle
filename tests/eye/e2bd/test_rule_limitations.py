"""E2B-D Rule Limitations Audit Test Suite."""

import pytest
from src.eye.registry import RuleStatus
from src.eye.detectors.rule_variants import get_e2b_rule_variants


def test_rule_limitations_all_research_status():
    rules = get_e2b_rule_variants()
    assert len(rules) == 5
    for r in rules:
        assert r.status == RuleStatus.RESEARCH
