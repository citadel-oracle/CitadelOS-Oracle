import ast
import dataclasses
import itertools
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.oracle.opportunity_gate import (
    ConfidenceCategory,
    Direction,
    Freshness,
    GateDecision,
    InstrumentType,
    LiquidityState,
    OpportunityGate,
    OpportunitySnapshot,
    RiskEligibility,
    VolatilityState,
)


pytestmark = [pytest.mark.unit, pytest.mark.safety]
NOW = datetime(2026, 7, 26, 7, 0, tzinfo=timezone.utc)


def snapshot(**changes):
    values = {
        "symbol": "NIFTY",
        "instrument_type": InstrumentType.OPTION,
        "snapshot_timestamp": NOW,
        "evaluation_timestamp": NOW,
        "freshness": Freshness.FRESH,
        "market_regime": Direction.BULLISH,
        "price_structure": Direction.BULLISH,
        "vob_context": Direction.BULLISH,
        "argus_metrics": Direction.BULLISH,
        "ose_context": Direction.BULLISH,
        "volatility": VolatilityState.SUPPORTIVE,
        "liquidity_spread": LiquidityState.ACCEPTABLE,
        "risk_eligibility": RiskEligibility.ELIGIBLE,
        "unavailable_reasons": (),
    }
    values.update(changes)
    return OpportunitySnapshot(**values)


def test_repeated_evaluation_is_deterministic_and_does_not_mutate_input():
    supplied = snapshot(unavailable_reasons=("zeta", "alpha"))
    before = dataclasses.asdict(supplied)

    results = [OpportunityGate.evaluate(supplied) for _ in range(100)]

    assert len(set(results)) == 1
    assert dataclasses.asdict(supplied) == before


def test_unavailable_reason_order_cannot_change_result():
    first = OpportunityGate.evaluate(
        snapshot(
            price_structure=Direction.UNAVAILABLE,
            unavailable_reasons=("source_b", "source_a"),
        )
    )
    second = OpportunityGate.evaluate(
        snapshot(
            price_structure=Direction.UNAVAILABLE,
            unavailable_reasons=("source_a", "source_b"),
        )
    )

    assert first == second
    assert first.unavailable_reasons == ("source_a", "source_b")
    assert first.rejection_reasons[-2:] == (
        "UNAVAILABLE:source_a",
        "UNAVAILABLE:source_b",
    )


def test_complete_bullish_alignment_returns_call():
    result = OpportunityGate.evaluate(snapshot())

    assert result.decision is GateDecision.CALL
    assert result.evidence_quality_score == 100
    assert result.confidence_category is ConfidenceCategory.HIGH_EVIDENCE
    assert result.rejection_reasons == ()


def test_complete_bearish_alignment_returns_put():
    result = OpportunityGate.evaluate(
        snapshot(
            market_regime=Direction.BEARISH,
            price_structure=Direction.BEARISH,
            vob_context=Direction.BEARISH,
            argus_metrics=Direction.BEARISH,
            ose_context=Direction.BEARISH,
        )
    )

    assert result.decision is GateDecision.PUT
    assert result.evidence_quality_score == 100


def test_valid_equity_alignment_returns_equity_without_ose_authority():
    result = OpportunityGate.evaluate(
        snapshot(
            instrument_type=InstrumentType.EQUITY,
            ose_context=Direction.UNAVAILABLE,
        )
    )

    assert result.decision is GateDecision.EQUITY
    assert result.evidence_quality_score == 85
    assert "ose_context" not in result.critical_missing_inputs


def test_mixed_direction_is_no_trade_even_when_coverage_is_high():
    result = OpportunityGate.evaluate(
        snapshot(vob_context=Direction.BEARISH)
    )

    assert result.decision is GateDecision.NO_TRADE
    assert "DIRECTIONAL_CONFLICT" in result.rejection_reasons
    assert {
        "market_regime",
        "price_structure",
        "vob_context",
        "argus_metrics",
        "ose_context",
    }.issubset(result.conflicting_evidence)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"freshness": Freshness.STALE}, "STALE_SNAPSHOT"),
        (
            {
                "price_structure": Direction.UNAVAILABLE,
                "unavailable_reasons": ("PRICE_STRUCTURE_NOT_REPORTED",),
            },
            "CRITICAL_INPUTS_MISSING",
        ),
    ],
)
def test_stale_or_critical_unavailable_data_is_no_trade(changes, reason):
    result = OpportunityGate.evaluate(snapshot(**changes))

    assert result.decision is GateDecision.NO_TRADE
    assert reason in result.rejection_reasons


def test_noncritical_unavailable_evidence_is_truthful_without_forced_rejection():
    result = OpportunityGate.evaluate(
        snapshot(
            argus_metrics=Direction.UNAVAILABLE,
            volatility=VolatilityState.UNAVAILABLE,
            unavailable_reasons=(
                "ARGUS_NOT_REPORTED",
                "VOLATILITY_NOT_REPORTED",
            ),
        )
    )

    assert result.decision is GateDecision.CALL
    assert result.evidence_quality_score == 75
    assert result.unavailable_reasons == (
        "ARGUS_NOT_REPORTED",
        "VOLATILITY_NOT_REPORTED",
    )
    assert result.rejection_reasons == ()


def test_weak_evidence_is_no_trade_at_score_boundary():
    below = OpportunityGate.evaluate(
        snapshot(
            vob_context=Direction.NEUTRAL,
            argus_metrics=Direction.NEUTRAL,
            ose_context=Direction.NEUTRAL,
        )
    )
    boundary = OpportunityGate.evaluate(
        snapshot(
            argus_metrics=Direction.NEUTRAL,
            ose_context=Direction.NEUTRAL,
        )
    )

    assert below.evidence_quality_score == 50
    assert below.decision is GateDecision.NO_TRADE
    assert "EVIDENCE_QUALITY_BELOW_THRESHOLD" in below.rejection_reasons
    assert boundary.evidence_quality_score == 70
    assert boundary.decision is GateDecision.CALL


@pytest.mark.parametrize(
    ("score", "accepted"),
    [(69, False), (70, True), (71, True)],
)
def test_exact_evidence_quality_threshold(score, accepted):
    assert OpportunityGate._score_is_sufficient(score) is accepted


@pytest.mark.parametrize("score", [True, math.nan, math.inf, "70", None])
def test_malformed_evidence_scores_are_rejected(score):
    with pytest.raises(TypeError):
        OpportunityGate._score_is_sufficient(score)


@pytest.mark.parametrize("score", [-1, 101])
def test_out_of_bounds_evidence_scores_are_rejected(score):
    with pytest.raises(ValueError):
        OpportunityGate._score_is_sufficient(score)


@pytest.mark.parametrize(
    ("aligned", "decision"),
    [
        (2, GateDecision.NO_TRADE),
        (3, GateDecision.CALL),
        (4, GateDecision.CALL),
    ],
)
def test_independent_alignment_threshold(aligned, decision):
    values = [Direction.BULLISH] * aligned + [Direction.NEUTRAL] * (5 - aligned)
    result = OpportunityGate.evaluate(
        snapshot(
            market_regime=values[0],
            price_structure=values[1],
            vob_context=values[2],
            argus_metrics=values[3],
            ose_context=values[4],
        )
    )

    assert result.decision is decision


def test_risk_blocked_is_no_trade_without_changing_score():
    eligible = OpportunityGate.evaluate(snapshot())
    blocked = OpportunityGate.evaluate(
        snapshot(risk_eligibility=RiskEligibility.BLOCKED)
    )

    assert blocked.evidence_quality_score == eligible.evidence_quality_score
    assert blocked.decision is GateDecision.NO_TRADE
    assert "RISK_NOT_ELIGIBLE" in blocked.rejection_reasons


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"instrument_type": "OPTION"}, TypeError),
        ({"freshness": "FRESH"}, TypeError),
        ({"market_regime": "BULLISH"}, TypeError),
        ({"price_structure": True}, TypeError),
        ({"vob_context": math.nan}, TypeError),
        ({"argus_metrics": math.inf}, TypeError),
        ({"ose_context": 1}, TypeError),
        ({"volatility": "SUPPORTIVE"}, TypeError),
        ({"liquidity_spread": False}, TypeError),
        ({"risk_eligibility": "ELIGIBLE"}, TypeError),
        ({"snapshot_timestamp": math.nan}, TypeError),
        ({"evaluation_timestamp": math.inf}, TypeError),
        ({"snapshot_timestamp": datetime(2026, 7, 26)}, ValueError),
        ({"evaluation_timestamp": datetime(2026, 7, 26)}, ValueError),
    ],
)
def test_unknown_enums_and_malformed_values_fail_closed(changes, error):
    with pytest.raises(error):
        snapshot(**changes)


def test_future_and_stale_timestamps_are_no_trade():
    future = OpportunityGate.evaluate(
        snapshot(snapshot_timestamp=NOW + timedelta(microseconds=1))
    )
    stale = OpportunityGate.evaluate(snapshot(freshness=Freshness.STALE))

    assert future.decision is GateDecision.NO_TRADE
    assert future.rejection_reasons[0] == "FUTURE_SNAPSHOT_TIMESTAMP"
    assert stale.decision is GateDecision.NO_TRADE
    assert "STALE_SNAPSHOT" in stale.rejection_reasons


def test_missing_critical_input_scores_zero_for_that_component_and_blocks():
    result = OpportunityGate.evaluate(
        snapshot(price_structure=Direction.UNAVAILABLE)
    )
    component = next(
        item
        for item in result.component_scores
        if item.component == "price_structure"
    )

    assert component.awarded == 0
    assert component.disposition == "UNAVAILABLE"
    assert result.decision is GateDecision.NO_TRADE
    assert "price_structure" in result.critical_missing_inputs


def test_scoring_channels_are_unique_and_never_double_counted():
    result = OpportunityGate.evaluate(snapshot())
    components = [item.component for item in result.component_scores]

    assert len(components) == len(set(components))
    assert sum(item.weight for item in result.component_scores) == 100
    assert sum(item.awarded for item in result.component_scores) == 100


def test_call_put_and_equity_share_threshold_and_score_symmetrically():
    bullish = OpportunityGate.evaluate(snapshot())
    bearish = OpportunityGate.evaluate(
        snapshot(
            market_regime=Direction.BEARISH,
            price_structure=Direction.BEARISH,
            vob_context=Direction.BEARISH,
            argus_metrics=Direction.BEARISH,
            ose_context=Direction.BEARISH,
        )
    )
    equity = OpportunityGate.evaluate(
        snapshot(instrument_type=InstrumentType.EQUITY)
    )

    assert (bullish.decision, bearish.decision, equity.decision) == (
        GateDecision.CALL,
        GateDecision.PUT,
        GateDecision.EQUITY,
    )
    assert {
        bullish.evidence_quality_score,
        bearish.evidence_quality_score,
        equity.evidence_quality_score,
    } == {100}


def test_all_direction_permutations_are_deterministic_bounded_and_fail_conflicts():
    directions = tuple(Direction)
    for values in itertools.product(directions, repeat=5):
        supplied = snapshot(
            market_regime=values[0],
            price_structure=values[1],
            vob_context=values[2],
            argus_metrics=values[3],
            ose_context=values[4],
        )
        first = OpportunityGate.evaluate(supplied)
        second = OpportunityGate.evaluate(supplied)
        reported = {
            value
            for value in values
            if value in {Direction.BULLISH, Direction.BEARISH}
        }

        assert first == second
        assert 0 <= first.evidence_quality_score <= 100
        if len(reported) > 1:
            assert first.decision is GateDecision.NO_TRADE


def test_keyword_input_order_does_not_change_result():
    values = dataclasses.asdict(snapshot())
    forward = OpportunitySnapshot(**values)
    reverse = OpportunitySnapshot(**dict(reversed(tuple(values.items()))))

    assert OpportunityGate.evaluate(forward) == OpportunityGate.evaluate(reverse)


@pytest.mark.parametrize(
    "supplied",
    [
        snapshot(),
        snapshot(
            market_regime=Direction.BEARISH,
            price_structure=Direction.BEARISH,
            vob_context=Direction.BEARISH,
            argus_metrics=Direction.BEARISH,
            ose_context=Direction.BEARISH,
        ),
        snapshot(freshness=Freshness.STALE),
    ],
)
def test_probability_planning_and_execution_fields_are_always_disabled(supplied):
    result = OpportunityGate.evaluate(supplied)

    assert result.probability is None
    assert result.contract is None
    assert result.entry is None
    assert result.stop_loss is None
    assert result.targets is None
    assert result.quantity is None
    assert result.execution_allowed is False


def test_inputs_outputs_and_scoring_components_are_immutable():
    result = OpportunityGate.evaluate(snapshot())

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.decision = GateDecision.NO_TRADE
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.component_scores[0].awarded = 0
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot().symbol = "BANKNIFTY"


def test_module_has_no_forbidden_runtime_imports_or_calls():
    path = Path(__file__).parents[1] / "src/oracle/opportunity_gate.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = []
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
        elif isinstance(node, ast.Call):
            calls.append(
                getattr(
                    node.func,
                    "id",
                    getattr(node.func, "attr", ""),
                )
            )

    forbidden = {
        "requests",
        "httpx",
        "urllib",
        "socket",
        "openai",
        "dhan",
        "argus",
        "broker",
        "order",
        "fill",
        "mission",
        "guardian",
        "strategy",
        "risk_mutation",
    }
    searchable = {value.lower() for value in imports + calls}

    assert not {
        forbidden_name
        for forbidden_name in forbidden
        if any(forbidden_name in value for value in searchable)
    }
