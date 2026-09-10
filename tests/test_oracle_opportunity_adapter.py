import ast
import copy
import dataclasses
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.oracle.opportunity_adapter import (
    SnapshotAdapterError,
    adapt_v2_snapshot,
    evaluate_v2_snapshot,
)
from src.oracle.opportunity_gate import (
    Direction,
    Freshness,
    GateDecision,
    InstrumentType,
    LiquidityState,
    RiskEligibility,
    VolatilityState,
)


pytestmark = [pytest.mark.unit, pytest.mark.safety]
NOW = datetime(2026, 7, 26, 8, 37, 28, tzinfo=timezone.utc)


def v2_snapshot(
    *,
    direction: str = "BULLISH",
    instrument: str = "OPTION",
) -> dict:
    argus_direction = {
        "BULLISH": "CALL",
        "BEARISH": "PUT",
        "NEUTRAL": "BALANCED",
    }[direction]
    ose_direction = {
        "BULLISH": "CLEAR CALL ADVANTAGE",
        "BEARISH": "CLEAR PUT ADVANTAGE",
        "NEUTRAL": "BALANCED",
    }[direction]
    price_trend = "MIXED" if direction == "NEUTRAL" else direction
    contracts = (
        {
            "CE": {
                "contract": {
                    "exchange_segment": "NSE_FNO",
                    "option_type": "CE",
                    "security_id": "63935",
                    "underlying": "NIFTY",
                    "expiry": "2026-07-28",
                }
            },
            "PE": {
                "contract": {
                    "exchange_segment": "NSE_FNO",
                    "option_type": "PE",
                    "security_id": "63944",
                    "underlying": "NIFTY",
                    "expiry": "2026-07-28",
                }
            },
        }
        if instrument == "OPTION"
        else {}
    )
    segment = "IDX_I" if instrument == "OPTION" else "NSE_EQ"
    return {
        "api_version": "2.0",
        "symbol": "NIFTY" if instrument == "OPTION" else "RELIANCE",
        "generated_at": NOW.isoformat(),
        "polling": {
            "delivery": "PRECOMPUTED_SNAPSHOT",
            "snapshot_status": "FRESH",
        },
        "feeds": {
            "oracle": {
                "data": {
                    "market_data_as_of": (NOW - timedelta(seconds=1)).isoformat(),
                    "data_status": "LIVE",
                    "directional_bias": direction,
                    "regime": (
                        "SIDEWAYS" if direction == "NEUTRAL" else "TRENDING"
                    ),
                    "input_features": {
                        "price_trend": price_trend,
                        "timeframe_bias": direction,
                        "volatility": "SIDEWAYS",
                        "liquidity": "RANGE_LIQUIDITY",
                    },
                    "warnings": [],
                    "reason_codes": [],
                },
                "meta": {
                    "calculation_timestamp": NOW.isoformat(),
                    "generated_at": (
                        NOW + timedelta(milliseconds=50)
                    ).isoformat(),
                },
            },
            "argus": {
                "data": {
                    "data": {
                        "underlying": {"segment": segment},
                        "tactical_edge": {
                            "freshness": "LIVE",
                            "decision": {
                                "market_direction": argus_direction,
                                "all_candidate_ranks": [
                                    {
                                        "rank": 1,
                                        "side": (
                                            "PE"
                                            if direction == "BEARISH"
                                            else "CE"
                                        ),
                                        "status": "CANDIDATE",
                                        "rejection_reason": None,
                                        "spread_abs": 0.2,
                                        "spread_pct": 0.2,
                                    }
                                ],
                            },
                            "iv_intelligence": {
                                "status": "AVAILABLE",
                                "direction": "STABLE",
                            },
                        },
                    }
                }
            },
            "strategy_lab": {
                "data": {
                    "execution": {
                        "nifty_vob": {
                            "symbol": "NIFTY",
                            "nearest_support": {"side": "BULLISH"},
                            "nearest_resistance": {"side": "BEARISH"},
                            "strongest_confluence": (
                                {}
                                if direction == "NEUTRAL"
                                else {
                                    direction.lower(): {
                                        "side": direction,
                                        "tier": "STRONG",
                                    }
                                }
                            ),
                            "source_1m_sync": {
                                "runtime_status": "LIVE",
                                "backlog_count": 0,
                            },
                            "timeframes": {},
                        },
                        "options_structure": {
                            "source_freshness": "LIVE",
                            "duel": {"state": ose_direction},
                            "contracts": contracts,
                        },
                    }
                }
            },
            "risk_status": {
                "data": {
                    "risk_state_available": True,
                    "kill_switch_active": False,
                }
            },
        },
    }


@pytest.mark.parametrize(
    ("direction", "expected"),
    [
        ("BULLISH", Direction.BULLISH),
        ("BEARISH", Direction.BEARISH),
        ("NEUTRAL", Direction.NEUTRAL),
    ],
)
def test_representative_option_v2_fixture_maps_explicit_directions(
    direction, expected
):
    mapped = adapt_v2_snapshot(v2_snapshot(direction=direction))

    assert mapped.instrument_type is InstrumentType.OPTION
    assert mapped.market_regime is expected
    assert mapped.price_structure is expected
    assert mapped.argus_metrics is expected
    assert mapped.ose_context is expected
    assert mapped.vob_context is (
        Direction.UNAVAILABLE if direction == "NEUTRAL" else expected
    )
    assert mapped.volatility is VolatilityState.NEUTRAL
    assert mapped.liquidity_spread is (
        LiquidityState.UNAVAILABLE
        if direction == "NEUTRAL"
        else LiquidityState.ACCEPTABLE
    )
    assert mapped.risk_eligibility is RiskEligibility.ELIGIBLE
    if direction == "NEUTRAL":
        assert "VOB_DIRECTION_NOT_REPORTED" in mapped.unavailable_reasons
        assert (
            "LIQUIDITY_SPREAD_DIRECTION_UNAVAILABLE"
            in mapped.unavailable_reasons
        )
    else:
        assert "VOB_DIRECTION_NOT_REPORTED" not in mapped.unavailable_reasons


def test_representative_equity_v2_fixture_maps_without_ose_authority():
    supplied = v2_snapshot(instrument="EQUITY")
    supplied["feeds"]["strategy_lab"]["data"]["execution"][
        "options_structure"
    ] = {}

    mapped = adapt_v2_snapshot(supplied)
    result = evaluate_v2_snapshot(supplied)

    assert mapped.instrument_type is InstrumentType.EQUITY
    assert mapped.ose_context is Direction.UNAVAILABLE
    assert "OSE_DIRECTION_NOT_REPORTED" in mapped.unavailable_reasons
    assert result.decision is GateDecision.EQUITY


@pytest.mark.parametrize(
    ("direction", "decision", "score"),
    [
        ("BULLISH", GateDecision.CALL, 95),
        ("BEARISH", GateDecision.PUT, 95),
    ],
)
def test_valid_directional_fixtures_reach_symmetric_gate_decisions(
    direction, decision, score
):
    result = evaluate_v2_snapshot(v2_snapshot(direction=direction))

    assert result.decision is decision
    assert result.evidence_quality_score == score
    assert result.rejection_reasons == ()
    assert tuple(
        (component.component, component.awarded)
        for component in result.component_scores
    ) == (
        ("market_regime", 15),
        ("price_structure", 20),
        ("vob_context", 20),
        ("argus_metrics", 15),
        ("ose_context", 15),
        ("volatility", 5),
        ("liquidity_spread", 5),
    )


def test_valid_no_trade_fixture_preserves_conflict():
    supplied = v2_snapshot(direction="BULLISH")
    supplied["feeds"]["strategy_lab"]["data"]["execution"][
        "options_structure"
    ]["duel"]["state"] = "CLEAR PUT ADVANTAGE"

    result = evaluate_v2_snapshot(supplied)

    assert result.decision is GateDecision.NO_TRADE
    assert "DIRECTIONAL_CONFLICT" in result.rejection_reasons
    assert result.evidence_quality_score == 10


def test_directional_bias_is_not_used_as_market_regime():
    supplied = v2_snapshot(direction="BULLISH")
    supplied["feeds"]["oracle"]["data"]["directional_bias"] = "BEARISH"

    mapped = adapt_v2_snapshot(supplied)

    assert mapped.market_regime is Direction.BULLISH


def test_regime_requires_its_own_directional_context():
    supplied = v2_snapshot(direction="BULLISH")
    supplied["feeds"]["oracle"]["data"]["input_features"][
        "timeframe_bias"
    ] = "NEUTRAL"

    mapped = adapt_v2_snapshot(supplied)
    result = evaluate_v2_snapshot(supplied)

    assert mapped.market_regime is Direction.UNAVAILABLE
    assert (
        "MARKET_REGIME_DIRECTION_UNSUPPORTED"
        in mapped.unavailable_reasons
    )
    assert result.decision is GateDecision.NO_TRADE


def test_evaluation_time_uses_calculation_timestamp_not_wrapper_generated_at():
    supplied = v2_snapshot()
    supplied["feeds"]["oracle"]["meta"]["generated_at"] = (
        NOW + timedelta(hours=2)
    ).isoformat()

    mapped = adapt_v2_snapshot(supplied)

    assert mapped.evaluation_timestamp == NOW


@pytest.mark.parametrize(
    "mutation",
    [
        lambda ce, pe: pe.update(security_id=ce["security_id"]),
        lambda ce, pe: pe.update(option_type="CE"),
        lambda ce, pe: pe.update(exchange_segment="NSE_EQ"),
        lambda ce, pe: (
            ce.update(underlying="NIFTY"),
            pe.update(underlying="BANKNIFTY"),
        ),
        lambda ce, pe: (
            ce.update(expiry="2026-07-28"),
            pe.update(expiry="2026-08-04"),
        ),
    ],
)
def test_conflicting_ce_pe_pair_fails_closed(mutation):
    supplied = v2_snapshot()
    contracts = supplied["feeds"]["strategy_lab"]["data"]["execution"][
        "options_structure"
    ]["contracts"]
    ce = contracts["CE"]["contract"]
    pe = contracts["PE"]["contract"]
    mutation(ce, pe)

    with pytest.raises(SnapshotAdapterError, match="pair is conflicting"):
        adapt_v2_snapshot(supplied)


def test_ambiguous_real_vob_confluence_remains_unavailable():
    supplied = v2_snapshot()
    supplied["feeds"]["strategy_lab"]["data"]["execution"]["nifty_vob"][
        "strongest_confluence"
    ]["bearish"] = {"side": "BEARISH", "tier": "STRONG"}

    mapped = adapt_v2_snapshot(supplied)
    result = evaluate_v2_snapshot(supplied)

    assert mapped.vob_context is Direction.UNAVAILABLE
    assert "VOB_DIRECTION_AMBIGUOUS" in mapped.unavailable_reasons
    assert "vob_context" in result.critical_missing_inputs
    assert result.decision is GateDecision.NO_TRADE


def test_missing_vob_blocks_only_because_gate_marks_it_critical():
    supplied = v2_snapshot()
    supplied["feeds"]["strategy_lab"]["data"]["execution"]["nifty_vob"][
        "strongest_confluence"
    ] = {}

    result = evaluate_v2_snapshot(supplied)

    assert "vob_context" in result.critical_missing_inputs
    assert result.evidence_quality_score == 75
    assert result.decision is GateDecision.NO_TRADE


def test_one_stale_critical_feed_cannot_be_hidden_by_fresh_feeds():
    supplied = v2_snapshot()
    supplied["feeds"]["strategy_lab"]["data"]["execution"][
        "options_structure"
    ]["source_freshness"] = "STALE"

    mapped = adapt_v2_snapshot(supplied)
    result = evaluate_v2_snapshot(supplied)

    assert mapped.freshness is Freshness.STALE
    assert "OSE_STALE" in mapped.unavailable_reasons
    assert "STALE_SNAPSHOT" in result.rejection_reasons


@pytest.mark.parametrize(
    ("backlog", "expected_reason"),
    [
        (1, "VOB_STALE"),
        (True, "VOB_FRESHNESS_UNSUPPORTED"),
        ("0", "VOB_FRESHNESS_UNSUPPORTED"),
    ],
)
def test_vob_backlog_and_malformed_counts_cannot_appear_fresh(
    backlog, expected_reason
):
    supplied = v2_snapshot()
    supplied["feeds"]["strategy_lab"]["data"]["execution"]["nifty_vob"][
        "source_1m_sync"
    ]["backlog_count"] = backlog

    mapped = adapt_v2_snapshot(supplied)
    result = evaluate_v2_snapshot(supplied)

    assert mapped.freshness is not Freshness.FRESH
    assert expected_reason in mapped.unavailable_reasons
    assert result.decision is GateDecision.NO_TRADE


def test_kill_switch_blocks_and_missing_risk_fails_closed():
    blocked = v2_snapshot()
    blocked["feeds"]["risk_status"]["data"]["kill_switch_active"] = True
    missing = v2_snapshot()
    missing["feeds"]["risk_status"]["data"] = {
        "risk_state_available": False,
        "kill_switch_active": None,
    }

    blocked_result = evaluate_v2_snapshot(blocked)
    missing_result = evaluate_v2_snapshot(missing)

    assert blocked_result.decision is GateDecision.NO_TRADE
    assert "RISK_NOT_ELIGIBLE" in blocked_result.rejection_reasons
    assert missing_result.decision is GateDecision.NO_TRADE
    assert "risk_eligibility" in missing_result.critical_missing_inputs


@pytest.mark.parametrize(
    "path",
    [
        ("feeds", "oracle", "data", "input_features"),
        ("feeds", "argus", "data", "data", "tactical_edge"),
        (
            "feeds",
            "strategy_lab",
            "data",
            "execution",
            "options_structure",
        ),
        ("feeds", "risk_status", "data"),
    ],
)
def test_malformed_nested_objects_are_rejected(path):
    supplied = v2_snapshot()
    target = supplied
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = []

    with pytest.raises(SnapshotAdapterError, match="malformed"):
        adapt_v2_snapshot(supplied)


@pytest.mark.parametrize("value", [True, "0.2", math.nan, math.inf])
def test_malformed_spread_values_are_rejected_fail_closed(value):
    supplied = v2_snapshot()
    rank = supplied["feeds"]["argus"]["data"]["data"]["tactical_edge"][
        "decision"
    ]["all_candidate_ranks"][0]
    rank["spread_pct"] = value

    mapped = adapt_v2_snapshot(supplied)
    result = evaluate_v2_snapshot(supplied)

    assert mapped.liquidity_spread is LiquidityState.UNAVAILABLE
    assert "LIQUIDITY_SPREAD_MALFORMED" in mapped.unavailable_reasons
    assert result.decision is GateDecision.NO_TRADE


def test_output_is_frozen_and_source_warning_order_is_stable():
    first = v2_snapshot()
    second = v2_snapshot()
    first["feeds"]["oracle"]["data"]["warnings"] = ["Z_REASON", "A_REASON"]
    second["feeds"]["oracle"]["data"]["warnings"] = ["A_REASON", "Z_REASON"]

    left = adapt_v2_snapshot(first)
    right = adapt_v2_snapshot(second)

    assert left == right
    with pytest.raises(dataclasses.FrozenInstanceError):
        left.symbol = "BANKNIFTY"


def test_stale_and_unavailable_sources_are_preserved_fail_closed():
    supplied = v2_snapshot()
    supplied["feeds"]["oracle"]["data"]["data_status"] = "CACHED"
    supplied["feeds"]["oracle"]["data"]["warnings"] = [
        "CACHED_MARKET_SNAPSHOT"
    ]
    supplied["feeds"]["argus"]["data"]["data"]["tactical_edge"][
        "freshness"
    ] = "STALE"

    mapped = adapt_v2_snapshot(supplied)
    result = evaluate_v2_snapshot(supplied)

    assert mapped.freshness is Freshness.STALE
    assert {
        "ARGUS_STALE",
        "CACHED_MARKET_SNAPSHOT",
        "ORACLE_STALE",
    }.issubset(mapped.unavailable_reasons)
    assert result.decision is GateDecision.NO_TRADE
    assert "STALE_SNAPSHOT" in result.rejection_reasons


def test_missing_nested_contract_fails_closed_without_defaults():
    supplied = v2_snapshot()
    del supplied["feeds"]["oracle"]

    with pytest.raises(
        SnapshotAdapterError, match="feeds.oracle is missing or malformed"
    ):
        adapt_v2_snapshot(supplied)


def test_unknown_enum_values_become_unavailable_with_exact_reasons():
    supplied = v2_snapshot()
    oracle = supplied["feeds"]["oracle"]["data"]
    oracle["regime"] = "UPISH"
    oracle["input_features"]["price_trend"] = "CHAOTIC"
    tactical = supplied["feeds"]["argus"]["data"]["data"]["tactical_edge"]
    tactical["decision"]["market_direction"] = "SIDE"
    tactical["iv_intelligence"]["direction"] = "MYSTERY"
    tactical["decision"]["all_candidate_ranks"] = []
    supplied["feeds"]["strategy_lab"]["data"]["execution"][
        "options_structure"
    ]["duel"]["state"] = "UNCERTAIN"

    mapped = adapt_v2_snapshot(supplied)

    assert mapped.market_regime is Direction.UNAVAILABLE
    assert mapped.price_structure is Direction.UNAVAILABLE
    assert mapped.argus_metrics is Direction.UNAVAILABLE
    assert mapped.ose_context is Direction.UNAVAILABLE
    assert mapped.volatility is VolatilityState.UNAVAILABLE
    assert mapped.liquidity_spread is LiquidityState.UNAVAILABLE
    assert {
        "ARGUS_DIRECTION_UNSUPPORTED",
        "LIQUIDITY_SPREAD_DIRECTION_UNAVAILABLE",
        "MARKET_REGIME_UNSUPPORTED",
        "OSE_DIRECTION_UNSUPPORTED",
        "PRICE_STRUCTURE_UNSUPPORTED",
        "VOLATILITY_UNSUPPORTED",
    }.issubset(mapped.unavailable_reasons)


@pytest.mark.parametrize("malformed", [True, 1, math.nan, math.inf])
def test_malformed_numeric_or_boolean_evidence_never_becomes_directional(
    malformed,
):
    supplied = v2_snapshot()
    supplied["feeds"]["oracle"]["data"]["regime"] = malformed
    supplied["feeds"]["argus"]["data"]["data"]["tactical_edge"][
        "iv_intelligence"
    ]["direction"] = malformed

    mapped = adapt_v2_snapshot(supplied)

    assert mapped.market_regime is Direction.UNAVAILABLE
    assert mapped.volatility is VolatilityState.UNAVAILABLE
    assert "MARKET_REGIME_UNSUPPORTED" in mapped.unavailable_reasons
    assert "VOLATILITY_UNSUPPORTED" in mapped.unavailable_reasons


@pytest.mark.parametrize(
    ("field_path", "value"),
    [
        (("feeds", "oracle", "data", "market_data_as_of"), "not-a-time"),
        (
            ("feeds", "oracle", "meta", "calculation_timestamp"),
            "2026-07-26T08:37:28",
        ),
        (("feeds", "oracle", "meta", "calculation_timestamp"), 123),
    ],
)
def test_malformed_or_naive_timestamps_are_rejected(field_path, value):
    supplied = v2_snapshot()
    target = supplied
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = value

    with pytest.raises(SnapshotAdapterError):
        adapt_v2_snapshot(supplied)


def test_future_source_timestamp_remains_a_gate_rejection():
    supplied = v2_snapshot()
    supplied["feeds"]["oracle"]["data"]["market_data_as_of"] = (
        NOW + timedelta(seconds=1)
    ).isoformat()

    result = evaluate_v2_snapshot(supplied)

    assert result.decision is GateDecision.NO_TRADE
    assert "FUTURE_SNAPSHOT_TIMESTAMP" in result.rejection_reasons


def test_equal_source_and_evaluation_timestamp_is_valid_boundary():
    supplied = v2_snapshot()
    supplied["feeds"]["oracle"]["data"][
        "market_data_as_of"
    ] = NOW.isoformat()

    result = evaluate_v2_snapshot(supplied)

    assert result.decision is GateDecision.CALL
    assert "FUTURE_SNAPSHOT_TIMESTAMP" not in result.rejection_reasons


def test_unknown_freshness_fails_closed():
    supplied = v2_snapshot()
    supplied["feeds"]["argus"]["data"]["data"]["tactical_edge"][
        "freshness"
    ] = "MAYBE"

    mapped = adapt_v2_snapshot(supplied)
    result = evaluate_v2_snapshot(supplied)

    assert mapped.freshness is Freshness.UNAVAILABLE
    assert "ARGUS_FRESHNESS_UNSUPPORTED" in mapped.unavailable_reasons
    assert result.decision is GateDecision.NO_TRADE


def test_current_production_shaped_weekend_snapshot_is_truthful_no_trade():
    supplied = v2_snapshot(direction="NEUTRAL")
    oracle = supplied["feeds"]["oracle"]["data"]
    oracle.update(
        data_status="UNAVAILABLE",
        directional_bias="NEUTRAL",
        regime="UNKNOWN",
        warnings=["MARKET_PRICE_UNAVAILABLE"],
        reason_codes=["MARKET_PRICE_UNAVAILABLE"],
    )
    oracle["input_features"].update(
        price_trend="MIXED",
        timeframe_bias="NEUTRAL",
        volatility="SIDEWAYS",
        liquidity="RANGE_LIQUIDITY",
    )
    tactical = supplied["feeds"]["argus"]["data"]["data"]["tactical_edge"]
    tactical["freshness"] = "STALE"
    tactical["decision"]["market_direction"] = "BALANCED"
    ose = supplied["feeds"]["strategy_lab"]["data"]["execution"][
        "options_structure"
    ]
    ose["source_freshness"] = "STALE"
    ose["duel"]["state"] = "BALANCED"
    vob = supplied["feeds"]["strategy_lab"]["data"]["execution"][
        "nifty_vob"
    ]
    vob["strongest_confluence"] = {
        "bullish": {"side": "BULLISH", "tier": "ULTRA STRONG"},
        "bearish": {"side": "BEARISH", "tier": "STRONG"},
    }
    supplied["feeds"]["risk_status"]["data"] = {
        "risk_state_available": False,
        "kill_switch_active": None,
    }

    mapped = adapt_v2_snapshot(supplied)
    result = evaluate_v2_snapshot(supplied)

    assert mapped.freshness is Freshness.UNAVAILABLE
    assert mapped.market_regime is Direction.UNAVAILABLE
    assert mapped.vob_context is Direction.UNAVAILABLE
    assert mapped.risk_eligibility is RiskEligibility.UNAVAILABLE
    assert result.decision is GateDecision.NO_TRADE
    assert result.evidence_quality_score == 5
    assert {
        "ARGUS_STALE",
        "MARKET_PRICE_UNAVAILABLE",
        "ORACLE_FRESHNESS_NOT_REPORTED",
        "OSE_STALE",
        "RISK_ELIGIBILITY_NOT_REPORTED",
        "VOB_DIRECTION_AMBIGUOUS",
    }.issubset(mapped.unavailable_reasons)


def test_input_order_does_not_change_mapping_or_gate_result():
    supplied = v2_snapshot()

    def reversed_maps(value):
        if isinstance(value, dict):
            return {
                key: reversed_maps(item)
                for key, item in reversed(tuple(value.items()))
            }
        if isinstance(value, list):
            return [reversed_maps(item) for item in value]
        return value

    reordered = reversed_maps(supplied)

    assert adapt_v2_snapshot(supplied) == adapt_v2_snapshot(reordered)
    assert evaluate_v2_snapshot(supplied) == evaluate_v2_snapshot(reordered)


def test_adapter_does_not_mutate_source_and_repeats_deterministically():
    supplied = v2_snapshot()
    before = json.dumps(supplied, sort_keys=True)

    mapped = [adapt_v2_snapshot(supplied) for _ in range(25)]
    results = [evaluate_v2_snapshot(supplied) for _ in range(25)]

    assert len(set(mapped)) == 1
    assert len(set(results)) == 1
    assert json.dumps(supplied, sort_keys=True) == before
    assert copy.deepcopy(supplied) == supplied


def test_missing_risk_state_and_missing_timestamp_are_truthful():
    supplied = v2_snapshot()
    supplied["feeds"]["risk_status"]["data"] = {
        "risk_state_available": False,
        "kill_switch_active": None,
    }
    supplied["feeds"]["oracle"]["data"]["market_data_as_of"] = None

    mapped = adapt_v2_snapshot(supplied)
    result = evaluate_v2_snapshot(supplied)

    assert mapped.snapshot_timestamp is None
    assert mapped.risk_eligibility is RiskEligibility.UNAVAILABLE
    assert "RISK_ELIGIBILITY_NOT_REPORTED" in mapped.unavailable_reasons
    assert result.decision is GateDecision.NO_TRADE


def test_adapter_has_no_forbidden_runtime_imports_or_calls():
    source_path = (
        Path(__file__).parents[1]
        / "src"
        / "oracle"
        / "opportunity_adapter.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    forbidden_imports = {
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "dhanhq",
        "openalgo",
    }
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert forbidden_imports.isdisjoint(imported)
    assert {"request", "post", "put", "delete", "fetch", "poll"}.isdisjoint(
        calls
    )
