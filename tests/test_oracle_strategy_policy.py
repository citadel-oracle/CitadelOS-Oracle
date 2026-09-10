from copy import deepcopy
from datetime import datetime, timezone

import pytest

from src.oracle.opportunity_adapter import (
    adapt_v2_snapshot,
    evaluate_v2_snapshot,
    strategy_triggers_from_v2,
)
from src.oracle.opportunity_gate import (
    DecisionLane,
    EntryState,
    GateDecision,
    OpportunityGate,
    TriggerSource,
)
from src.oracle.strategy_policy import StrategyTrigger, StrategyTriggeredPolicy


pytestmark = [pytest.mark.unit, pytest.mark.safety]
BOUNDARY = "2026-07-27T10:00:00+05:30"
EVALUATED = "2026-07-27T10:00:10+05:30"


def snapshot(
    *,
    price_structure="BULLISH",
    ose="MODERATE CALL ADVANTAGE",
    argus="BALANCED",
    persistence="BALANCED",
    lifecycle=True,
):
    zone = {
        "status": "BROKEN",
        "role": "RESISTANCE",
        "side": "BEARISH",
        "zone_id": "zone-1",
        "broken_at": BOUNDARY,
        "source_candle_timestamp": BOUNDARY,
        "last_tested_time": None,
    }
    return {
        "symbol": "NIFTY",
        "generated_at": EVALUATED,
        "intelligence_boundary": {
            "status": "COHERENT",
            "timeframe": "5m",
            "completed_boundary": BOUNDARY,
            "modules": {
                "ORACLE": BOUNDARY,
                "OSE": BOUNDARY,
                "VOB": BOUNDARY,
            },
        },
        "polling": {"snapshot_status": "FRESH"},
        "feeds": {
            "oracle": {
                "data": {
                    "market_data_as_of": BOUNDARY,
                    "data_status": "LIVE",
                    "regime": "TRENDING",
                    "input_features": {
                        "price_trend": price_structure,
                        "timeframe_bias": price_structure,
                    },
                },
                "meta": {"calculation_timestamp": EVALUATED},
            },
            "argus": {
                "data": {
                    "data": {
                        "underlying": {"segment": "IDX_I"},
                        "tactical_edge": {
                            "freshness": "LIVE",
                            "decision": {
                                "banner": argus,
                                "market_direction": (
                                    "PUT" if "PUT" in argus else "CALL"
                                    if "CALL" in argus
                                    else "BALANCED"
                                ),
                                "all_candidate_ranks": [
                                    {
                                        "rank": 1,
                                        "side": "CE",
                                        "status": "CANDIDATE",
                                        "rejection_reason": None,
                                        "spread_abs": 0.2,
                                        "spread_pct": 0.2,
                                    },
                                    {
                                        "rank": 2,
                                        "side": "PE",
                                        "status": "CANDIDATE",
                                        "rejection_reason": None,
                                        "spread_abs": 0.2,
                                        "spread_pct": 0.2,
                                    },
                                ],
                            },
                            "pressure": {
                                "direction": (
                                    "PUT" if "PUT" in argus else "CALL"
                                    if "CALL" in argus
                                    else "BALANCED"
                                ),
                                "state": (
                                    "NO_CLEAN_EDGE"
                                    if argus == "BALANCED"
                                    else "CLEAN_EDGE"
                                ),
                            },
                            "persistence": {
                                "status": "AVAILABLE",
                                "direction": persistence,
                                "consecutive_confirmations": 3,
                                "required_count": 3,
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
                            "strongest_confluence": {
                                "bullish": {
                                    "side": "BULLISH",
                                    "confluence_score": 75,
                                },
                                "bearish": {
                                    "side": "BEARISH",
                                    "confluence_score": 75,
                                },
                            },
                            "source_1m_sync": {
                                "runtime_status": "LIVE",
                                "backlog_count": 0,
                            },
                            "timeframes": {
                                "5m": {
                                    "evaluated_through": BOUNDARY,
                                    "recently_broken": [zone]
                                    if lifecycle
                                    else [],
                                }
                            },
                        },
                        "options_structure": {
                            "source_freshness": "LIVE",
                            "duel": {"state": ose},
                            "contracts": {
                                "CE": {
                                    "contract": {
                                        "exchange_segment": "NSE_FNO",
                                        "option_type": "CE",
                                        "security_id": "1",
                                        "underlying": "NIFTY",
                                        "expiry": "2026-07-30",
                                    }
                                },
                                "PE": {
                                    "contract": {
                                        "exchange_segment": "NSE_FNO",
                                        "option_type": "PE",
                                        "security_id": "2",
                                        "underlying": "NIFTY",
                                        "expiry": "2026-07-30",
                                    }
                                },
                            },
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
            "matrix": {"data": []},
        },
    }


def test_fresh_vob_break_uses_strategy_lane_without_unanimity():
    result = evaluate_v2_snapshot(snapshot())

    assert result.decision_lane is DecisionLane.STRATEGY_TRIGGERED
    assert result.trigger_source is TriggerSource.VOB_BREAKOUT
    assert result.decision is GateDecision.CALL
    assert result.entry_state is EntryState.READY
    assert result.confidence_category.value != "LOW_EVIDENCE"
    assert "argus_metrics" in result.neutral_evidence
    assert "spot_volume" in result.neutral_evidence
    spot = next(
        row for row in result.component_scores if row.component == "spot_volume"
    )
    assert spot.observed == "NOT_APPLICABLE"
    assert spot.weight == 0
    assert spot.disposition == "NOT_APPLICABLE"
    assert any(
        row.component == "ose_context"
        and row.observed == "MODERATE_SUPPORT"
        for row in result.component_scores
    )


def test_persistent_opposite_argus_is_hard_veto():
    result = evaluate_v2_snapshot(
        snapshot(argus="CLEAR PUT ADVANTAGE", persistence="PUT")
    )

    assert result.entry_state is EntryState.REJECTED
    assert result.decision is GateDecision.NO_TRADE
    assert "OPPOSITE_ARGUS_METRICS" in result.hard_vetoes


def test_static_vob_tie_without_fresh_lifecycle_stays_discovery():
    supplied = snapshot(lifecycle=False)
    strict = OpportunityGate.evaluate(adapt_v2_snapshot(supplied))

    result = evaluate_v2_snapshot(supplied)

    assert result.decision_lane is DecisionLane.ORACLE_DISCOVERY
    assert result.decision == strict.decision
    assert result.rejection_reasons == strict.rejection_reasons
    assert result.neutral_evidence == ("spot_volume", "spot_vwap")


def test_planner_maximum_entry_marks_overextended():
    supplied = snapshot()
    trigger = StrategyTrigger(
        source=TriggerSource.VOB_BREAKOUT,
        direction=GateDecision.CALL,
        candle_timestamp=datetime.fromisoformat(BOUNDARY),
        current_entry=110,
        maximum_entry=100,
    )

    result = StrategyTriggeredPolicy.evaluate(
        supplied, adapt_v2_snapshot(supplied), trigger
    )

    assert result.entry_state is EntryState.OVEREXTENDED
    assert result.decision is GateDecision.NO_TRADE
    assert "PLANNER_MAXIMUM_ENTRY_EXCEEDED" in result.rejection_reasons


def test_moderate_ose_is_available_support_and_spot_volume_is_expected_na():
    result = evaluate_v2_snapshot(snapshot())
    ose = next(
        row for row in result.component_scores if row.component == "ose_context"
    )
    volume = next(
        row for row in result.component_scores if row.component == "spot_volume"
    )

    assert ose.disposition == "ALIGNED"
    assert ose.observed == "MODERATE_SUPPORT"
    assert volume.disposition == "NOT_APPLICABLE"


def test_stale_snapshot_fails_closed():
    supplied = snapshot()
    supplied["polling"]["snapshot_status"] = "STALE"

    result = evaluate_v2_snapshot(supplied)

    assert result.decision is GateDecision.NO_TRADE
    assert result.entry_state is EntryState.WAIT_FOR_RETEST
    assert "SNAPSHOT_NOT_FRESH" in result.rejection_reasons


def test_competing_call_put_candidates_never_accepts_two():
    supplied = snapshot()
    input_snapshot = adapt_v2_snapshot(supplied)
    timestamp = datetime.fromisoformat(BOUNDARY)
    result = StrategyTriggeredPolicy.choose(
        supplied,
        input_snapshot,
        (
            StrategyTrigger(
                TriggerSource.VOB_BREAKOUT,
                GateDecision.CALL,
                timestamp,
                identity="call",
            ),
            StrategyTrigger(
                TriggerSource.BREAKOUT,
                GateDecision.PUT,
                timestamp,
                identity="put",
            ),
        ),
    )

    assert result.decision in {
        GateDecision.CALL,
        GateDecision.PUT,
        GateDecision.NO_TRADE,
    }
    assert not isinstance(result.decision, tuple)


def test_discovery_fixture_decision_is_unchanged_without_trigger():
    supplied = snapshot(lifecycle=False)
    supplied["feeds"]["strategy_lab"]["data"]["execution"]["nifty_vob"][
        "strongest_confluence"
    ] = {"bullish": {"side": "BULLISH"}}
    expected = OpportunityGate.evaluate(adapt_v2_snapshot(deepcopy(supplied)))

    actual = evaluate_v2_snapshot(supplied)

    assert actual.decision == expected.decision
    assert actual.evidence_quality_score == expected.evidence_quality_score
    assert actual.component_scores == expected.component_scores


def test_trigger_extraction_requires_current_completed_lifecycle():
    supplied = snapshot()
    triggers = strategy_triggers_from_v2(supplied)
    assert len(triggers) == 1
    assert triggers[0].source is TriggerSource.VOB_BREAKOUT

    supplied["feeds"]["strategy_lab"]["data"]["execution"]["nifty_vob"][
        "timeframes"
    ]["5m"]["recently_broken"][0]["source_candle_timestamp"] = (
        "2026-07-27T09:55:00+05:30"
    )
    assert strategy_triggers_from_v2(supplied) == ()

    supplied = snapshot()
    zone = supplied["feeds"]["strategy_lab"]["data"]["execution"][
        "nifty_vob"
    ]["timeframes"]["5m"]["recently_broken"][0]
    zone["broken_at"] = "2026-07-27T09:55:00+05:30"
    zone["last_tested_time"] = BOUNDARY
    triggers = strategy_triggers_from_v2(supplied)
    assert len(triggers) == 1
    assert triggers[0].source is TriggerSource.VOB_RETEST
    assert triggers[0].acceptance_confirmed is False
