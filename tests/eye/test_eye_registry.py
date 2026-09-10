"""Tests for Rule Provenance Registry and SemVer Rule Definitions."""

import pytest
from src.eye.registry import RuleRegistry, RuleDefinition, RuleStatus, ProvenanceType, EyeRegistryError


def test_rule_definition_validation():
    # Valid ACTIVE rule definition
    rule = RuleDefinition(
        rule_id="BOS_CLOSE_BREAK_V1",
        rule_version="1.0.0",
        event_type="BOS_BULLISH",
        event_family="STRUCTURE",
        status=RuleStatus.ACTIVE,
        provenance=ProvenanceType.EXISTING_CITADEL_RULE,
        source_file="src/structure/structure_engine_v2.py",
        source_symbol="StructureEngineV2.analyze",
        source_commit="8632791",
        effective_parameters={"swing_window": 2, "break_type": "CLOSE"},
    )
    assert rule.rule_key == "BOS_CLOSE_BREAK_V1:1.0.0"

    # Invalid SemVer rejected
    with pytest.raises(EyeRegistryError, match="Invalid SemVer"):
        RuleDefinition(
            rule_id="BOS_CLOSE_BREAK_V1",
            rule_version="v1.0",  # Invalid SemVer!
            event_type="BOS_BULLISH",
            event_family="STRUCTURE",
            status=RuleStatus.ACTIVE,
            provenance=ProvenanceType.EXISTING_CITADEL_RULE,
            source_file="src/structure/structure_engine_v2.py",
            source_symbol="StructureEngineV2.analyze",
            source_commit="8632791",
        )

    # ACTIVE rule MUST carry source provenance
    with pytest.raises(EyeRegistryError, match="ACTIVE rule requires complete source provenance"):
        RuleDefinition(
            rule_id="BOS_CLOSE_BREAK_V1",
            rule_version="1.0.0",
            event_type="BOS_BULLISH",
            event_family="STRUCTURE",
            status=RuleStatus.ACTIVE,
            provenance=ProvenanceType.EXISTING_CITADEL_RULE,
            source_file="",  # Missing source file!
            source_symbol="StructureEngineV2.analyze",
            source_commit="8632791",
        )


def test_rule_registry_storage():
    registry = RuleRegistry()
    rule = RuleDefinition(
        rule_id="BOS_CLOSE_BREAK_V1",
        rule_version="1.0.0",
        event_type="BOS_BULLISH",
        event_family="STRUCTURE",
        status=RuleStatus.ACTIVE,
        provenance=ProvenanceType.EXISTING_CITADEL_RULE,
        source_file="src/structure/structure_engine_v2.py",
        source_symbol="StructureEngineV2.analyze",
        source_commit="8632791",
        effective_parameters={"swing_window": 2},
    )
    registry.register(rule)
    assert registry.get("BOS_CLOSE_BREAK_V1", "1.0.0") == rule

    # Duplicate registration rejected
    with pytest.raises(EyeRegistryError, match="Duplicate rule registration"):
        registry.register(rule)
