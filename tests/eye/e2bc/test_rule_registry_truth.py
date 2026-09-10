"""Phase P — Rule Registry Truth Test Suite."""

import pytest
from src.eye.registry import RuleStatus, ProvenanceType
from src.eye.detectors.rule_variants import get_e2b_rule_variants


def test_rule_registry_truth_research_status():
    rules = get_e2b_rule_variants()
    assert len(rules) == 5
    for r in rules:
        assert r.status == RuleStatus.RESEARCH
        assert r.provenance == ProvenanceType.PROPOSED_RESEARCH_VARIANT
