"""Rule Provenance Registry and SemVer Rule Definitions for Eye Engine."""

from __future__ import annotations

from dataclasses import dataclass, fields, field
from enum import Enum
import re
from threading import RLock
from typing import Any, Dict, Mapping, Optional, Sequence

SEMVER_REGEX = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$")


class EyeRegistryError(ValueError):
    pass


class RuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESEARCH = "RESEARCH"
    UNRESOLVED = "UNRESOLVED"
    DEPRECATED = "DEPRECATED"


class ProvenanceType(str, Enum):
    EXISTING_CITADEL_RULE = "EXISTING_CITADEL_RULE"
    USER_RULE = "USER_RULE"
    EXTERNAL_REFERENCE_VARIANT = "EXTERNAL_REFERENCE_VARIANT"
    PROPOSED_RESEARCH_VARIANT = "PROPOSED_RESEARCH_VARIANT"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, kw_only=True, slots=True)
class RuleDefinition:
    rule_id: str
    rule_version: str
    event_type: str
    event_family: str
    status: RuleStatus
    provenance: ProvenanceType
    source_file: str = ""
    source_symbol: str = ""
    source_commit: str = ""
    effective_parameters: Mapping[str, Any] = field(default_factory=dict)
    timeframe_constraints: Sequence[str] = field(default_factory=tuple)
    description: str = ""

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise EyeRegistryError("rule_id is required")
        if not SEMVER_REGEX.match(self.rule_version):
            raise EyeRegistryError(f"Invalid SemVer rule_version: {self.rule_version}")

        # ACTIVE rules MUST carry source provenance
        if self.status == RuleStatus.ACTIVE:
            if not self.source_file.strip() or not self.source_symbol.strip() or not self.source_commit.strip():
                raise EyeRegistryError("ACTIVE rule requires complete source provenance (source_file, source_symbol, source_commit)")

    @property
    def rule_key(self) -> str:
        return f"{self.rule_id}:{self.rule_version}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "rule_key": self.rule_key,
            "event_type": self.event_type,
            "event_family": self.event_family,
            "status": self.status.value,
            "provenance": self.provenance.value,
            "source_file": self.source_file,
            "source_symbol": self.source_symbol,
            "source_commit": self.source_commit,
            "effective_parameters": dict(self.effective_parameters),
            "timeframe_constraints": list(self.timeframe_constraints),
            "description": self.description,
        }


class RuleRegistry:
    def __init__(self) -> None:
        self._rules: Dict[str, RuleDefinition] = {}
        self._lock = RLock()
        self._register_default_native_rules()

    def _register_default_native_rules(self) -> None:
        defaults = [
            RuleDefinition(
                rule_id="STRUCTURE_V2_BOS_CLOSE_V1",
                rule_version="1.0.0",
                event_type="BOS_BULLISH",
                event_family="STRUCTURE",
                status=RuleStatus.ACTIVE,
                provenance=ProvenanceType.EXISTING_CITADEL_RULE,
                source_file="src/structure/structure_engine_v2.py",
                source_symbol="StructureEngineV2.analyze",
                source_commit="8632791",
                effective_parameters={"swing_window": 2, "break_type": "CLOSE"},
                description="StructureEngineV2 2-bar swing close break BOS",
            ),
            RuleDefinition(
                rule_id="BIGBELUGA_OB_CLOSE_MITIGATION_V1",
                rule_version="1.0.0",
                event_type="ORDER_BLOCK_BULLISH",
                event_family="ZONE",
                status=RuleStatus.ACTIVE,
                provenance=ProvenanceType.EXISTING_CITADEL_RULE,
                source_file="src/vob/bigbeluga_engine.py",
                source_symbol="BigBelugaVOBEngine.analyze",
                source_commit="8632791",
                effective_parameters={"mslen": 5},
                description="BigBelugaVOBEngine Order Block close mitigation",
            ),
            RuleDefinition(
                rule_id="FVG_NATIVE_THREE_BAR_V1",
                rule_version="1.0.0",
                event_type="FVG_BULLISH",
                event_family="IMBALANCE",
                status=RuleStatus.ACTIVE,
                provenance=ProvenanceType.EXISTING_CITADEL_RULE,
                source_file="src/fvg/fvg_engine.py",
                source_symbol="FVGEngine.analyze",
                source_commit="8632791",
                effective_parameters={"gap_min": 0.0},
                description="FVGEngine 3-bar Fair Value Gap imbalance",
            ),
            RuleDefinition(
                rule_id="LIQUIDITY_NATIVE_EQH_CLUSTER_V1",
                rule_version="1.0.0",
                event_type="LIQUIDITY_POOL_HIGH",
                event_family="LIQUIDITY",
                status=RuleStatus.ACTIVE,
                provenance=ProvenanceType.EXISTING_CITADEL_RULE,
                source_file="src/liquidity/liquidity_engine.py",
                source_symbol="LiquidityEngine.analyze",
                source_commit="8632791",
                effective_parameters={"tolerance": 0.0005},
                description="LiquidityEngine equal highs cluster pool",
            ),
            RuleDefinition(
                rule_id="ORACLE_DEV_PRICE_ACTION_V1",
                rule_version="1.0.0",
                event_type="TREND_BULLISH",
                event_family="REGIME",
                status=RuleStatus.ACTIVE,
                provenance=ProvenanceType.EXISTING_CITADEL_RULE,
                source_file="src/oracle_development/price_action_analyzer.py",
                source_symbol="OracleDevPriceActionAnalyzer.analyze",
                source_commit="8632791",
                effective_parameters={"modules_count": 15},
                description="OracleDevPriceActionAnalyzer multi-module price action state",
            ),
        ]
        for r in defaults:
            self._rules[r.rule_key] = r

    def register(self, rule: RuleDefinition) -> None:
        with self._lock:
            if rule.rule_key in self._rules:
                raise EyeRegistryError(f"Duplicate rule registration for {rule.rule_key}")
            self._rules[rule.rule_key] = rule

    def get(self, rule_id: str, rule_version: str) -> Optional[RuleDefinition]:
        rule_key = f"{rule_id}:{rule_version}"
        with self._lock:
            return self._rules.get(rule_key)

    def list_all(self) -> Sequence[RuleDefinition]:
        with self._lock:
            return list(self._rules.values())
