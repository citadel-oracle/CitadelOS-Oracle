"""Focused contracts for advisory-only ARGUS Tactical Edge."""

from __future__ import annotations

from datetime import datetime, timedelta
import importlib
import json
from zoneinfo import ZoneInfo

import pytest

from src.argus.prime import ArgusPrimeProjection
from src.argus.tactical_edge import ArgusTacticalEdgeEngine
from src.argus.session_recorder import (
    ArgusSessionRecorder,
    ArgusSessionRecorderError,
)
from src.argus.tactical_store import ArgusTacticalStore


IST = ZoneInfo("Asia/Kolkata")
pytestmark = pytest.mark.unit


def leg(side: str, index: int, *, bullish: bool = True):
    price_change = (2.0 + index / 10) * (1 if bullish else -1)
    oi_change = (900 + index * 50) * (1 if bullish else -1)
    activity = (
        f"{'CALL' if side == 'CE' else 'PUT'}_BUYING"
        if bullish
        else f"{'CALL' if side == 'CE' else 'PUT'}_WRITING"
    )
    return {
        "security_id": 63000 + index + (0 if side == "CE" else 100),
        "ltp": 170.0 + index,
        "previous_close": 168.0,
        "price_change": price_change,
        "day_price_change": price_change,
        "intraday_price_change": price_change,
        "oi": 12_000 + index * 500,
        "previous_oi": 11_000 + index * 450,
        "change_oi": oi_change,
        "day_change_oi": oi_change,
        "intraday_change_oi": oi_change,
        "baseline_oi": 11_100,
        "baseline_ltp": 168.0,
        "volume": 100_000 + index * 4_000,
        "iv": 14.0 + index / 10,
        "top_ask_price": 170.1,
        "top_ask_quantity": 900,
        "top_bid_price": 170.0,
        "top_bid_quantity": 1100,
        "activity": activity,
        "positioning": "LONG_BUILDUP" if bullish else "SHORT_BUILDUP",
    }


def argus(now: datetime, *, fresh: bool = True, missing_iv: bool = False):
    rows = []
    for index, strike in enumerate(range(23700, 24400, 100)):
        ce = leg("CE", index, bullish=True)
        pe = leg("PE", index, bullish=False)
        if missing_iv:
            ce["iv"] = pe["iv"] = None
        rows.append(
            {
                "strike": float(strike),
                "ce_moneyness": "ATM",
                "pe_moneyness": "ATM",
                "ce": ce,
                "pe": pe,
            }
        )
    return {
        "status": "available" if fresh else "stale",
        "freshness": "fresh" if fresh else "stale",
        "cache": {"hit": False, "age_seconds": 0, "ttl_seconds": 3},
        "data": {
            "underlying": {
                "symbol": "NIFTY",
                "security_id": 13,
                "segment": "IDX_I",
                "ltp": 24002.0,
                "expiry": "2026-07-28",
                "atm_strike": 24000.0,
                "fetched_at": now.isoformat(),
                "market_state": "OPEN" if fresh else "CLOSED",
                "session_name": "REGULAR",
                "trading_date": now.date().isoformat(),
                "baseline_timestamp": now.replace(hour=9, minute=15).isoformat(),
                "baseline_status": "AVAILABLE",
            },
            "totals": {
                "day_ce_change_oi": 9_000,
                "day_pe_change_oi": -6_000,
                "intraday_ce_change_oi": 7_000,
                "intraday_pe_change_oi": -5_000,
            },
            "atm_window": rows,
            "walls": {
                "highest_ce_oi": {"strike": 24200.0, "value": 15_000},
                "highest_pe_oi": {"strike": 23800.0, "value": 14_000},
            },
            "dominance": {},
            "verdict": {},
            "missing_fields": [],
        },
    }


def ose(now: datetime, *, live: bool = True):
    def contract(side, strike, security_id):
        return {
            "contract": {
                "security_id": str(security_id),
                "strike": strike,
                "expiry": "2026-07-28",
                "trading_symbol": f"NIFTY 28 JUL {strike} {side}",
            },
            "premium": 170.0,
            "vob": {"state": "BULLISH", "evaluated_through": now.isoformat()},
            "trend": {"state": "BULLISH", "evaluated_through": now.isoformat()},
            "composite": {"label": "BULLISH ALIGNMENT"},
            "structures": {
                "3m": {"state": "BULLISH", "completed_bucket": True},
                "5m": {
                    "state": "BULLISH",
                    "completed_bucket": True,
                    "supply_break": True,
                    "demand_break": False,
                    "bullish_retest": True,
                    "bearish_retest": False,
                },
            },
            "quality": {"data_gap_count": 0, "freshness": "FRESH"},
        }

    return {
        "status": "LIVE" if live else "STALE",
        "symbol": "NIFTY",
        "calculated_at": now.isoformat(),
        "canonical_digest": f"digest-{now.isoformat()}",
        "anchor": 24000,
        "expiry": "2026-07-28",
        "contracts": {
            "CE": contract("CE", 23900, 63935),
            "PE": contract("PE", 24100, 63944),
        },
    }


def engine(tmp_path, *, contract_technicals_provider=None):
    return ArgusTacticalEdgeEngine(
        ArgusTacticalStore(tmp_path / "tactical.json"),
        clock=lambda: "2026-07-23T10:00:01+05:30",
        contract_technicals_provider=contract_technicals_provider,
    )


def test_pure_projection_exposes_required_engines_and_zero_influence(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    result = engine(tmp_path).evaluate(argus(now), ose(now))
    assert result["status"] == "LIVE"
    assert len(result["pressure"]["strikes"]) == 7
    assert result["breadth"]["sample_size"] == 7
    assert result["contract_selection"]["reason"] == "EXISTING_OSE_SAME_EXPIRY_100_POINT_ITM_PAIR"
    assert result["gamma"]["status"] == "UNAVAILABLE"
    assert result["execution_influence"] == "ZERO"
    assert result["strategy_influence"] == "ZERO"
    assert result["order_influence"] == "ZERO"
    assert result["paper_only"] is True
    assert result["broker_submission"] is False
    assert result["decision"]["win_probability"] is None
    assert result["decision"]["evidence_quality_label"] == "Data Quality"
    assert result["decision"]["state"] == "READY"
    assert set(result["quality"]) == {
        "data_quality",
        "evidence_agreement",
        "signal_stability",
        "actionability",
    }
    assert result["why"]["approximated"] == []


def test_gamma_unavailable_does_not_block_standard_directional(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    result = engine(tmp_path).evaluate(argus(now), ose(now))
    assert result["setups"]["GAMMA_BLAST"]["status"] == "UNAVAILABLE"
    assert result["setups"]["GAMMA_BLAST"]["normal_trade_gate"] is False
    assert result["setups"]["STANDARD_DIRECTIONAL"]["status"] == "AVAILABLE"
    assert result["setups"]["HIGH_CONVICTION"]["status"] == "AVAILABLE"
    assert result["setups"]["HIGH_CONVICTION"]["qualified"] is True


def test_missing_iv_is_truthfully_unavailable_without_fabrication(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    result = engine(tmp_path).evaluate(argus(now, missing_iv=True), ose(now))
    assert result["iv_intelligence"]["status"] == "UNAVAILABLE"
    assert result["iv_intelligence"]["direction"] == "UNAVAILABLE"
    assert "GAMMA" in result["why"]["unavailable"]
    assert (
        result["why"]["unavailable_details"]["GAMMA"]
        == "AUTHORITATIVE_DIRECT_GREEKS_UNAVAILABLE"
    )


def test_missing_native_delta_and_iv_are_excluded_from_contract_rank(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    missing = argus(now, missing_iv=True)
    without_greeks = engine(tmp_path / "without").evaluate(missing, ose(now))
    candidate = next(
        item for item in without_greeks["contract_selection"]["all_candidate_ranks"]
        if item["status"] == "CANDIDATE"
    )
    assert candidate["delta"] is None
    assert candidate["iv"] is None
    assert candidate["score_breakdown"]["delta_suitability"]["contribution"] is None
    assert candidate["score_breakdown"]["iv_risk"]["contribution"] is None
    assert candidate["ranking_policy"] == "MISSING_GREEKS_EXCLUDED_NO_RENORMALIZATION"
    assert {"NATIVE_DELTA", "NATIVE_IV"} <= set(candidate["unavailable_evidence"])

    with_greeks = argus(now)
    for row in with_greeks["data"]["atm_window"]:
        row["ce"].update({"delta": 0.50, "iv": 14.0})
        row["pe"].update({"delta": -0.50, "iv": 14.0})
    ranked = engine(tmp_path / "with").evaluate(with_greeks, ose(now))
    ranked_candidate = next(
        item for item in ranked["contract_selection"]["all_candidate_ranks"]
        if item["trading_symbol"] == candidate["trading_symbol"]
    )
    assert ranked_candidate["contract_score"] != candidate["contract_score"]


@pytest.mark.parametrize(
    ("side", "positioning", "expected"),
    [
        ("CE", "LONG_BUILDUP", "CALL"),
        ("CE", "LONG_UNWINDING", "PUT"),
        ("CE", "SHORT_BUILDUP", "PUT"),
        ("CE", "SHORT_COVERING", "CALL"),
        ("PE", "LONG_BUILDUP", "PUT"),
        ("PE", "LONG_UNWINDING", "CALL"),
        ("PE", "SHORT_BUILDUP", "CALL"),
        ("PE", "SHORT_COVERING", "PUT"),
    ],
)
def test_previous_oi_ce_pe_quadrants_are_explicit(side, positioning, expected):
    direction, evidence = ArgusTacticalEdgeEngine._previous_oi_direction(
        [{"strike": 24000, side.lower(): {"positioning": positioning}}]
    )
    assert direction == expected
    assert evidence == [{"side": side, "positioning": positioning, "direction": expected}]


def test_previous_oi_requires_scope_time_and_session_lineage(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    service = engine(tmp_path)
    first = service.evaluate(argus(now), ose(now))
    assert first["previous_oi"]["status"] == "UNAVAILABLE"
    assert first["previous_oi"]["reason"] == "PREVIOUS_OI_HISTORY_UNAVAILABLE"

    later = service.evaluate(argus(now + timedelta(minutes=1)), ose(now + timedelta(minutes=1)))
    assert later["previous_oi"]["status"] == "AVAILABLE"
    assert later["previous_oi"]["direction"] in {"CALL", "PUT", "BALANCED"}

    invalid_history = dict(service.store.history()[-1])
    invalid_history["expiry"] = "2026-08-04"
    mismatch = service._previous_oi(argus(now + timedelta(minutes=2))["data"], [], invalid_history)
    assert mismatch["status"] == "UNAVAILABLE"
    assert mismatch["reason"] == "PREVIOUS_OI_EXPIRY_MISMATCH"

    missing_scope = dict(service.store.history()[-1])
    missing_scope.pop("strike_scope")
    unavailable_scope = service._previous_oi(
        argus(now + timedelta(minutes=2))["data"], [], missing_scope
    )
    assert unavailable_scope["status"] == "UNAVAILABLE"
    assert unavailable_scope["reason"] == "PREVIOUS_OI_STRIKE_SCOPE_UNAVAILABLE"

    mismatch_scope = dict(service.store.history()[-1])
    mismatch_scope["strike_scope"] = [24000.0]
    mismatched_scope = service._previous_oi(
        argus(now + timedelta(minutes=2))["data"], [], mismatch_scope
    )
    assert mismatched_scope["status"] == "UNAVAILABLE"
    assert mismatched_scope["reason"] == "PREVIOUS_OI_STRIKE_SCOPE_MISMATCH"


def test_premium_attribution_keeps_unobserved_history_and_greeks_unavailable(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    result = engine(tmp_path).evaluate(argus(now), ose(now))
    premium = result["premium_attribution"]

    assert premium["greek_attribution"] == "UNAVAILABLE"
    assert premium["unavailable"] == [
        "OPTION_PREMIUM_HISTORY_UNAVAILABLE",
        "GREEK_MOVE_ATTRIBUTION_UNAVAILABLE",
    ]
    for side in ("CE", "PE"):
        assert premium[side]["stretch_score"] is None
        assert premium[side]["stretch_state"] == "UNAVAILABLE"
        assert premium[side]["vwap_deviation_pct"] is None
        assert premium[side]["rolling_z_score"] is None
        assert premium[side]["iv_contribution"] is None
        assert premium[side]["attribution_status"] == "UNAVAILABLE"


def test_unavailable_prime_components_are_not_neutral_imputed(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    prime = engine(tmp_path).evaluate(argus(now), ose(now))["argus_prime"]

    for component in ("futures_confirmation", "gamma_regime"):
        item = prime["score_breakdown"][component]
        assert item["availability"] == "UNAVAILABLE"
        assert item["raw_score"] is None
        assert item["contribution"] is None
        assert item["scored"] is False
        assert item["neutral_imputation"] is False
    assert "FUTURES_CONFIRMATION_UNAVAILABLE" in prime["warnings"]

    for outcome in ("call_edge", "put_edge", "big_move"):
        futures = prime["outcome_engines"][outcome]["components"]["futures"]
        assert futures["score"] is None
        assert futures["availability"] == "UNAVAILABLE"
        assert futures["scored"] is False
    premium = prime["outcome_engines"]["decay_risk"]["components"][
        "premium_non_response"
    ]
    assert premium["score"] is None
    assert premium["availability"] == "UNAVAILABLE"
    assert premium["scored"] is False


def test_tactical_summary_never_claims_unavailable_flows_agree():
    summary = ArgusPrimeProjection._tactical_summary(
        direction="CALL",
        smart_flow={"label": "UNAVAILABLE"},
        wall={},
        blast={"state": "UNAVAILABLE"},
        reversal_score=0.0,
        live_pcr={},
        best_strike_stack={
            "direction": "CALL",
            "state": "BULLISH STACK",
            "primary_flow": {"label": "UNAVAILABLE"},
            "defence_flow": {"label": "UNAVAILABLE"},
        },
    )

    assert summary["reasons"][0] == (
        "Probable flow: insufficient independent leg evidence"
    )
    assert "agree" not in summary["reasons"][0]


def test_tactical_source_time_lineage_never_relabels_receipt_as_provider_event(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    projection = argus(now)
    underlying = projection["data"]["underlying"]
    underlying.update(
        {
            "source_event_time": None,
            "receipt_timestamp": now.isoformat(),
            "timestamp_semantics": "RECEIPT_TIME_NO_PROVIDER_EVENT_TIME",
        }
    )

    result = engine(tmp_path).evaluate(projection, ose(now))
    assert result["source_event_time"] is None
    assert result["receipt_timestamp"] == now.isoformat()
    assert result["timestamp_semantics"] == "RECEIPT_TIME_NO_PROVIDER_EVENT_TIME"
    truth = result["argus_prime"]["data_truth"]
    assert truth["source_event_time"] is None
    assert truth["receipt_timestamp"] == now.isoformat()
    assert truth["freshness_basis"] == "SOURCE_EVENT_TIME_UNAVAILABLE"
    assert truth["age_seconds"] is None
    assert truth["receipt_age_seconds"] is not None


def test_prime_effective_weight_policy_is_explicit_and_deterministic(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    first = engine(tmp_path / "a").evaluate(argus(now, missing_iv=True), ose(now))["argus_prime"]
    second = engine(tmp_path / "b").evaluate(argus(now, missing_iv=True), ose(now))["argus_prime"]
    assert first["normalization_policy"] == "AVAILABLE_COMPONENT_WEIGHT_RENORMALIZATION_V1"
    assert first["effective_weight"] == second["effective_weight"]
    assert first["raw_score"] == second["raw_score"]
    assert 0.0 <= first["raw_score"] <= 100.0
    for name in first["unavailable_components"]:
        assert first["score_breakdown"][name]["contribution"] is None


def test_non_finite_inputs_remain_unavailable(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    projection = argus(now)
    projection["data"]["atm_window"][0]["ce"]["oi"] = float("inf")
    result = engine(tmp_path).evaluate(projection, ose(now))
    assert (
        result["pressure"]["strikes"][0]["CE"]["components"]["open_interest"]
        is None
    )


def test_activity_label_does_not_double_count_pressure_inputs(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    first_projection = argus(now)
    second_projection = argus(now)
    second_projection["data"]["atm_window"][0]["ce"]["activity"] = "CALL_WRITING"
    first = engine(tmp_path / "first").evaluate(first_projection, ose(now))
    second = engine(tmp_path / "second").evaluate(second_projection, ose(now))
    assert (
        first["pressure"]["strikes"][0]["CE"]["score"]
        == second["pressure"]["strikes"][0]["CE"]["score"]
    )


def test_argus_and_ose_symbol_context_must_match(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    projection = argus(now)
    projection["data"]["underlying"]["symbol"] = "BANKNIFTY"
    result = engine(tmp_path).evaluate(projection, ose(now))
    assert result["contract_selection"]["status"] == "UNAVAILABLE"
    assert result["contract_selection"]["reason"] == "ARGUS_OSE_CONTEXT_MISMATCH"
    assert result["setups"]["STANDARD_DIRECTIONAL"]["status"] == "UNAVAILABLE"


def test_disagreement_is_scoring_only_for_high_conviction(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    projection = ose(now)
    projection["contracts"]["CE"]["composite"]["label"] = "BEARISH ALIGNMENT"
    result = engine(tmp_path).evaluate(argus(now), projection)
    high = result["setups"]["HIGH_CONVICTION"]
    assert high["status"] == "AVAILABLE"
    assert high["qualified"] is False
    assert high["mandatory_failures"] == []
    assert "PRESSURE_BREADTH_OSE_NOT_ALIGNED" in high["scoring_misses"]


def test_ce_pe_pressure_is_symmetric_for_symmetric_inputs(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    projection = argus(now)
    for row in projection["data"]["atm_window"]:
        mirrored = dict(row["ce"])
        mirrored["security_id"] = row["pe"]["security_id"]
        mirrored["activity"] = "NEUTRAL"
        row["ce"]["activity"] = "NEUTRAL"
        row["pe"] = mirrored
    result = engine(tmp_path).evaluate(projection, ose(now))
    assert result["pressure"]["call_score"] == result["pressure"]["put_score"]
    assert result["pressure"]["direction"] == "BALANCED"
    assert result["continuation_reversal"]["raw_state"] == "BALANCED"
    assert result["quality"]["evidence_agreement"]["score"] == 0.0
    assert result["entry_lifecycle"]["state"] == "WAIT"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (-18.0, ("CALL", "STRONG_CALL_PRESSURE")),
        (-17.99, ("CALL", "CALL_PRESSURE")),
        (-7.0, ("BALANCED", "NO_CLEAN_EDGE")),
        (7.0, ("BALANCED", "NO_CLEAN_EDGE")),
        (7.01, ("PUT", "PUT_PRESSURE")),
        (18.0, ("PUT", "STRONG_PUT_PRESSURE")),
    ],
)
def test_pressure_threshold_boundaries_use_canonical_config(value, expected):
    assert ArgusTacticalEdgeEngine._classify_pressure_imbalance(value) == expected


def test_argus_prime_hold_contract_is_complete_and_advisory(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    projection = argus(now)
    for row in projection["data"]["atm_window"]:
        mirrored = dict(row["ce"])
        mirrored["security_id"] = row["pe"]["security_id"]
        mirrored["activity"] = "NEUTRAL"
        mirrored["gamma"] = 0.001
        mirrored["delta"] = -0.5
        row["ce"]["activity"] = "NEUTRAL"
        row["ce"]["gamma"] = 0.001
        row["ce"]["delta"] = 0.5
        row["pe"] = mirrored
    result = engine(tmp_path).evaluate(projection, ose(now))
    prime = result["argus_prime"]
    assert prime["direction"] == "HOLD"
    assert prime["action"] == "HOLD"
    assert prime["recommended_contract"] is None
    assert prime["argus_prime_score"] <= 59
    assert prime["futures_confirmation"]["status"] == "UNAVAILABLE"
    assert prime["execution_influence"] == "ZERO"
    assert prime["paper_only"] is True
    assert prime["live_trading_enabled"] is False
    assert prime["broker_submission"] is False
    assert prime["full_evidence"]["score_is_probability"] is False


def test_argus_prime_call_put_hold_direction_is_symmetric(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    call_engine = engine(tmp_path / "call")
    put_engine = engine(tmp_path / "put")
    for offset in range(3):
        timestamp = now + timedelta(seconds=offset * 3)
        call_result = call_engine.evaluate(
            argus(timestamp), ose(timestamp)
        )["argus_prime"]
        put_projection = argus(timestamp)
        for index, row in enumerate(put_projection["data"]["atm_window"]):
            row["ce"] = leg("CE", index, bullish=False)
            row["pe"] = leg("PE", index, bullish=True)
        put_result = put_engine.evaluate(
            put_projection, ose(timestamp)
        )["argus_prime"]
    assert call_result["direction"] == "CALL"
    assert put_result["direction"] == "PUT"
    assert call_result["smart_money_flow"]["label"] == "BULLISH"
    assert put_result["smart_money_flow"]["label"] == "BEARISH"


def test_argus_prime_hero_direction_requires_persistent_distinct_snapshots(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    service = engine(tmp_path)
    observed = []
    for offset in range(3):
        timestamp = now + timedelta(seconds=offset * 3)
        prime = service.evaluate(
            argus(timestamp), ose(timestamp)
        )["argus_prime"]
        observed.append(
            (
                prime["raw_direction"],
                prime["direction"],
                prime["stability"]["transition"],
            )
        )
    assert observed == [
        ("CALL", "HOLD", "SOFT_CHANGE_PENDING"),
        ("CALL", "HOLD", "SOFT_CHANGE_PENDING"),
        ("CALL", "CALL", "HARD_PERSISTENCE_CONFIRMED"),
    ]


def test_argus_prime_hero_direction_confirms_after_ten_seconds(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    service = engine(tmp_path)
    first = service.evaluate(argus(now), ose(now))["argus_prime"]
    second = service.evaluate(
        argus(now + timedelta(seconds=10)),
        ose(now + timedelta(seconds=10)),
    )["argus_prime"]
    assert first["direction"] == "HOLD"
    assert second["direction"] == "CALL"
    assert second["stability"]["transition"] == "HARD_PERSISTENCE_CONFIRMED"


def test_argus_prime_hero_ignores_one_snapshot_direction_noise(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    service = engine(tmp_path)
    for offset in range(3):
        timestamp = now + timedelta(seconds=offset * 3)
        stable = service.evaluate(
            argus(timestamp), ose(timestamp)
        )["argus_prime"]
    assert stable["direction"] == "CALL"

    noisy = argus(now + timedelta(seconds=9))
    for row in noisy["data"]["atm_window"]:
        mirrored = dict(row["ce"])
        mirrored["security_id"] = row["pe"]["security_id"]
        mirrored["activity"] = "NEUTRAL"
        row["ce"]["activity"] = "NEUTRAL"
        row["pe"] = mirrored
    softened = service.evaluate(
        noisy, ose(now + timedelta(seconds=9))
    )["argus_prime"]
    assert softened["raw_direction"] == "HOLD"
    assert softened["direction"] == "CALL"
    assert softened["stability"]["transition"] == "SOFT_CHANGE_PENDING"


def test_argus_prime_persists_stability_and_fast_read_metadata(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    service = engine(tmp_path)
    for offset in range(3):
        timestamp = now + timedelta(seconds=offset * 3)
        prime = service.evaluate(
            argus(timestamp), ose(timestamp)
        )["argus_prime"]
    restarted = engine(tmp_path)
    later = now + timedelta(seconds=12)
    restored = restarted.evaluate(argus(later), ose(later))["argus_prime"]
    assert restored["direction"] == "CALL"
    assert restored["stability"]["confirmed_direction"] == "CALL"
    assert restored["retest_status"] in {
        "RETEST_ACTIVE",
        "RETEST_CONFIRMED",
        "WAIT_RETEST",
    }
    assert restored["trigger"].startswith(("BUY CE", "WAIT —"))
    assert restored["invalidation_text"].startswith("INVALID ")
    record = restarted.store.history()[-1]
    assert record["prime_direction"] == "CALL"
    assert "prime_pending_direction" in record


def test_argus_full_session_recorder_is_restart_and_duplicate_safe(tmp_path):
    now = datetime(2026, 7, 29, 10, 0, tzinfo=IST)
    path = tmp_path / "session"
    service = engine(tmp_path / "runtime")
    service.recorder = ArgusSessionRecorder(path)
    projection = argus(now)
    first = service.evaluate(projection, ose(now))
    assert service.evaluate(projection, ose(now)) == first

    session_path = path / "2026-07-29.jsonl"
    records = [
        json.loads(line)
        for line in session_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 1
    record = records[0]
    assert record["raw_scores"]["hero"] is not None
    assert record["smoothed_scores"]["hero"] is not None
    assert record["displayed_state"]["direction"] in {"CALL", "PUT", "HOLD"}
    assert len(record["option_chain_evidence"]) == 7
    assert set(record["option_chain_evidence"][0]) == {"strike", "CE", "PE"}
    assert "futures_evidence" in record
    assert "flow_evidence" in record
    assert "wall_evidence" in record
    assert "gamma_evidence" in record
    assert "recommended_contract" in record
    assert record["trigger"]
    assert record["invalidation"]
    assert record["execution_influence"] == "ZERO"

    restarted = ArgusSessionRecorder(path)
    assert restarted.append(
        projection=first,
        rows=projection["data"]["atm_window"],
        source=projection["data"],
    ) is False
    assert len(session_path.read_text(encoding="utf-8").splitlines()) == 1


def test_argus_full_session_recorder_fails_closed_on_corruption(tmp_path):
    root = tmp_path / "session"
    root.mkdir()
    (root / "2026-07-29.jsonl").write_text("{not-json}\n", encoding="utf-8")
    recorder = ArgusSessionRecorder(root)
    with pytest.raises(
        ArgusSessionRecorderError,
        match="ARGUS_SESSION_RECORD_CORRUPT",
    ):
        recorder._seen_ids("2026-07-29")


def test_argus_prime_uses_direct_dhan_greeks_as_labelled_proxy(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    projection = argus(now)
    for index, row in enumerate(projection["data"]["atm_window"]):
        row["ce"].update(
            {"gamma": 0.001 + index * 0.0001, "delta": 0.55, "theta": -8.0, "vega": 10.0}
        )
        row["pe"].update(
            {"gamma": 0.001 + index * 0.0001, "delta": -0.45, "theta": -8.0, "vega": 10.0}
        )
    prime = engine(tmp_path).evaluate(projection, ose(now))["argus_prime"]
    gamma = prime["gamma_regime"]
    assert gamma["status"] == "AVAILABLE"
    assert gamma["proxy"] is True
    assert gamma["dealer_ownership_claimed"] is False
    assert gamma["direct_greeks_count"] == 14
    assert prime["full_evidence"]["field_audit"]["fields"]["gamma"] == "USED_AS_PROXY"


def test_argus_prime_high_oi_alone_cannot_trigger_blast(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    projection = argus(now)
    for row in projection["data"]["atm_window"]:
        row["ce"]["oi"] = row["pe"]["oi"] = 100_000_000
        row["ce"]["gamma"] = row["pe"]["gamma"] = None
    prime = engine(tmp_path).evaluate(projection, ose(now))["argus_prime"]
    blast = prime["expiry_gamma_blast"]
    assert blast["high_oi_alone_sufficient"] is False
    assert blast["state"] not in {"CONFIRMED", "ACTIVE"}


def test_argus_prime_stale_source_holds_action(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    tactical = engine(tmp_path)
    tactical.evaluate(argus(now), ose(now))
    stale = tactical.evaluate(argus(now + timedelta(seconds=3), fresh=False), ose(now))
    assert stale["argus_prime"]["status"] == "STALE"
    assert stale["argus_prime"]["action"] == "HOLD"
    assert stale["argus_prime"]["hero_state"] == (
        "MARKET CLOSED — LAST GOOD SNAPSHOT"
    )
    assert stale["argus_prime"]["display_state"] == "LAST_GOOD"
    assert stale["argus_prime"]["live_pcr"]["freshness"] == "STALE"
    assert stale["argus_prime"]["live_pcr"]["source_timestamp"] == (
        now
    ).isoformat()
    assert stale["argus_prime"]["selected_contract_technicals"]["reason"] == (
        "MARKET_CLOSED_LAST_GOOD"
    )
    assert stale["argus_prime"]["action_card"]["status"] == "LAST GOOD"
    assert "MARKET_CLOSED_LAST_GOOD" in stale["argus_prime"]["hard_blocks"]
    truth = stale["argus_prime"]["data_truth"]
    assert truth["state"] == "LAST_GOOD"
    assert truth["source_event_time"] is None
    assert truth["source_timestamp"] is None
    assert truth["receipt_timestamp"] == stale["receipt_timestamp"]
    assert truth["freshness_timestamp"] is None
    assert truth["freshness_basis"] == "SOURCE_EVENT_TIME_UNAVAILABLE"
    assert truth["formula_version"] == "ARGUS_PRIME_V3_AUDITABLE"
    assert truth["age_seconds"] is None
    assert truth["receipt_age_seconds"] is not None
    assert stale["argus_prime"]["score_breakdown"]
    for item in stale["argus_prime"]["score_breakdown"].values():
        if item["raw_score"] is not None:
            assert item["contribution"] == pytest.approx(
                item["raw_score"] * item["weight"]
            )


def test_weekend_retained_snapshot_is_last_good_never_live(tmp_path):
    friday = datetime(2026, 8, 7, 15, 25, tzinfo=IST)
    saturday = datetime(2026, 8, 8, 10, 0, tzinfo=IST)
    service = ArgusTacticalEdgeEngine(
        ArgusTacticalStore(tmp_path / "tactical.json"),
        clock=lambda: saturday.isoformat(),
    )
    live = argus(friday)
    live["data"]["underlying"].update(
        {
            "source_event_time": friday.isoformat(),
            "receipt_timestamp": (friday + timedelta(seconds=2)).isoformat(),
            "timestamp_semantics": "PROVIDER_EVENT_TIME",
        }
    )
    service.evaluate(live, ose(friday))
    retained = argus(saturday, fresh=False)
    retained["data"]["underlying"].update(
        {
            "market_state": "WEEKEND",
            "source_event_time": friday.isoformat(),
            # A newer refetch receipt must not make Friday source data live.
            "receipt_timestamp": saturday.isoformat(),
            "timestamp_semantics": "PROVIDER_EVENT_TIME",
        }
    )
    result = service.evaluate(retained, ose(friday))
    assert result["status"] == "STALE"
    assert result["argus_prime"]["display_state"] == "LAST_GOOD"
    assert result["argus_prime"]["hero_state"] == "MARKET CLOSED — LAST GOOD SNAPSHOT"
    assert result["argus_prime"]["data_truth"]["source_event_time"] == friday.isoformat()
    assert result["argus_prime"]["data_truth"]["receipt_timestamp"] != saturday.isoformat()


def test_argus_prime_live_feed_stale_is_not_market_closed(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    tactical = engine(tmp_path)
    tactical.evaluate(argus(now), ose(now))
    projection = argus(now + timedelta(seconds=25))
    projection["status"] = "stale"
    projection["freshness"] = "stale"
    stale = tactical.evaluate(projection, ose(now))
    assert stale["argus_prime"]["hero_state"] == (
        "LIVE FEED STALE — ACTION LOCKED"
    )
    assert stale["argus_prime"]["display_state"] == "STALE"
    assert stale["argus_prime"]["action_card"]["status"] == "DATA STALE"
    assert "LIVE_FEED_STALE_ACTION_LOCKED" in stale["argus_prime"]["hard_blocks"]
    assert stale["argus_prime"]["data_truth"]["state"] == "STALE"


@pytest.mark.parametrize(
    "activity",
    [
        "CALL_BUYING",
        "CALL_SHORT_COVERING",
        "CALL_WRITING",
        "CALL_LONG_UNWINDING",
        "PUT_BUYING",
        "PUT_SHORT_COVERING",
        "PUT_WRITING",
        "PUT_LONG_UNWINDING",
    ],
)
def test_argus_prime_probable_flow_preserves_all_price_oi_quadrants(activity):
    timestamp = "2026-07-23T10:00:00+05:30"
    result = ArgusPrimeProjection._probable_flow(
        {
            "activity": activity,
            "price_change": 2,
            "oi_change": 100,
            "volume": 10_000,
        },
        {
            "source_timestamp": timestamp,
            "fetched_at": timestamp,
            "depth_imbalance_percentage": 0,
            "average_price": 100,
            "last_trade_time": timestamp,
        },
        source_timestamp=timestamp,
    )
    assert result["label"] == activity
    assert result["state"] == "LOW_CONFIDENCE"
    assert result["confidence"] <= 49


def test_argus_prime_probable_flow_conflicting_depth_is_amber_not_confirmed():
    timestamp = "2026-07-23T10:00:00+05:30"
    result = ArgusPrimeProjection._probable_flow(
        {
            "activity": "CALL_BUYING",
            "price_change": 2,
            "oi_change": 100,
            "volume": 10_000,
        },
        {
            "source_timestamp": timestamp,
            "fetched_at": timestamp,
            "depth_imbalance_percentage": -45,
            "average_price": 100,
            "last_trade_time": timestamp,
        },
        source_timestamp=timestamp,
    )
    assert result["label"] == "MIXED_CONTRADICTORY"
    assert result["state"] == "CONTRADICTORY"
    assert result["confidence"] < 50


def test_argus_prime_probable_flow_uses_supporting_aggressor_evidence():
    timestamp = "2026-07-23T10:00:00+05:30"
    result = ArgusPrimeProjection._probable_flow(
        {
            "activity": "CALL_BUYING",
            "price_change": 2,
            "oi_change": 100,
            "volume": 10_000,
        },
        {
            "source_timestamp": timestamp,
            "fetched_at": timestamp,
            "depth_imbalance_percentage": 18,
            "average_price": 100,
            "last_trade_time": timestamp,
        },
        source_timestamp=timestamp,
    )
    assert result["state"] == "PROBABLE"
    assert result["evidence"]["five_level_depth_agreement"] is True
    assert result["evidence_coverage"]["available"] >= 5


def test_argus_prime_probable_flow_requires_fresh_timestamp_parity():
    result = ArgusPrimeProjection._probable_flow(
        {
            "activity": "CALL_BUYING",
            "price_change": 2,
            "oi_change": 100,
            "volume": 10_000,
        },
        {
            "source_timestamp": "2026-07-23T10:00:25+05:30",
            "fetched_at": "2026-07-23T10:00:25+05:30",
            "depth_imbalance_percentage": 20,
            "average_price": 100,
            "last_trade_time": "2026-07-23T10:00:25+05:30",
        },
        source_timestamp="2026-07-23T10:00:00+05:30",
    )
    assert result["state"] == "INCONSISTENT"
    assert result["confidence"] == 0


def test_argus_prime_pcr_current_value_survives_missing_change_history():
    timestamp = "2026-07-23T10:00:00+05:30"
    result = ArgusPrimeProjection._live_pcr(
        [], [], timestamp, {"ce_oi": 100, "pe_oi": 117}
    )
    assert result["current_state"] == "AVAILABLE"
    assert result["oi_pcr"] == 1.17
    assert result["change_1m_state"] == "HISTORY_BUILDING"
    assert result["change_5m_state"] == "HISTORY_BUILDING"
    assert result["trend"] == "HISTORY_BUILDING"


def test_argus_prime_pcr_uses_nearest_same_expiry_complete_snapshots():
    current = "2026-07-29T10:05:00+05:30"
    history = [
        {
            "pcr_observation": {
                "timestamp": "2026-07-29T10:04:02+05:30",
                "expiry": "2026-08-04",
                "underlying": "NIFTY",
                "total_call_oi": 100,
                "total_put_oi": 110,
                "pcr": 1.10,
                "snapshot_id": "one-minute",
            }
        },
        {
            "pcr_observation": {
                "timestamp": "2026-07-29T10:00:12+05:30",
                "expiry": "2026-08-04",
                "underlying": "NIFTY",
                "total_call_oi": 100,
                "total_put_oi": 105,
                "pcr": 1.05,
                "snapshot_id": "five-minute",
            }
        },
        {
            "pcr_observation": {
                "timestamp": "2026-07-29T10:04:00+05:30",
                "expiry": "2026-07-28",
                "underlying": "NIFTY",
                "total_call_oi": 100,
                "total_put_oi": 50,
                "pcr": 0.50,
                "snapshot_id": "wrong-expiry",
            }
        },
    ]
    result = ArgusPrimeProjection._live_pcr(
        [],
        history,
        current,
        {"ce_oi": 100, "pe_oi": 117},
        expiry="2026-08-04",
        underlying="NIFTY",
        snapshot_id="current",
    )
    assert result["oi_pcr"] == 1.17
    assert result["change_1m"] == pytest.approx(0.07)
    assert result["change_5m"] == pytest.approx(0.12)
    assert result["trend"] == "RISING"
    assert "volume_pcr" not in result


def test_argus_prime_structural_strike_is_independent_of_atm_and_authorization():
    def leg(flow, load, acceleration, pressure):
        return {
            "probable_flow": flow,
            "load_intensity": load,
            "oi_acceleration": acceleration,
            "pressure_score": pressure,
            "liquidity_score": 80,
            "velocity_arrow": "↑↑",
        }

    spine = [
        {
            "strike": 24200,
            "CE": leg("CALL_BUYING", 100, 183_109, 69.77),
            "PE": leg("PUT_WRITING", 90.3, 227_348, 79.83),
            "wall_strength": "SUPPORT_WALL",
            "wall_condition": "STRENGTHENING",
            "is_probable_magnet": True,
        },
        {
            "strike": 24250,
            "CE": leg("CALL_BUYING", 46.16, 78_624, 53.48),
            "PE": leg("PUT_WRITING", 32.3, 109_885, 48.92),
            "wall_strength": "NONE",
            "wall_condition": "NONE",
        },
    ]
    result = ArgusPrimeProjection._best_strike_stack(
        direction="HOLD",
        recommended=None,
        strike_spine=spine,
        history=[],
        underlying={
            "atm_strike": 24250,
            "ltp": 24238.85,
            "market_state": "CLOSED",
        },
    )
    assert result["strongest_structural_strike"] == 24200
    assert result["atm_observation"] == 24250
    assert result["direction"] == "CALL"
    assert result["state"] == "BULLISH STRUCTURE"
    assert result["structural_strength"]["score"] > 80
    assert result["trade_readiness"]["score"] < result["structural_strength"]["score"]
    assert result["authorized_contract"] is False
    assert "NO_AUTHORIZED_CONTRACT" in result["trade_readiness"]["reasons"]


def test_argus_prime_reversal_zero_and_gamma_wording_are_truthful():
    reversal = ArgusPrimeProjection._reversal_semantics(
        score=0,
        market_state="CLOSED",
        futures={"status": "LAST_GOOD"},
        pressure_price={"status": "AVAILABLE"},
        continuation={"raw_compass": 0},
        source_timestamp="2026-07-29T15:29:30+05:30",
    )
    assert reversal["label"] == "LAST GOOD REVERSAL · 0"
    rows = [
        {
            "strike": 24200,
            "ce": {"gamma": 0.001, "oi": 100},
            "pe": {"gamma": 0.001, "oi": 100},
        },
        {
            "strike": 24250,
            "ce": {"gamma": 0.001, "oi": 100},
            "pe": {"gamma": 0.001, "oi": 100},
        },
        {
            "strike": 24300,
            "ce": {"gamma": 0.001, "oi": 100},
            "pe": {"gamma": 0.001, "oi": 100},
        },
    ]
    gamma = ArgusPrimeProjection._gamma_regime(
        rows, {}, {}, {"state": "WAIT"}, "HOLD"
    )
    assert gamma["state"] == "MOVE_SUPPRESSED"
    assert gamma["technical_state"] == "DAMPING"


def test_argus_prime_output_contract_and_strike_spine(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    result = engine(tmp_path).evaluate(argus(now), ose(now))
    prime = result["argus_prime"]
    required = {
        "argus_prime_score",
        "direction",
        "move_state",
        "entry_style",
        "smart_flow_score",
        "futures_confirmation_score",
        "pressure_price_state",
        "wall_outcome_score",
        "reversal_score",
        "gamma_regime_score",
        "gamma_blast_score",
        "recommended_contract",
        "trigger",
        "invalidation",
        "why",
        "freshness",
        "snapshot_id",
    }
    assert required <= set(prime)
    assert len(prime["strike_spine"]) == 7
    assert set(prime["score_weights"]) == {
        "smart_flow",
        "futures_confirmation",
        "pressure_to_price",
        "wall_outcome",
        "reversal",
        "gamma_regime",
        "gamma_blast",
    }
    assert sum(prime["score_weights"].values()) == pytest.approx(1.0)
    presentation = prime["canonical_presentation"]
    assert len(presentation["full_spine"]) == 7
    assert any(row["ce_load"] is not None for row in presentation["full_spine"])
    assert any(row["pe_load"] is not None for row in presentation["full_spine"])


def test_argus_prime_exposes_live_pcr_stack_and_selected_contract_technicals(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    provider_calls = []

    def technicals(candidate, observed_at):
        provider_calls.append((candidate["side"], candidate["security_id"], observed_at))
        return {
            "status": "AVAILABLE",
            "security_id": str(candidate["security_id"]),
            "side": candidate["side"],
            "current_premium": 171.0,
            "completed_5m_timestamp": now.isoformat(),
            "completed_3m_timestamp": now.isoformat(),
            "pullback_state": "PULLBACK_ACTIVE",
            "trend": {
                "ema_21": 169.0,
                "ema_50": 162.0,
                "supertrend_value": 160.0,
                "ema_21_zone": {"low": 168.2, "high": 169.8},
                "ema_50_zone": {"low": 161.2, "high": 162.8},
                "supertrend_zone": {"low": 159.2, "high": 160.8},
            },
            "vob_3m": {
                "support_buy_zone": {"low": 166.0, "high": 168.0},
                "breakout_trigger": 176.0,
            },
        }

    service = engine(tmp_path, contract_technicals_provider=technicals)
    for offset in range(3):
        timestamp = now + timedelta(seconds=offset * 3)
        projection = argus(timestamp)
        projection["data"]["totals"].update(
            {"ce_oi": 100_000, "pe_oi": 118_000, "pcr": 1.18}
        )
        for row in projection["data"]["atm_window"]:
            for side in ("ce", "pe"):
                row[side]["ltp"] = 90.0
                row[side]["top_bid_price"] = 89.95
                row[side]["top_ask_price"] = 90.05
        prime = service.evaluate(projection, ose(timestamp))["argus_prime"]

    assert prime["direction"] == "CALL"
    assert prime["live_pcr"]["status"] == "AVAILABLE"
    assert prime["live_pcr"]["oi_pcr"] == pytest.approx(1.18)
    assert prime["live_pcr"]["source"] == "ARGUS_DHAN_FULL_CHAIN_TOTALS"
    assert prime["live_pcr"]["direction_is_not_trade_signal"] is True
    assert prime["best_strike_stack"]["strike"] is not None
    stack_contributions = prime["best_strike_stack"]["score_contributions"]
    assert sum(item["weight"] for item in stack_contributions.values()) == pytest.approx(1.0)
    assert prime["best_strike_stack"]["score"] == pytest.approx(
        sum(item["contribution"] for item in stack_contributions.values()),
        abs=0.1,
    )
    readiness = prime["best_strike_stack"]["trade_readiness"]
    assert sum(
        item["weight"] for item in readiness["contributions"].values()
    ) == pytest.approx(1.0)
    assert prime["selected_contract_technicals"]["status"] == "AVAILABLE"
    assert prime["selected_contract_technicals"]["trend"]["ema_21"] == 169.0
    assert prime["selected_contract_technicals"]["invalidation_premium"] == 160.0
    assert prime["selected_contract_technicals"]["next_strength_premium"] == 176.0
    assert prime["selected_contract_technicals"]["zone_width_formula"] == (
        "MAX(2_TICKS,ATR10_X_0.08,TOP_OF_BOOK_SPREAD)_EACH_SIDE"
    )
    assert {call[0] for call in provider_calls} == {"CE", "PE"}
    assert prime["execution_influence"] == "ZERO"
    assert prime["broker_submission"] is False


def test_argus_prime_rejects_technical_levels_from_wrong_contract(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)

    def mismatched(_candidate, _observed_at):
        return {"status": "AVAILABLE", "security_id": "WRONG"}

    service = engine(tmp_path, contract_technicals_provider=mismatched)
    for offset in range(3):
        timestamp = now + timedelta(seconds=offset * 3)
        projection = argus(timestamp)
        for row in projection["data"]["atm_window"]:
            for side in ("ce", "pe"):
                row[side]["ltp"] = 90.0
                row[side]["top_bid_price"] = 89.95
                row[side]["top_ask_price"] = 90.05
        prime = service.evaluate(projection, ose(timestamp))["argus_prime"]

    assert prime["selected_contract_technicals"] == {
        "status": "UNAVAILABLE",
        "reason": "SELECTED_CONTRACT_TECHNICAL_ID_MISMATCH",
        "pullback_state": "WAITING_FOR_5M_PULLBACK",
    }


def test_first_snapshot_iv_comparison_resolves_on_later_snapshot(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    service = engine(tmp_path)
    first = service.evaluate(argus(now), ose(now))
    second_argus = argus(now + timedelta(minutes=1))
    for row in second_argus["data"]["atm_window"]:
        row["ce"]["iv"] += 1.0
        row["pe"]["iv"] += 1.0
    second = service.evaluate(
        second_argus, ose(now + timedelta(minutes=1))
    )
    assert first["iv_intelligence"]["prior_snapshot_available"] is False
    assert first["iv_intelligence"]["direction"] == "UNAVAILABLE"
    assert second["iv_intelligence"]["prior_snapshot_available"] is True
    assert second["iv_intelligence"]["direction"] == "RISING"


def test_stale_source_preserves_last_authoritative_projection_but_disables_action(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    service = engine(tmp_path)
    live = service.evaluate(argus(now), ose(now))
    stale = service.evaluate(argus(now + timedelta(minutes=1), fresh=False), ose(now))
    assert stale["calculation_id"] == live["calculation_id"]
    assert stale["status"] == "STALE"
    assert stale["decision"]["action_enabled"] is False
    assert stale["decision"]["gate"] == "UNAVAILABLE"
    assert stale["decision"]["state"] == "WAIT"
    assert stale["quality"]["data_quality"]["status"] == "STALE"
    assert stale["quality"]["actionability"]["score"] == 0.0
    assert stale["continuation_reversal"]["status"] == "STALE"
    assert all(value["status"] == "UNAVAILABLE" for value in stale["setups"].values())


def _regime_projection(
    service,
    now,
    history,
    *,
    direction="CALL",
    breadth_direction="CALL",
    ose_direction="CALL",
    delta=20.0,
):
    selected_side = "CE" if direction == "CALL" else "PE"
    bullish = (
        (selected_side == "CE" and ose_direction == "CALL")
        or (selected_side == "PE" and ose_direction == "PUT")
    )
    projection = ose(now)
    projection["contracts"][selected_side]["composite"]["label"] = (
        "BULLISH ALIGNMENT" if bullish else "BEARISH ALIGNMENT"
    )
    projection["contracts"][selected_side]["structures"]["5m"].update(
        {"supply_break": False, "demand_break": False}
    )
    pressure = {"direction": direction, "delta": delta}
    breadth = {
        "direction": breadth_direction,
        "call_confirming_strikes": 4 if breadth_direction == "CALL" else 1,
        "put_confirming_strikes": 4 if breadth_direction == "PUT" else 1,
    }
    persistence = {
        "direction": direction,
        "consecutive_confirmations": 1,
        "duration_seconds": 0.0,
    }
    selection = service._contract_selection(
        argus(now)["data"]["underlying"], projection
    )
    return service._continuation_reversal(
        pressure,
        breadth,
        persistence,
        {"direction": "STABLE"},
        projection,
        selection,
        history,
        now.isoformat(),
    )


def _regime_record(result, now):
    return {
        "source_timestamp": now.isoformat(),
        "confirmed_regime_state": result["confirmed_state"],
        "confirmed_compass": result["compass"],
        "pending_regime_state": result["pending_state"],
        "pending_regime_count": result["pending_count"],
        "pending_regime_since": result["pending_since"],
    }


def test_boundary_oscillation_does_not_flip_confirmed_state(tmp_path):
    service = engine(tmp_path)
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    history = []
    for index, opposing in enumerate((False, True, False, True, False)):
        timestamp = now + timedelta(seconds=index * 2)
        result = _regime_projection(
            service,
            timestamp,
            history,
            breadth_direction="PUT" if opposing else "CALL",
            ose_direction="PUT" if opposing else "CALL",
        )
        assert result["raw_state"] == ("REVERSAL" if opposing else "CONTINUATION")
        assert result["confirmed_state"] == "BALANCED"
        history.append(_regime_record(result, timestamp))


def test_stable_continuation_confirms_after_three_snapshots(tmp_path):
    service = engine(tmp_path)
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    history = []
    states = []
    for index in range(3):
        timestamp = now + timedelta(seconds=index * 3)
        result = _regime_projection(service, timestamp, history)
        states.append(result["confirmed_state"])
        history.append(_regime_record(result, timestamp))
    assert states == ["BALANCED", "BALANCED", "CONTINUATION"]


def test_stable_state_confirms_after_ten_seconds(tmp_path):
    service = engine(tmp_path)
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    first = _regime_projection(service, now, [])
    history = [_regime_record(first, now)]
    second = _regime_projection(
        service, now + timedelta(seconds=10), history
    )
    assert second["confirmed_state"] == "CONTINUATION"
    assert second["transition_reason"] == "HYSTERESIS_CONFIRMATION_COMPLETE"


def test_stable_reversal_confirms_after_three_snapshots(tmp_path):
    service = engine(tmp_path)
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    history = []
    states = []
    for index in range(3):
        timestamp = now + timedelta(seconds=index * 3)
        result = _regime_projection(
            service,
            timestamp,
            history,
            breadth_direction="PUT",
            ose_direction="PUT",
        )
        states.append(result["confirmed_state"])
        history.append(_regime_record(result, timestamp))
    assert states == ["BALANCED", "BALANCED", "REVERSAL"]


def test_confirmed_regime_uses_separate_exit_hysteresis(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    continuation_history = [
        {
            "confirmed_regime_state": "CONTINUATION",
            "confirmed_compass": 60.0,
        }
    ]
    held_continuation = engine(tmp_path)._stabilize_regime(
        "BALANCED", 20.0, continuation_history, now.isoformat(), False
    )
    exiting_continuation = engine(tmp_path)._stabilize_regime(
        "BALANCED", 14.0, continuation_history, now.isoformat(), False
    )
    assert held_continuation["confirmed_state"] == "CONTINUATION"
    assert held_continuation["pending_state"] is None
    assert exiting_continuation["confirmed_state"] == "CONTINUATION"
    assert exiting_continuation["pending_state"] == "BALANCED"

    reversal_history = [
        {
            "confirmed_regime_state": "REVERSAL",
            "confirmed_compass": -60.0,
        }
    ]
    held_reversal = engine(tmp_path)._stabilize_regime(
        "BALANCED", -20.0, reversal_history, now.isoformat(), False
    )
    exiting_reversal = engine(tmp_path)._stabilize_regime(
        "BALANCED", -14.0, reversal_history, now.isoformat(), False
    )
    assert held_reversal["confirmed_state"] == "REVERSAL"
    assert held_reversal["pending_state"] is None
    assert exiting_reversal["confirmed_state"] == "REVERSAL"
    assert exiting_reversal["pending_state"] == "BALANCED"


def test_extreme_override_requires_every_centralized_condition(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    service = engine(tmp_path)
    projection = ose(now)
    pressure = {"direction": "CALL", "delta": 40.0}
    breadth = {
        "direction": "CALL",
        "call_confirming_strikes": 5,
        "put_confirming_strikes": 0,
    }
    assert service._extreme_break(
        "CONTINUATION", pressure, breadth, projection, "CE", "CALL"
    ) is True
    breadth["call_confirming_strikes"] = 4
    assert service._extreme_break(
        "CONTINUATION", pressure, breadth, projection, "CE", "CALL"
    ) is False
    breadth["call_confirming_strikes"] = 5
    projection["contracts"]["CE"]["structures"]["5m"]["completed_bucket"] = False
    assert service._extreme_break(
        "CONTINUATION", pressure, breadth, projection, "CE", "CALL"
    ) is False


def test_persistence_duration_uses_only_contiguous_history(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    history = [
        {"direction": "CALL", "source_timestamp": (now - timedelta(seconds=30)).isoformat()},
        {"direction": "PUT", "source_timestamp": (now - timedelta(seconds=5)).isoformat()},
        {"direction": "CALL", "source_timestamp": (now - timedelta(seconds=2)).isoformat()},
    ]
    persistence = engine(tmp_path)._persistence("CALL", history, now.isoformat())
    assert persistence["consecutive_confirmations"] == 2
    assert persistence["duration_seconds"] == 2.0


def test_balanced_pressure_forces_balanced_regime(tmp_path):
    service = engine(tmp_path)
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    result = _regime_projection(
        service,
        now,
        [],
        direction="BALANCED",
        breadth_direction="PUT",
        ose_direction="PUT",
        delta=2.0,
    )
    assert result["raw_state"] == "BALANCED"
    assert result["raw_compass"] == 0.0
    assert result["market_direction"] == "BALANCED"
    assert result["regime_character"] == "BALANCED"


def test_contradictory_evidence_is_low_agreement_not_high_quality(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    projection = ose(now)
    projection["contracts"]["CE"]["composite"]["label"] = "BEARISH ALIGNMENT"
    result = engine(tmp_path).evaluate(argus(now), projection)
    assert result["quality"]["data_quality"]["score"] > 90
    assert result["quality"]["evidence_agreement"]["score"] < 70
    assert result["decision"]["actionability"] == 50.0
    assert result["quality"]["actionability"]["status"] == "CONTEXT_ONLY"
    assert result["setups"]["HIGH_CONVICTION"]["qualified"] is False


def test_ce_and_pe_regime_sign_conventions_are_symmetric(tmp_path):
    service = engine(tmp_path)
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    call = _regime_projection(service, now, [], direction="CALL", ose_direction="CALL")
    put = _regime_projection(
        service,
        now,
        [],
        direction="PUT",
        breadth_direction="PUT",
        ose_direction="PUT",
        delta=-20.0,
    )
    assert call["raw_state"] == put["raw_state"] == "CONTINUATION"
    assert call["raw_compass"] == put["raw_compass"]


def test_compass_never_reaches_extreme_without_full_support(tmp_path):
    service = engine(tmp_path)
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    continuation = _regime_projection(service, now, [], delta=20.0)
    reversal = _regime_projection(
        service,
        now,
        [],
        breadth_direction="PUT",
        ose_direction="PUT",
        delta=20.0,
    )
    assert abs(continuation["raw_compass"]) < 100
    assert abs(reversal["raw_compass"]) < 100


def test_restart_safe_exactly_once_persistence(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    first = engine(tmp_path)
    first_result = first.evaluate(argus(now), ose(now))
    first.evaluate(argus(now), ose(now))
    restarted = engine(tmp_path)
    second_result = restarted.evaluate(
        argus(now + timedelta(minutes=1)), ose(now + timedelta(minutes=1))
    )
    history = restarted.store.history()
    assert len(history) == 2
    assert history[0]["calculation_id"] == first_result["calculation_id"]
    assert history[-1]["calculation_id"] == second_result["calculation_id"]
    assert second_result["persistence"]["restart_safe"] is True
    assert second_result["persistence"]["consecutive_confirmations"] >= 2
    assert (
        second_result["continuation_reversal"]["confirmed_state"]
        == first_result["continuation_reversal"]["confirmed_state"]
    )


def test_same_authoritative_snapshot_is_calculated_and_persisted_once(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    service = engine(tmp_path)
    first = service.evaluate(argus(now), ose(now))
    second = service.evaluate(argus(now), ose(now))
    assert first["calculation_id"] == second["calculation_id"]
    assert first == second
    assert len(service.store.history()) == 1


def test_invalid_ose_disables_normal_setups_without_affecting_gamma_rule(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    result = engine(tmp_path).evaluate(argus(now), ose(now, live=False))
    standard = result["setups"]["STANDARD_DIRECTIONAL"]
    assert standard["status"] == "UNAVAILABLE"
    assert "OSE_INPUT_NOT_LIVE" in standard["mandatory_failures"]
    assert result["setups"]["GAMMA_BLAST"]["status"] == "UNAVAILABLE"


def test_entry_hard_invalidation_is_separate_from_evidence_cancellation(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    projection = ose(now)
    projection["contracts"]["CE"]["structures"]["5m"]["state"] = "BEARISH"
    result = engine(tmp_path).evaluate(argus(now), projection)
    entry = result["entry_lifecycle"]
    assert entry["state"] == "INVALIDATED"
    assert entry["hard_invalidation"] is True
    assert entry["evidence_cancelled"] is False


def test_entry_rejection_can_resume_only_from_persisted_authoritative_transition(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    service = engine(tmp_path)
    rejected = ose(now)
    rejected["contracts"]["CE"]["structures"]["5m"].update(
        {"state": "BEARISH", "bearish_retest": True, "bullish_retest": False}
    )
    first = service.evaluate(argus(now), rejected)
    assert first["entry_lifecycle"]["state"] == "REJECTION"

    later = now + timedelta(minutes=1)
    resumed = service.evaluate(argus(later), ose(later))
    assert resumed["entry_lifecycle"]["state"] == "RESUMPTION"
    assert resumed["entry_lifecycle"]["hard_invalidation"] is False


def test_v1_refreshes_canonical_argus_and_v2_reads_warm_cache_only():
    main = importlib.import_module("app.main")
    assert main.v2_integration.providers["argus"] is main.cached_argus_projection
    assert main.argus_oi.__globals__["current_argus_projection"] is main.current_argus_projection


def test_background_argus_fanout_publishes_matching_tactical_projection(monkeypatch):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    main = importlib.import_module("app.main")
    projection = argus(now)
    source_timestamp = projection["data"]["underlying"]["fetched_at"]
    enriched = {
        **projection,
        "data": {
            **projection["data"],
            "argus_market_snapshot": {
                "status": "AVAILABLE",
                "argus_source_timestamp": source_timestamp,
            },
            "futures": {"status": "AVAILABLE"},
        },
    }
    evaluated = []
    edge_published = []

    monkeypatch.setattr(main.option_chart_feed, "ingest", lambda value: None)
    monkeypatch.setattr(main, "_enrich_argus_projection", lambda value, refresh_market: enriched)
    monkeypatch.setattr(main.options_structure_engine, "projection", lambda: ose(now))
    monkeypatch.setattr(
        main.argus_tactical_edge,
        "evaluate",
        lambda argus_value, ose_value: evaluated.append((argus_value, ose_value)),
    )
    monkeypatch.setattr(
        main.argus_edge_lab,
        "evaluate_once",
        lambda value: edge_published.append(value),
    )

    main._argus_cache_fanout(projection)

    assert evaluated == [(enriched, ose(now))]
    assert edge_published == [enriched]


def test_incomplete_cycle_retains_coherent_snapshot_until_next_fresh(monkeypatch):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    second = now + timedelta(seconds=3)
    later = now + timedelta(seconds=6)
    main = importlib.import_module("app.main")
    live = argus(now)
    next_live = argus(second)
    fresh = argus(later)

    def complete(projection):
        source_timestamp = projection["data"]["underlying"]["fetched_at"]
        return {
            **projection,
            "data": {
                **projection["data"],
                "argus_market_snapshot": {
                    "status": "AVAILABLE",
                    "argus_source_timestamp": source_timestamp,
                },
                "futures": {"status": "AVAILABLE"},
            },
        }

    live_enriched = complete(live)
    next_enriched = complete(next_live)
    incomplete = complete(argus(now + timedelta(seconds=4)))
    incomplete["data"].pop("futures")
    fresh_enriched = complete(fresh)

    def tactical(timestamp, snapshot_id, score, pcr, side, security_id):
        return {
            "status": "LIVE",
            "freshness": "FRESH",
            "source_timestamp": timestamp.isoformat(),
            "decision": {"action_enabled": True},
            "argus_prime": {
                "status": "LIVE",
                "freshness": "FRESH",
                "display_state": "LIVE",
                "hero_state": f"BUY {side}",
                "action": side,
                "display_score": score,
                "live_pcr": {"status": "AVAILABLE", "oi_pcr": pcr},
                "recommended_contract": {"security_id": security_id},
                "selected_contract_technicals": {"status": "AVAILABLE"},
                "data_truth": {
                    "source_timestamp": timestamp.isoformat(),
                    "snapshot_id": snapshot_id,
                    "freshness_threshold_seconds": 20.0,
                    "state": "LIVE",
                },
            },
        }

    evaluations = iter(
        [
            tactical(now, "coherent-a", 74, 1.18, "CALL", "123"),
            tactical(second, "coherent-b", 76, 1.20, "CALL", "234"),
            tactical(later, "coherent-c", 81, 1.22, "PUT", "456"),
        ]
    )
    edge_published = []
    monkeypatch.setattr(main.option_chart_feed, "ingest", lambda value: None)
    monkeypatch.setattr(main.options_structure_engine, "projection", lambda: ose(now))
    monkeypatch.setattr(main.argus_tactical_edge, "evaluate", lambda *args: next(evaluations))
    monkeypatch.setattr(
        main.argus_edge_lab,
        "evaluate_once",
        lambda value: edge_published.append(
            value["data"]["tactical_edge"]["argus_prime"]["data_truth"]["snapshot_id"]
        ),
    )
    enriched = iter([live_enriched, next_enriched, incomplete, fresh_enriched])
    monkeypatch.setattr(main, "_enrich_argus_projection", lambda *args, **kwargs: next(enriched))
    monkeypatch.setattr(main, "_argus_coherent_projection", None)

    main._argus_cache_fanout(live)
    first = main.cached_argus_projection("NIFTY")
    main._argus_cache_fanout(next_live)
    second_projection = main.cached_argus_projection("NIFTY")
    main._argus_cache_fanout(incomplete)
    retained = main.cached_argus_projection("NIFTY")
    main._argus_cache_fanout(fresh)
    replaced = main.cached_argus_projection("NIFTY")

    first_prime = first["data"]["tactical_edge"]["argus_prime"]
    retained_tactical = retained["data"]["tactical_edge"]
    retained_prime = retained_tactical["argus_prime"]
    replaced_prime = replaced["data"]["tactical_edge"]["argus_prime"]
    assert first_prime["data_truth"]["snapshot_id"] == "coherent-a"
    assert second_projection["data"]["tactical_edge"]["argus_prime"][
        "data_truth"
    ]["snapshot_id"] == "coherent-b"
    assert retained_prime["data_truth"]["snapshot_id"] == "coherent-b"
    assert retained_prime["display_score"] == 76
    assert retained_prime["live_pcr"]["oi_pcr"] == 1.20
    assert retained_tactical["status"] in {"DEGRADED", "DEGRADED_STALE"}
    assert retained_tactical["freshness"] == "LAST_GOOD"
    assert retained_tactical["missing_components"] == [
        "ARGUS_FUTURES_SNAPSHOT_UNAVAILABLE"
    ]
    assert retained_tactical["decision"]["action_enabled"] is False
    assert retained_prime["recommended_contract"] is None
    assert retained_prime["selected_contract_technicals"]["status"] == "UNAVAILABLE"
    assert replaced_prime["data_truth"]["snapshot_id"] == "coherent-c"
    assert replaced_prime["display_score"] == 81
    assert replaced_prime["live_pcr"]["oi_pcr"] == 1.22
    assert edge_published == [
        "coherent-a",
        "coherent-b",
        "coherent-b",
        "coherent-c",
    ]


def test_v2_rebuild_fails_closed_when_no_coherent_market_snapshot_exists(monkeypatch):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    main = importlib.import_module("app.main")
    monkeypatch.setattr(main, "_argus_coherent_projection", None)
    monkeypatch.setattr(main.argus, "projection", lambda _symbol: argus(now))
    monkeypatch.setattr(
        main.argus_market_snapshot,
        "latest",
        lambda _source_timestamp: None,
    )
    monkeypatch.setattr(main.argus_tactical_edge.store, "latest", lambda: None)

    result = main.cached_argus_projection("NIFTY")

    assert result["status"] == "UNAVAILABLE"
    assert result["data"] == {}
    assert result["reason"] == "ARGUS_COHERENT_PROJECTION_NOT_READY"


def test_v2_cached_argus_never_reads_store_or_market_on_request_path(monkeypatch):
    now = datetime.now(IST)
    main = importlib.import_module("app.main")
    monkeypatch.setattr(main, "_argus_coherent_projection", None)
    monkeypatch.setattr(main.argus, "projection", lambda _symbol: pytest.fail("store fallback"))
    monkeypatch.setattr(main.argus_market_snapshot, "latest", lambda _source_timestamp: pytest.fail("market fallback"))
    monkeypatch.setattr(main.argus_tactical_edge.store, "latest", lambda: pytest.fail("tactical store fallback"))

    result = main.cached_argus_projection("NIFTY")

    assert result == {
        "status": "UNAVAILABLE",
        "reason": "ARGUS_COHERENT_PROJECTION_NOT_READY",
        "data": {},
    }


def test_v1_and_v2_tactical_payloads_have_canonical_parity(tmp_path):
    now = datetime(2026, 7, 23, 10, 0, tzinfo=IST)
    main = importlib.import_module("app.main")
    original_coherent = main._argus_coherent_projection
    main._argus_coherent_projection = None

    class API:
        @staticmethod
        def get_oi_isolated(symbol, worker, expiry=None):
            assert symbol == "NIFTY" and expiry is None
            return argus(now)

        @staticmethod
        def projection(symbol):
            assert symbol == "NIFTY"
            return argus(now)

    original = (
        main.argus,
        main.option_chart_feed,
        main.options_structure_engine,
        main.argus_tactical_edge,
        main.argus_market_snapshot,
    )
    main.argus = API()
    main.option_chart_feed = type(
        "ReadOnlyFeed", (), {"ingest": staticmethod(lambda _projection: None)}
    )()
    main.options_structure_engine = type(
        "ReadOnlyOSE", (), {"projection": staticmethod(lambda: ose(now))}
    )()
    main.argus_tactical_edge = engine(tmp_path)
    source_timestamp = argus(now)["data"]["underlying"]["fetched_at"]
    market = {
        "status": "AVAILABLE",
        "argus_source_timestamp": source_timestamp,
        "fetched_at": source_timestamp,
    }
    main.argus_market_snapshot = type(
        "ReadOnlyMarket",
        (),
        {
            "refresh": staticmethod(lambda _projection: market),
            "latest": staticmethod(lambda _source_timestamp: market),
        },
    )()
    try:
        main._argus_coherent_projection = main.current_argus_projection("NIFTY")
        v1 = main.argus_oi("NIFTY")
        v2_provider = main.v2_integration.providers["argus"]("NIFTY")
        assert v1["data"]["tactical_edge"] == v2_provider["data"]["tactical_edge"]
    finally:
        (
            main.argus,
            main.option_chart_feed,
            main.options_structure_engine,
            main.argus_tactical_edge,
            main.argus_market_snapshot,
        ) = original
        main._argus_coherent_projection = original_coherent
