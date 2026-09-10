"""Strategy-triggered Oracle veto policy over one cached canonical snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any, Mapping, Sequence

from src.oracle.opportunity_gate import (
    ComponentScore,
    ConfidenceCategory,
    DecisionLane,
    Direction,
    EntryState,
    Freshness,
    GateDecision,
    LiquidityState,
    OpportunityGateResult,
    OpportunitySnapshot,
    RiskEligibility,
    TriggerSource,
)


@dataclass(frozen=True)
class StrategyTrigger:
    source: TriggerSource
    direction: GateDecision
    candle_timestamp: datetime
    acceptance_confirmed: bool = True
    current_entry: float | None = None
    maximum_entry: float | None = None
    identity: str = ""

    def __post_init__(self) -> None:
        if self.direction not in {GateDecision.CALL, GateDecision.PUT}:
            raise ValueError("strategy trigger direction must be CALL or PUT")
        if (
            not isinstance(self.candle_timestamp, datetime)
            or self.candle_timestamp.tzinfo is None
            or self.candle_timestamp.utcoffset() is None
        ):
            raise ValueError("strategy trigger timestamp must be timezone-aware")
        for value in (self.current_entry, self.maximum_entry):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value <= 0
            ):
                raise ValueError("entry values must be positive finite numbers")


class StrategyTriggeredPolicy:
    """Qualifies an existing strategy trigger without re-running its strategy."""

    _WEIGHTS = {
        "market_regime": 15,
        "price_structure": 20,
        "argus_metrics": 15,
        "ose_context": 15,
        "volatility": 10,
        "liquidity_spread": 5,
    }

    @classmethod
    def evaluate(
        cls,
        snapshot: Mapping[str, Any],
        gate_input: OpportunitySnapshot,
        trigger: StrategyTrigger,
    ) -> OpportunityGateResult:
        expected = (
            Direction.BULLISH
            if trigger.direction is GateDecision.CALL
            else Direction.BEARISH
        )
        rejection: list[str] = []
        critical: list[str] = []
        supports: list[str] = []
        neutral: list[str] = ["spot_volume", "spot_vwap"]
        conflicts: list[str] = []
        vetoes: list[str] = []

        boundary = cls._completed_boundary(snapshot)
        if trigger.candle_timestamp > gate_input.evaluation_timestamp:
            rejection.append("FUTURE_TRIGGER_TIMESTAMP")
        if trigger.source in {
            TriggerSource.VOB_BREAKOUT,
            TriggerSource.VOB_RETEST,
        } and trigger.candle_timestamp != boundary:
            rejection.append("TRIGGER_NOT_CURRENT_COMPLETED_5M")
        if gate_input.freshness is not Freshness.FRESH:
            critical.append("freshness")
            rejection.append("SNAPSHOT_NOT_FRESH")
        if gate_input.risk_eligibility is not RiskEligibility.ELIGIBLE:
            critical.append("risk_eligibility")
            rejection.append("PLANNER_RISK_PATH_UNAVAILABLE")

        structure = gate_input.price_structure
        if structure is expected:
            supports.append("price_structure")
        elif structure is Direction.NEUTRAL:
            neutral.append("price_structure")
        elif structure is Direction.UNAVAILABLE:
            critical.append("price_structure")
        else:
            vetoes.append("OPPOSITE_PRICE_STRUCTURE")

        regime = gate_input.market_regime
        if regime is expected:
            supports.append("market_regime")
        elif regime in {Direction.NEUTRAL, Direction.UNAVAILABLE}:
            neutral.append("market_regime")
        else:
            conflicts.append("market_regime")

        argus_disposition = cls._argus_disposition(snapshot, trigger.direction)
        cls._record_disposition(
            "argus_metrics",
            argus_disposition,
            supports,
            neutral,
            conflicts,
            vetoes,
        )
        ose_disposition = cls._ose_disposition(snapshot, trigger.direction)
        cls._record_disposition(
            "ose_context",
            ose_disposition,
            supports,
            neutral,
            conflicts,
            vetoes,
        )

        liquidity = cls._selected_liquidity(snapshot, trigger.direction)
        if liquidity is LiquidityState.ACCEPTABLE:
            supports.append("liquidity_spread")
        elif liquidity is LiquidityState.POOR:
            vetoes.append("SELECTED_OPTION_LIQUIDITY_INVALID")
        else:
            critical.append("liquidity_spread")
            rejection.append("SELECTED_OPTION_LIQUIDITY_UNAVAILABLE")

        if trigger.source is TriggerSource.VOB_BREAKOUT:
            if structure is Direction.NEUTRAL:
                rejection.append("BREAKOUT_STRUCTURE_UNCONFIRMED")
            elif structure is Direction.UNAVAILABLE:
                rejection.append("BREAKOUT_STRUCTURE_UNAVAILABLE")

        if vetoes:
            rejection.append("HARD_CONTRADICTION_VETO")
        independent = tuple(
            item for item in supports if item != "liquidity_spread"
        )
        if not independent:
            rejection.append("INDEPENDENT_DIRECTIONAL_SUPPORT_MISSING")

        entry_state = EntryState.READY
        if rejection or critical:
            entry_state = (
                EntryState.REJECTED
                if vetoes
                else EntryState.WAIT_FOR_RETEST
            )
        elif not trigger.acceptance_confirmed:
            entry_state = EntryState.WAIT_FOR_RETEST
            rejection.append("ENTRY_ACCEPTANCE_INCOMPLETE")
        elif (
            trigger.current_entry is not None
            and trigger.maximum_entry is not None
            and trigger.current_entry > trigger.maximum_entry
        ):
            entry_state = EntryState.OVEREXTENDED
            rejection.append("PLANNER_MAXIMUM_ENTRY_EXCEEDED")

        components, quality = cls._component_scores(
            gate_input=gate_input,
            expected=expected,
            argus_disposition=argus_disposition,
            ose_disposition=ose_disposition,
            liquidity=liquidity,
        )

        # Shadow Anti-Double-Counting Cluster Comparison (ZERO execution influence)
        try:
            from src.canonical_features.cluster_caps import ClusterCapEvaluator
            comp_dict = {c.component: float(c.awarded) for c in components}
            weights_dict = {c.component: float(c.weight) for c in components}
            cluster_eval = ClusterCapEvaluator()
            _shadow_result = cluster_eval.evaluate_shadow(comp_dict, weights_dict)
        except Exception:
            pass
        decision = (
            trigger.direction
            if entry_state is EntryState.READY
            else GateDecision.NO_TRADE
        )
        return OpportunityGateResult(
            decision=decision,
            evidence_quality_score=quality,
            confidence_category=cls._confidence(quality),
            component_scores=components,
            aligned_evidence=tuple(dict.fromkeys(supports)),
            conflicting_evidence=tuple(dict.fromkeys(conflicts)),
            rejection_reasons=tuple(dict.fromkeys(rejection)),
            critical_missing_inputs=tuple(sorted(set(critical))),
            unavailable_reasons=tuple(
                sorted(set(gate_input.unavailable_reasons))
            ),
            decision_lane=DecisionLane.STRATEGY_TRIGGERED,
            trigger_source=trigger.source,
            entry_state=entry_state,
            evidence_label="EVIDENCE_QUALITY",
            neutral_evidence=tuple(dict.fromkeys(neutral)),
            hard_vetoes=tuple(dict.fromkeys(vetoes)),
        )

    @classmethod
    def choose(
        cls,
        snapshot: Mapping[str, Any],
        gate_input: OpportunitySnapshot,
        triggers: Sequence[StrategyTrigger],
    ) -> OpportunityGateResult:
        evaluated = tuple(
            (trigger, cls.evaluate(snapshot, gate_input, trigger))
            for trigger in sorted(
                triggers,
                key=lambda value: (
                    value.candle_timestamp,
                    value.source.value,
                    value.direction.value,
                    value.identity,
                ),
                reverse=True,
            )
        )
        if not evaluated:
            raise ValueError("at least one strategy trigger is required")
        eligible = tuple(
            (trigger, result)
            for trigger, result in evaluated
            if result.entry_state
            in {EntryState.READY, EntryState.WAIT_FOR_RETEST, EntryState.OVEREXTENDED}
            and not result.hard_vetoes
        )
        if not eligible:
            return evaluated[0][1]
        best_score = max(
            result.evidence_quality_score for _, result in eligible
        )
        best = tuple(
            (trigger, result)
            for trigger, result in eligible
            if result.evidence_quality_score == best_score
        )
        decisions = {trigger.direction for trigger, _ in best}
        if len(best) > 1 and len(decisions) > 1:
            return OpportunityGateResult(
                decision=GateDecision.NO_TRADE,
                evidence_quality_score=best_score,
                confidence_category=cls._confidence(best_score),
                component_scores=(),
                aligned_evidence=(),
                conflicting_evidence=("COMPETING_CALL_PUT_CANDIDATES",),
                rejection_reasons=("COMPETING_CANDIDATES_UNRESOLVED",),
                critical_missing_inputs=(),
                unavailable_reasons=(),
                decision_lane=DecisionLane.STRATEGY_TRIGGERED,
                trigger_source=None,
                entry_state=EntryState.NO_TRADE,
                neutral_evidence=(),
                hard_vetoes=(),
            )
        return best[0][1]

    @staticmethod
    def _completed_boundary(snapshot: Mapping[str, Any]) -> datetime:
        boundary = snapshot.get("intelligence_boundary")
        if not isinstance(boundary, Mapping):
            raise ValueError("intelligence boundary is unavailable")
        if boundary.get("status") != "COHERENT" or boundary.get("timeframe") != "5m":
            raise ValueError("intelligence boundary is not coherent completed 5m")
        value = boundary.get("completed_boundary")
        if not isinstance(value, str):
            raise ValueError("completed 5m boundary is unavailable")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("completed 5m boundary must be timezone-aware")
        return parsed

    @staticmethod
    def _record_disposition(
        component: str,
        disposition: str,
        supports: list[str],
        neutral: list[str],
        conflicts: list[str],
        vetoes: list[str],
    ) -> None:
        if disposition in {"SUPPORT", "STRONG_SUPPORT", "MODERATE_SUPPORT"}:
            supports.append(component)
        elif disposition == "HARD_VETO":
            vetoes.append(f"OPPOSITE_{component.upper()}")
        elif disposition == "CONFLICT":
            conflicts.append(component)
        else:
            neutral.append(component)

    @staticmethod
    def _argus_disposition(
        snapshot: Mapping[str, Any], direction: GateDecision
    ) -> str:
        tactical = StrategyTriggeredPolicy._tactical(snapshot)
        decision = tactical.get("decision")
        pressure = tactical.get("pressure")
        persistence = tactical.get("persistence")
        if not all(
            isinstance(value, Mapping)
            for value in (decision, pressure, persistence)
        ):
            return "NEUTRAL"
        banner = str(
            decision.get("banner") or decision.get("raw_banner") or ""
        ).upper()
        pressure_direction = str(pressure.get("direction") or "").upper()
        pressure_state = str(pressure.get("state") or "").upper()
        persistent_direction = str(
            persistence.get("direction") or ""
        ).upper()
        persistent = (
            persistence.get("status") == "AVAILABLE"
            and type(persistence.get("consecutive_confirmations")) is int
            and persistence.get("consecutive_confirmations", 0)
            >= persistence.get("required_count", 3)
        )
        if (
            banner in {"BALANCED", "NO CLEAN EDGE", "NO_CLEAN_EDGE"}
            or pressure_direction == "BALANCED"
            or pressure_state == "NO_CLEAN_EDGE"
        ):
            return "NEUTRAL"
        expected = "CALL" if direction is GateDecision.CALL else "PUT"
        if (
            expected in banner
            and pressure_direction == expected
            and persistent_direction == expected
            and persistent
        ):
            return "SUPPORT"
        opposite = "PUT" if expected == "CALL" else "CALL"
        if (
            opposite in banner
            and pressure_direction == opposite
            and persistent_direction == opposite
            and persistent
        ):
            return "HARD_VETO"
        return "NEUTRAL"

    @staticmethod
    def _ose_disposition(
        snapshot: Mapping[str, Any], direction: GateDecision
    ) -> str:
        execution = StrategyTriggeredPolicy._execution(snapshot)
        ose = execution.get("options_structure")
        duel = ose.get("duel") if isinstance(ose, Mapping) else None
        state = str(duel.get("state") if isinstance(duel, Mapping) else "").upper()
        expected = "CALL" if direction is GateDecision.CALL else "PUT"
        opposite = "PUT" if expected == "CALL" else "CALL"
        if state == f"CLEAR {expected} ADVANTAGE":
            return "STRONG_SUPPORT"
        if state == f"MODERATE {expected} ADVANTAGE":
            return "MODERATE_SUPPORT"
        if state == f"CLEAR {opposite} ADVANTAGE":
            return "HARD_VETO"
        if state == f"MODERATE {opposite} ADVANTAGE":
            return "CONFLICT"
        return "NEUTRAL"

    @staticmethod
    def _selected_liquidity(
        snapshot: Mapping[str, Any], direction: GateDecision
    ) -> LiquidityState:
        tactical = StrategyTriggeredPolicy._tactical(snapshot)
        decision = tactical.get("decision")
        ranks = (
            decision.get("all_candidate_ranks")
            if isinstance(decision, Mapping)
            else None
        )
        if not isinstance(ranks, list):
            return LiquidityState.UNAVAILABLE
        side = "CE" if direction is GateDecision.CALL else "PE"
        for row in ranks:
            if not isinstance(row, Mapping) or row.get("side") != side:
                continue
            for field in ("spread_abs", "spread_pct"):
                value = row.get(field)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    or value < 0
                ):
                    return LiquidityState.UNAVAILABLE
            if row.get("status") == "CANDIDATE" and row.get("rejection_reason") is None:
                return LiquidityState.ACCEPTABLE
            rejection = str(row.get("rejection_reason") or "")
            if "SPREAD" in rejection or "LIQUIDITY" in rejection:
                return LiquidityState.POOR
        return LiquidityState.UNAVAILABLE

    @classmethod
    def _component_scores(
        cls,
        *,
        gate_input: OpportunitySnapshot,
        expected: Direction,
        argus_disposition: str,
        ose_disposition: str,
        liquidity: LiquidityState,
    ) -> tuple[tuple[ComponentScore, ...], int]:
        observations: list[tuple[str, str, str]] = []
        for component in ("market_regime", "price_structure"):
            value = getattr(gate_input, component)
            disposition = (
                "ALIGNED"
                if value is expected
                else "NEUTRAL"
                if value is Direction.NEUTRAL
                else "UNAVAILABLE"
                if value is Direction.UNAVAILABLE
                else "CONFLICTING"
            )
            observations.append((component, value.value, disposition))
        observations.extend(
            (
                (
                    "argus_metrics",
                    argus_disposition,
                    "ALIGNED"
                    if argus_disposition == "SUPPORT"
                    else "CONFLICTING"
                    if argus_disposition == "HARD_VETO"
                    else "NEUTRAL",
                ),
                (
                    "ose_context",
                    ose_disposition,
                    "ALIGNED"
                    if ose_disposition in {"STRONG_SUPPORT", "MODERATE_SUPPORT"}
                    else "CONFLICTING"
                    if ose_disposition in {"HARD_VETO", "CONFLICT"}
                    else "NEUTRAL",
                ),
                (
                    "volatility",
                    gate_input.volatility.value,
                    "ALIGNED"
                    if gate_input.volatility.value == "SUPPORTIVE"
                    else "NEUTRAL"
                    if gate_input.volatility.value == "NEUTRAL"
                    else "CONFLICTING"
                    if gate_input.volatility.value == "ADVERSE"
                    else "UNAVAILABLE",
                ),
                (
                    "liquidity_spread",
                    liquidity.value,
                    "ALIGNED"
                    if liquidity is LiquidityState.ACCEPTABLE
                    else "CONFLICTING"
                    if liquidity is LiquidityState.POOR
                    else "UNAVAILABLE",
                ),
                ("spot_volume", "NOT_APPLICABLE", "NOT_APPLICABLE"),
                ("spot_vwap", "NOT_APPLICABLE", "NOT_APPLICABLE"),
            )
        )
        denominator = sum(
            cls._WEIGHTS.get(component, 0)
            for component, _, disposition in observations
            if disposition not in {"UNAVAILABLE", "NOT_APPLICABLE"}
        )
        awarded_weight = sum(
            cls._WEIGHTS.get(component, 0)
            for component, _, disposition in observations
            if disposition == "ALIGNED"
        )
        quality = round(100 * awarded_weight / denominator) if denominator else 0
        scores = tuple(
            ComponentScore(
                component=component,
                observed=observed,
                weight=cls._WEIGHTS.get(component, 0),
                awarded=(
                    round(100 * cls._WEIGHTS.get(component, 0) / denominator)
                    if disposition == "ALIGNED" and denominator
                    else 0
                ),
                disposition=disposition,
            )
            for component, observed, disposition in observations
        )
        return scores, max(0, min(100, quality))

    @staticmethod
    def _confidence(score: int) -> ConfidenceCategory:
        if score >= 70:
            return ConfidenceCategory.HIGH_EVIDENCE
        if score >= 40:
            return ConfidenceCategory.MODERATE_EVIDENCE
        return ConfidenceCategory.LOW_EVIDENCE

    @staticmethod
    def _tactical(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
        feeds = snapshot.get("feeds")
        argus = feeds.get("argus") if isinstance(feeds, Mapping) else None
        envelope = argus.get("data") if isinstance(argus, Mapping) else None
        data = envelope.get("data") if isinstance(envelope, Mapping) else None
        tactical = data.get("tactical_edge") if isinstance(data, Mapping) else None
        return tactical if isinstance(tactical, Mapping) else {}

    @staticmethod
    def _execution(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
        feeds = snapshot.get("feeds")
        strategy = feeds.get("strategy_lab") if isinstance(feeds, Mapping) else None
        data = strategy.get("data") if isinstance(strategy, Mapping) else None
        execution = data.get("execution") if isinstance(data, Mapping) else None
        return execution if isinstance(execution, Mapping) else {}
