"""Deterministic, advisory-only Oracle Opportunity Gate V1."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class InstrumentType(str, Enum):
    OPTION = "OPTION"
    EQUITY = "EQUITY"


class Direction(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    UNAVAILABLE = "UNAVAILABLE"


class Freshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class VolatilityState(str, Enum):
    SUPPORTIVE = "SUPPORTIVE"
    NEUTRAL = "NEUTRAL"
    ADVERSE = "ADVERSE"
    UNAVAILABLE = "UNAVAILABLE"


class LiquidityState(str, Enum):
    ACCEPTABLE = "ACCEPTABLE"
    POOR = "POOR"
    UNAVAILABLE = "UNAVAILABLE"


class RiskEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    BLOCKED = "BLOCKED"
    UNAVAILABLE = "UNAVAILABLE"


class GateDecision(str, Enum):
    CALL = "CALL"
    PUT = "PUT"
    EQUITY = "EQUITY"
    NO_TRADE = "NO_TRADE"


class DecisionLane(str, Enum):
    ORACLE_DISCOVERY = "ORACLE_DISCOVERY"
    STRATEGY_TRIGGERED = "STRATEGY_TRIGGERED"


class TriggerSource(str, Enum):
    VOB_BREAKOUT = "VOB_BREAKOUT"
    VOB_RETEST = "VOB_RETEST"
    PULLBACK = "PULLBACK"
    BREAKOUT = "BREAKOUT"


class EntryState(str, Enum):
    READY = "READY"
    WAIT_FOR_RETEST = "WAIT_FOR_RETEST"
    OVEREXTENDED = "OVEREXTENDED"
    REJECTED = "REJECTED"
    NO_TRADE = "NO_TRADE"


class ConfidenceCategory(str, Enum):
    LOW_EVIDENCE = "LOW_EVIDENCE"
    MODERATE_EVIDENCE = "MODERATE_EVIDENCE"
    HIGH_EVIDENCE = "HIGH_EVIDENCE"


@dataclass(frozen=True)
class ScoringRule:
    component: str
    weight: int
    evidence_type: str


SCORING_MATRIX = (
    ScoringRule("market_regime", 15, "DIRECTIONAL"),
    ScoringRule("price_structure", 20, "DIRECTIONAL"),
    ScoringRule("vob_context", 20, "DIRECTIONAL"),
    ScoringRule("argus_metrics", 15, "DIRECTIONAL"),
    ScoringRule("ose_context", 15, "DIRECTIONAL"),
    ScoringRule("volatility", 10, "CONTEXT"),
    ScoringRule("liquidity_spread", 5, "CONTEXT"),
)
MIN_EVIDENCE_QUALITY = 70
MIN_INDEPENDENT_ALIGNMENT = 3


@dataclass(frozen=True)
class OpportunitySnapshot:
    symbol: str
    instrument_type: InstrumentType
    snapshot_timestamp: Optional[datetime]
    evaluation_timestamp: datetime
    freshness: Freshness
    market_regime: Direction
    price_structure: Direction
    vob_context: Direction
    argus_metrics: Direction
    ose_context: Direction
    volatility: VolatilityState
    liquidity_spread: LiquidityState
    risk_eligibility: RiskEligibility
    unavailable_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be reported")
        if not isinstance(self.instrument_type, InstrumentType):
            raise TypeError("instrument_type must be an InstrumentType")
        for field_name, expected_type in (
            ("freshness", Freshness),
            ("market_regime", Direction),
            ("price_structure", Direction),
            ("vob_context", Direction),
            ("argus_metrics", Direction),
            ("ose_context", Direction),
            ("volatility", VolatilityState),
            ("liquidity_spread", LiquidityState),
            ("risk_eligibility", RiskEligibility),
        ):
            if not isinstance(getattr(self, field_name), expected_type):
                raise TypeError(
                    f"{field_name} must be a {expected_type.__name__}"
                )
        OpportunitySnapshot._validate_timestamp(
            self.snapshot_timestamp,
            "snapshot_timestamp",
            optional=True,
        )
        OpportunitySnapshot._validate_timestamp(
            self.evaluation_timestamp,
            "evaluation_timestamp",
            optional=False,
        )
        if not isinstance(self.unavailable_reasons, tuple):
            raise TypeError("unavailable_reasons must be an immutable tuple")
        if any(
            not isinstance(reason, str) or not reason.strip()
            for reason in self.unavailable_reasons
        ):
            raise ValueError("unavailable reasons must be non-empty text")

    @staticmethod
    def _validate_timestamp(
        value: object,
        field_name: str,
        *,
        optional: bool,
    ) -> None:
        if value is None and optional:
            return
        if isinstance(value, bool) or not isinstance(value, datetime):
            raise TypeError(f"{field_name} must be a datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class ComponentScore:
    component: str
    observed: str
    weight: int
    awarded: int
    disposition: str


@dataclass(frozen=True)
class OpportunityGateResult:
    decision: GateDecision
    evidence_quality_score: int
    confidence_category: ConfidenceCategory
    component_scores: tuple[ComponentScore, ...]
    aligned_evidence: tuple[str, ...]
    conflicting_evidence: tuple[str, ...]
    rejection_reasons: tuple[str, ...]
    critical_missing_inputs: tuple[str, ...]
    unavailable_reasons: tuple[str, ...]
    decision_lane: DecisionLane = DecisionLane.ORACLE_DISCOVERY
    trigger_source: TriggerSource | None = None
    entry_state: EntryState = EntryState.NO_TRADE
    evidence_label: str = "EVIDENCE_QUALITY"
    neutral_evidence: tuple[str, ...] = ()
    hard_vetoes: tuple[str, ...] = ()
    probability: None = field(default=None, init=False)
    contract: None = field(default=None, init=False)
    entry: None = field(default=None, init=False)
    stop_loss: None = field(default=None, init=False)
    targets: None = field(default=None, init=False)
    quantity: None = field(default=None, init=False)
    execution_allowed: bool = field(default=False, init=False)


class OpportunityGate:
    """Evaluates one supplied snapshot without fetching or mutating state."""

    @staticmethod
    def evaluate(snapshot: OpportunitySnapshot) -> OpportunityGateResult:
        if not isinstance(snapshot, OpportunitySnapshot):
            raise TypeError("snapshot must be an OpportunitySnapshot")
        critical_missing = OpportunityGate._critical_missing(snapshot)
        bullish_weight, bearish_weight = OpportunityGate._direction_weights(
            snapshot
        )
        has_conflict = bullish_weight > 0 and bearish_weight > 0
        candidate = OpportunityGate._candidate_direction(
            bullish_weight,
            bearish_weight,
            has_conflict,
        )
        component_scores = OpportunityGate._score_components(
            snapshot,
            candidate,
            has_conflict,
        )
        score = sum(component.awarded for component in component_scores)
        aligned = tuple(
            component.component
            for component in component_scores
            if component.disposition == "ALIGNED"
        )
        conflicting = tuple(
            component.component
            for component in component_scores
            if component.disposition == "CONFLICTING"
        )
        aligned_directional = sum(
            component.disposition == "ALIGNED"
            and component.component
            in {
                "market_regime",
                "price_structure",
                "vob_context",
                "argus_metrics",
                "ose_context",
            }
            for component in component_scores
        )
        rejection_reasons = OpportunityGate._rejection_reasons(
            snapshot=snapshot,
            critical_missing=critical_missing,
            has_conflict=has_conflict,
            candidate=candidate,
            aligned_directional=aligned_directional,
            score=score,
        )
        decision = OpportunityGate._decision(
            snapshot,
            candidate,
            rejection_reasons,
        )
        return OpportunityGateResult(
            decision=decision,
            evidence_quality_score=score,
            confidence_category=OpportunityGate._confidence(score),
            component_scores=component_scores,
            aligned_evidence=aligned,
            conflicting_evidence=conflicting,
            rejection_reasons=rejection_reasons,
            critical_missing_inputs=critical_missing,
            unavailable_reasons=tuple(
                sorted(set(snapshot.unavailable_reasons))
            ),
            neutral_evidence=(
                ("spot_volume", "spot_vwap")
                if snapshot.symbol == "NIFTY"
                else ()
            ),
        )

    @staticmethod
    def _direction_weights(
        snapshot: OpportunitySnapshot,
    ) -> tuple[int, int]:
        weights = {
            rule.component: rule.weight
            for rule in SCORING_MATRIX
            if rule.evidence_type == "DIRECTIONAL"
        }
        bullish = 0
        bearish = 0
        for component, weight in weights.items():
            observed = getattr(snapshot, component)
            if observed is Direction.BULLISH:
                bullish += weight
            elif observed is Direction.BEARISH:
                bearish += weight
        return bullish, bearish

    @staticmethod
    def _candidate_direction(
        bullish_weight: int,
        bearish_weight: int,
        has_conflict: bool,
    ) -> Optional[Direction]:
        if has_conflict or bullish_weight == bearish_weight:
            return None
        return (
            Direction.BULLISH
            if bullish_weight > bearish_weight
            else Direction.BEARISH
        )

    @staticmethod
    def _score_components(
        snapshot: OpportunitySnapshot,
        candidate: Optional[Direction],
        has_conflict: bool,
    ) -> tuple[ComponentScore, ...]:
        scores: list[ComponentScore] = []
        for rule in SCORING_MATRIX:
            observed = getattr(snapshot, rule.component)
            if rule.evidence_type == "DIRECTIONAL":
                awarded, disposition = OpportunityGate._directional_score(
                    observed,
                    candidate,
                    has_conflict,
                    rule.weight,
                )
            elif rule.component == "volatility":
                awarded, disposition = OpportunityGate._volatility_score(
                    observed,
                    rule.weight,
                )
            else:
                awarded, disposition = OpportunityGate._liquidity_score(
                    observed,
                    rule.weight,
                )
            scores.append(
                ComponentScore(
                    component=rule.component,
                    observed=observed.value,
                    weight=rule.weight,
                    awarded=awarded,
                    disposition=disposition,
                )
            )
        return tuple(scores)

    @staticmethod
    def _directional_score(
        observed: Direction,
        candidate: Optional[Direction],
        has_conflict: bool,
        weight: int,
    ) -> tuple[int, str]:
        if observed is Direction.UNAVAILABLE:
            return 0, "UNAVAILABLE"
        if observed is Direction.NEUTRAL:
            return 0, "NEUTRAL"
        if has_conflict:
            return 0, "CONFLICTING"
        if observed is candidate:
            return weight, "ALIGNED"
        return 0, "CONFLICTING"

    @staticmethod
    def _volatility_score(
        observed: VolatilityState,
        weight: int,
    ) -> tuple[int, str]:
        if observed is VolatilityState.SUPPORTIVE:
            return weight, "ALIGNED"
        if observed is VolatilityState.NEUTRAL:
            return weight // 2, "NEUTRAL"
        if observed is VolatilityState.ADVERSE:
            return 0, "CONFLICTING"
        return 0, "UNAVAILABLE"

    @staticmethod
    def _liquidity_score(
        observed: LiquidityState,
        weight: int,
    ) -> tuple[int, str]:
        if observed is LiquidityState.ACCEPTABLE:
            return weight, "ALIGNED"
        if observed is LiquidityState.POOR:
            return 0, "CONFLICTING"
        return 0, "UNAVAILABLE"

    @staticmethod
    def _critical_missing(
        snapshot: OpportunitySnapshot,
    ) -> tuple[str, ...]:
        missing: list[str] = []
        if snapshot.snapshot_timestamp is None:
            missing.append("snapshot_timestamp")
        if snapshot.freshness is Freshness.UNAVAILABLE:
            missing.append("freshness")
        for component in (
            "market_regime",
            "price_structure",
            "vob_context",
        ):
            if getattr(snapshot, component) is Direction.UNAVAILABLE:
                missing.append(component)
        if (
            snapshot.instrument_type is InstrumentType.OPTION
            and snapshot.ose_context is Direction.UNAVAILABLE
        ):
            missing.append("ose_context")
        if snapshot.liquidity_spread is LiquidityState.UNAVAILABLE:
            missing.append("liquidity_spread")
        if snapshot.risk_eligibility is RiskEligibility.UNAVAILABLE:
            missing.append("risk_eligibility")
        return tuple(missing)

    @staticmethod
    def _rejection_reasons(
        *,
        snapshot: OpportunitySnapshot,
        critical_missing: tuple[str, ...],
        has_conflict: bool,
        candidate: Optional[Direction],
        aligned_directional: int,
        score: int,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if critical_missing:
            reasons.append("CRITICAL_INPUTS_MISSING")
        if (
            snapshot.snapshot_timestamp is not None
            and snapshot.snapshot_timestamp > snapshot.evaluation_timestamp
        ):
            reasons.append("FUTURE_SNAPSHOT_TIMESTAMP")
        if snapshot.freshness is Freshness.STALE:
            reasons.append("STALE_SNAPSHOT")
        if snapshot.risk_eligibility is RiskEligibility.BLOCKED:
            reasons.append("RISK_NOT_ELIGIBLE")
        if snapshot.liquidity_spread is LiquidityState.POOR:
            reasons.append("LIQUIDITY_OR_SPREAD_INVALID")
        if has_conflict:
            reasons.append("DIRECTIONAL_CONFLICT")
        elif candidate is None:
            reasons.append("NO_DIRECTIONAL_EVIDENCE")
        if aligned_directional < MIN_INDEPENDENT_ALIGNMENT:
            reasons.append("INSUFFICIENT_INDEPENDENT_ALIGNMENT")
        if not OpportunityGate._score_is_sufficient(score):
            reasons.append("EVIDENCE_QUALITY_BELOW_THRESHOLD")
        if critical_missing:
            reasons.extend(
                f"UNAVAILABLE:{reason.strip()}"
                for reason in sorted(set(snapshot.unavailable_reasons))
            )
        return tuple(reasons)

    @staticmethod
    def _decision(
        snapshot: OpportunitySnapshot,
        candidate: Optional[Direction],
        rejection_reasons: tuple[str, ...],
    ) -> GateDecision:
        if rejection_reasons or candidate is None:
            return GateDecision.NO_TRADE
        if snapshot.instrument_type is InstrumentType.EQUITY:
            return GateDecision.EQUITY
        return (
            GateDecision.CALL
            if candidate is Direction.BULLISH
            else GateDecision.PUT
        )

    @staticmethod
    def _confidence(score: int) -> ConfidenceCategory:
        if score >= 70:
            return ConfidenceCategory.HIGH_EVIDENCE
        if score >= 40:
            return ConfidenceCategory.MODERATE_EVIDENCE
        return ConfidenceCategory.LOW_EVIDENCE

    @staticmethod
    def _score_is_sufficient(score: int) -> bool:
        if isinstance(score, bool) or not isinstance(score, int):
            raise TypeError("evidence score must be an integer")
        if not 0 <= score <= 100:
            raise ValueError("evidence score must be between 0 and 100")
        return score >= MIN_EVIDENCE_QUALITY
