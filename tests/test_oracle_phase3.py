"""Phase-3 deterministic analyst/evidence/decision acceptance tests."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.oracle.analysis import AnalysisSnapshotAssembler
from src.oracle.context import ContextEngine
from src.oracle.contracts.analysis import AnalysisContractError, AnalysisSnapshot, OptionContractQuote, record_from_dict
from src.oracle.contracts.perception import Availability, FreshnessState
from src.oracle.decision import OracleAnalysisService


IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 7, 31, 15, 31, tzinfo=IST)


def minute_rows():
    rows = []
    start = datetime(2026, 7, 31, 9, 15, tzinfo=IST)
    for offset in range(375):
        price = 100 + offset * 0.001
        rows.append({"time": (start + timedelta(minutes=offset)).timestamp(), "open": price,
                     "high": price + .2, "low": price - .2, "close": price + .05,
                     "volume": 1000 + offset})
    return rows


def context_fixture(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    rows = minute_rows()
    candle_path = tmp_path / "candles.json"
    candle_path.write_text(json.dumps({"candles": rows}), encoding="utf-8")
    engine = ContextEngine(tmp_path / "context", candle_path=candle_path, clock=lambda: NOW)
    return engine.build(
        instrument_id="NSE:IDX_I:13", symbol="NIFTY", candles_1m=rows,
        correlation_id="phase3-fixture", parity_4h=False,
        source_ids={"canonical": "phase3-fixture"},
        dependency_versions={"policy": "2.0.1", "vob": "existing-authority"},
    )


def contract(security_id="CE100", side="CE", strike=100, rank=1, score=90, *,
             bid=9.8, ask=10.0, spread_abs=.2, spread_pct=2.0, delta=.5,
             iv=18.0, distance=0, rejection=None):
    return {
        "security_id": security_id, "trading_symbol": f"NIFTY20260804{strike}{side}",
        "expiry": "2026-08-04", "strike": strike, "option_type": side,
        "side": side, "bid": bid, "ask": ask, "premium": ask,
        "spread_abs": spread_abs, "spread_pct": spread_pct, "delta": delta,
        "gamma_value": .002, "iv": iv, "oi": 250000, "volume": 500000,
        "distance_atm": distance, "rank": rank, "contract_score": score,
        "status": "CANDIDATE", "rejection_reason": rejection, "stretch_state": "NORMAL",
    }


def dashboard(context, *, direction="BULLISH", trigger=True, market_state="NON_LIVE_FIXTURE",
              contracts=None, ose_state=None, spot=100.0, support=99.0, resistance=110.0):
    lanes = {lane.timeframe: lane for lane in context.lanes}
    boundary_5m = lanes["5m"].candle.bar_end
    boundary_3m = lanes["3m"].candle.bar_end
    source = (NOW - timedelta(seconds=10)).isoformat()
    contracts = contracts if contracts is not None else [
        contract(), contract("CE250", "CE", 250, 2, 98, bid=.8, ask=1.0, distance=150),
        contract("PE100", "PE", 100, 3, 80, delta=-.5),
    ]
    side = "CALL" if direction == "BULLISH" else "PUT"
    ose_state = ose_state or f"CLEAR {side} ADVANTAGE"
    recently_broken = [{"zone_id": "trigger-zone", "role": "RESISTANCE" if direction == "BULLISH" else "SUPPORT",
                        "broken_at": boundary_3m, "zone_high": spot, "zone_low": spot - .1}] if trigger else []
    bearish = {"side": "BEARISH", "tier": "STRONG"} if direction == "BEARISH" else None
    bullish = {"side": "BULLISH", "tier": "STRONG"} if direction == "BULLISH" else None
    return {
        "symbol": "NIFTY", "generated_at": NOW.isoformat(), "trace_id": "fixture-trace",
        "feeds": {
            "argus": {"data": {"data": {
                "underlying": {"symbol": "NIFTY", "security_id": 13, "ltp": spot,
                               "expiry": "2026-08-04", "market_state": market_state,
                               "fetched_at": source, "trading_date": "2026-07-31"},
                "atm_window": [{"strike": row["strike"], row["option_type"].lower(): {
                    "security_id": row["security_id"], "ltp": row["premium"],
                    "top_bid_quantity": 1000, "top_ask_quantity": 1000,
                    "theta": -.2, "vega": 2.1,
                }} for row in contracts],
                "tactical_edge": {
                    "schema_version": "existing", "calculation_id": "argus-fixture",
                    "source_timestamp": source, "option_chain_source_timestamp": source,
                    "spot_source_timestamp": boundary_5m, "freshness": "FRESH",
                    "contract_selection": {"expiry": "2026-08-04", "all_candidate_ranks": contracts,
                                           "directive_contract": contracts[0] if contracts else None},
                    "entry_lifecycle": {"state": "NORMAL"},
                },
            }}},
            "oracle": {"data": {"symbol": "NIFTY", "directional_bias": direction,
                "signal": "WAIT", "regime": "TRENDING", "market_data_as_of": boundary_5m,
                "decision_boundary_5m": boundary_5m}},
            "strategy_lab": {"data": {"execution": {
                "nifty_vob": {
                    "schema_version": "existing", "symbol": "NIFTY", "current_nifty_spot": spot,
                    "decision_boundary_5m": boundary_5m,
                    "strongest_confluence": {"bullish": bullish, "bearish": bearish},
                    "timeframes": {
                        "5m": {"evaluated_through": boundary_5m, "current_nifty_price": spot,
                               "nearest_bullish_support": {"zone_id": "support-zone", "zone_low": support, "zone_high": support + .2},
                               "nearest_bearish_resistance": {"zone_id": "resistance-zone", "zone_low": resistance - .2, "zone_high": resistance}},
                        "3m": {"evaluated_through": boundary_3m, "recently_broken": recently_broken},
                    },
                },
                "options_structure": {
                    "schema_version": "existing", "symbol": "NIFTY", "expiry": "2026-08-04",
                    "source_timestamp": source, "decision_boundary_5m": boundary_5m,
                    "status": "LIVE", "duel": {"state": ose_state, "ce_score": 80, "pe_score": 20, "delta": 60},
                },
            }}},
        },
    }


def features(direction="BULLISH"):
    return {"feature_snapshot_id": "features-fixture", "source_timestamp": (NOW-timedelta(seconds=10)).isoformat(),
            "supertrend": {"direction": direction}, "atr_value": 1.0, "vwap_value": 100.0}


def result(tmp_path, *, direction="BULLISH", trigger=True, contracts=None, ose_state=None,
           market_state="NON_LIVE_FIXTURE", support=99.0, resistance=110.0):
    context = context_fixture(tmp_path)
    snapshot = AnalysisSnapshotAssembler(clock=lambda: NOW).assemble(
        context=context,
        dashboard=dashboard(context, direction=direction, trigger=trigger, contracts=contracts,
                            ose_state=ose_state, market_state=market_state,
                            support=support, resistance=resistance),
        canonical_features=features(direction), visual_claims=(), correlation_id="phase3-fixture",
    )
    service = OracleAnalysisService(tmp_path / "analysis", clock=lambda: NOW)
    return service.analyze_snapshot(snapshot, persist=True), service


@pytest.mark.unit
def test_contracts_are_frozen_hashed_and_recoverable(tmp_path):
    value, service = result(tmp_path)
    assert all(record.verify_hash() for record in (
        value.snapshot, value.underlying, value.timing, value.option_capture,
        value.evidence, value.decision,
    ))
    with pytest.raises(FrozenInstanceError):
        value.decision.action = "WAIT"
    with pytest.raises(AnalysisContractError, match="hash"):
        replace(value.decision, content_hash="0" * 64)
    restored = service.decision(value.decision.decision_id)
    assert restored.content_hash == value.decision.content_hash


@pytest.mark.unit
def test_cross_contract_and_crossed_quote_fail_closed(tmp_path):
    value, _ = result(tmp_path)
    quote = value.snapshot.candidate_contracts[0]
    with pytest.raises(AnalysisContractError, match="identity"):
        replace(quote, content_hash="", contract_id="different")
    with pytest.raises(AnalysisContractError, match="crossed"):
        replace(quote, content_hash="", bid=11, ask=10)


@pytest.mark.unit
def test_snapshot_is_atomic_compatible_and_keeps_4h_visual_unavailable(tmp_path):
    value, _ = result(tmp_path)
    assert value.snapshot.compatible is True
    assert value.snapshot.source_states["argus"] == "FRESH"
    assert "4H" in value.snapshot.missing_evidence
    assert "VISUAL_UNAVAILABLE" in value.snapshot.missing_evidence
    assert value.decision.visual_certainty == "UNAVAILABLE"
    assert "4H_UNAVAILABLE_PARITY_UNPROVEN" in value.underlying.blockers


@pytest.mark.unit
def test_stale_argus_stale_ose_and_incompatible_boundaries_forbid_buy(tmp_path):
    context = context_fixture(tmp_path)
    assembler = AnalysisSnapshotAssembler(clock=lambda: NOW)
    raw = dashboard(context, market_state="OPEN")
    old = (NOW - timedelta(hours=1)).isoformat()
    raw["feeds"]["argus"]["data"]["data"]["tactical_edge"]["option_chain_source_timestamp"] = old
    stale_argus = assembler.assemble(context=context, dashboard=raw, canonical_features=features(),
                                     correlation_id="stale-argus")
    assert stale_argus.source_states["argus"] == "STALE"
    stale_result = OracleAnalysisService(tmp_path / "stale-argus").analyze_snapshot(stale_argus, persist=False)
    assert stale_result.decision.action == "NO_TRADE"
    assert stale_result.option_capture.selected_contract_id is None
    assert "STALE_OPTION_QUOTE" in stale_result.option_capture.rejected_contracts["CE100"]

    raw = dashboard(context, market_state="OPEN")
    raw["feeds"]["strategy_lab"]["data"]["execution"]["options_structure"]["source_timestamp"] = old
    stale_ose = assembler.assemble(context=context, dashboard=raw, canonical_features=features(),
                                  correlation_id="stale-ose")
    assert stale_ose.source_states["ose"] == "STALE"

    raw = dashboard(context)
    raw["feeds"]["strategy_lab"]["data"]["execution"]["options_structure"]["decision_boundary_5m"] = old
    incompatible = assembler.assemble(context=context, dashboard=raw, canonical_features=features(),
                                      correlation_id="incompatible-ose")
    assert incompatible.compatible is False
    assert "OSE_TO_CONTEXT_5M_INCOMPATIBLE" in incompatible.compatibility_reasons


@pytest.mark.unit
def test_cross_symbol_and_missing_chain_fields_fail_closed(tmp_path):
    context = context_fixture(tmp_path)
    raw = dashboard(context)
    raw["symbol"] = "BANKNIFTY"
    raw["feeds"]["argus"]["data"]["data"]["underlying"]["symbol"] = "BANKNIFTY"
    snapshot = AnalysisSnapshotAssembler(clock=lambda: NOW).assemble(
        context=context, dashboard=raw, canonical_features=features(), correlation_id="cross-symbol")
    assert snapshot.compatible is False
    assert not snapshot.candidate_contracts
    assert "CROSS_SYMBOL_SOURCE_CONFLICT" in snapshot.compatibility_reasons

    incomplete = contract("MISSING", "CE", 100, 1, 90, bid=None, delta=None)
    value, _ = result(tmp_path / "missing", contracts=[incomplete])
    quote = value.snapshot.candidate_contracts[0]
    assert {"BID_UNAVAILABLE", "DELTA_UNAVAILABLE"}.issubset(quote.missing_evidence)
    assert value.decision.action == "NO_TRADE"


@pytest.mark.unit
def test_conflicting_direction_and_extended_entry_are_distinct_states(tmp_path):
    context = context_fixture(tmp_path)
    raw = dashboard(context)
    raw["feeds"]["oracle"]["data"]["directional_bias"] = "BEARISH"
    snapshot = AnalysisSnapshotAssembler(clock=lambda: NOW).assemble(
        context=context, dashboard=raw, canonical_features=features("BULLISH"), correlation_id="direction-conflict")
    conflict = OracleAnalysisService(tmp_path / "conflict").analyze_snapshot(snapshot, persist=False)
    assert conflict.underlying.directional_posture == "NEUTRAL"
    assert conflict.decision.action == "NO_TRADE"

    raw = dashboard(context)
    raw["feeds"]["argus"]["data"]["data"]["tactical_edge"]["contract_selection"]["directive_contract"]["stretch_state"] = "STRETCHED"
    snapshot = AnalysisSnapshotAssembler(clock=lambda: NOW).assemble(
        context=context, dashboard=raw, canonical_features=features(), correlation_id="extended-entry")
    extended = OracleAnalysisService(tmp_path / "extended").analyze_snapshot(snapshot, persist=False)
    assert extended.timing.timing_state == "ENTRY_EXTENDED"
    assert extended.decision.action == "WAIT"


@pytest.mark.unit
def test_buy_fixture_requires_complete_mandatory_gates(tmp_path):
    value, _ = result(tmp_path)
    assert value.decision.action == "BUY"
    assert value.timing.timing_state == "ENTRY_AVAILABLE"
    assert value.option_capture.selected_contract_id == "CE100"
    assert value.decision.execution_authority is False
    assert value.decision.historical_probability is None
    assert value.decision.calibration_status == "NOT_AVAILABLE"


@pytest.mark.unit
def test_wait_when_trigger_is_incomplete(tmp_path):
    value, _ = result(tmp_path, trigger=False)
    assert value.timing.timing_state == "CONFIRMATION_PENDING"
    assert value.decision.action == "WAIT"
    assert "TRIGGER_INCOMPLETE" in value.decision.reason_codes


@pytest.mark.unit
def test_bearish_assessment_selects_exact_pe_candidate(tmp_path):
    rows = [contract("PE100", "PE", 100, 1, 90, delta=-.5), contract("CE100", "CE", 100, 2, 80)]
    value, _ = result(tmp_path, direction="BEARISH", contracts=rows, support=90, resistance=101)
    assert value.underlying.directional_posture == "BEARISH"
    assert value.option_capture.selected_contract_id == "PE100"
    assert value.decision.action == "BUY"


@pytest.mark.unit
@pytest.mark.parametrize("candidate,reason", [
    (contract("FAR", "CE", 250, 1, 99, bid=.8, ask=1, distance=150), "FAR_OTM_OR_DISTANCE_UNACCEPTABLE"),
    (contract("WIDE", "CE", 100, 1, 99, bid=8, ask=10, spread_abs=2, spread_pct=20), "SPREAD_UNACCEPTABLE"),
    (contract("NODELTA", "CE", 100, 1, 99, delta=None), "DELTA_UNSUITABLE_OR_MISSING"),
    (contract("HOSTILE", "CE", 100, 1, 99, iv=50), "IV_HOSTILITY"),
])
def test_ineligible_option_truth_is_explicit(tmp_path, candidate, reason):
    value, _ = result(tmp_path, contracts=[candidate])
    assert value.decision.action == "NO_TRADE"
    assert reason in value.option_capture.rejected_contracts[candidate["security_id"]]


@pytest.mark.unit
def test_authority_rank_beats_cheapest_and_missing_greeks_are_honest(tmp_path):
    best = contract("BEST", "CE", 100, 1, 90, bid=9.8, ask=10)
    cheap = contract("CHEAP", "CE", 150, 2, 80, bid=4.8, ask=5, distance=50)
    value, _ = result(tmp_path, contracts=[best, cheap])
    assert value.option_capture.selected_contract_id == "BEST"
    selected = next(row for row in value.snapshot.candidate_contracts if row.contract_id == "BEST")
    assert selected.mid == 9.9
    assert selected.ltp == 10
    assert selected.theta == -.2 and selected.vega == 2.1


@pytest.mark.unit
def test_ose_nonconfirmation_and_market_closed_forbid_buy(tmp_path):
    nonconfirm, _ = result(tmp_path / "ose", ose_state="CLEAR PUT ADVANTAGE")
    assert nonconfirm.decision.action == "NO_TRADE"
    assert "OSE_NON_CONFIRMATION" in nonconfirm.decision.reason_codes
    closed, _ = result(tmp_path / "closed", market_state="CLOSED")
    assert closed.snapshot.availability is Availability.HISTORICAL
    assert closed.snapshot.freshness_state is FreshnessState.STALE
    assert closed.decision.action == "NO_TRADE"
    assert "OPPORTUNITY_EXPIRED_OR_MARKET_CLOSED" in closed.decision.reason_codes


@pytest.mark.unit
def test_dynamic_structure_costs_and_rr_are_outputs_not_stretched(tmp_path):
    value, _ = result(tmp_path)
    estimate = value.option_capture.execution_estimate
    assert estimate.entry_band == (10.0, 10.1)
    assert estimate.expected_entry == 10.05
    assert estimate.premium_hard_stop_candidate == 9.55
    assert estimate.target_premiums == (15.05,)
    assert estimate.estimated_round_trip_cost == .3
    assert estimate.resulting_rr == (5.875,)
    poor, _ = result(tmp_path / "poor", resistance=101.2)
    assert poor.decision.action == "NO_TRADE"
    assert "INSUFFICIENT_NATURAL_RR" in poor.decision.reason_codes
    assert poor.underlying.natural_targets[0].level == 101.2


@pytest.mark.unit
def test_store_gets_are_side_effect_free_and_records_are_immutable(tmp_path):
    value, service = result(tmp_path)
    before = {path: path.stat().st_mtime_ns for path in (tmp_path / "analysis").rglob("*.json")}
    stored = service.analysis(value.snapshot.analysis_id)
    assert stored["manifest"]["decision_id"] == value.decision.decision_id
    assert record_from_dict(AnalysisSnapshot, stored["analysis"]).content_hash == value.snapshot.content_hash
    assert service.evidence(value.decision.decision_id).content_hash == value.evidence.content_hash
    after = {path: path.stat().st_mtime_ns for path in (tmp_path / "analysis").rglob("*.json")}
    assert after == before

    with pytest.raises(ValueError, match="ID_INVALID"):
        service.create(visual_claim_ids=("../../outside",))


@pytest.mark.safety
def test_phase3_modules_have_no_forbidden_dependencies_or_mutation_calls():
    files = [
        Path("src/oracle/analysis/snapshot.py"), Path("src/oracle/analyst/core.py"),
        Path("src/oracle/evidence/engine.py"), Path("src/oracle/decision/service.py"),
    ]
    forbidden_imports = ("risk", "execution", "guardian", "paper_autopilot", "dhan", "openalgo")
    forbidden_calls = ("submit_order", "authorize", "paper_execute", "arm_condition", "cancel_order")
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = []
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imports.extend(alias.name.lower() for alias in node.names)
            if isinstance(node, ast.ImportFrom): imports.append((node.module or "").lower())
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute): calls.append(node.func.attr.lower())
        assert not any(any(token in name for token in forbidden_imports) for name in imports)
        assert not any(call in forbidden_calls for call in calls)


@pytest.mark.safety
def test_api_surface_and_safety_literals_are_advisory_only():
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert '@app.post("/v1/oracle/analysis"' in source
    assert '@app.get("/v1/oracle/analysis/{analysis_id}"' in source
    assert '@app.get("/v1/oracle/decisions/{decision_id}"' in source
    assert '@app.get("/v1/oracle/decisions/{decision_id}/evidence"' in source
    decision_source = Path("src/oracle/decision/service.py").read_text(encoding="utf-8")
    for literal in ('"paper_only": True', '"live_trading_enabled": False', '"broker_submission": False',
                    '"advisory_only": True', '"execution_influence": "ZERO"', "execution_authority=False"):
        assert literal in decision_source


@pytest.mark.unit
def test_api_functions_persist_only_advisory_records_and_gets_do_not_write(tmp_path, monkeypatch):
    import app.main as main

    context = context_fixture(tmp_path / "api-context")
    calls = {"context": 0, "dashboard": 0, "features": 0}

    def counted(name, value):
        def provider():
            calls[name] += 1
            return value
        return provider

    service = OracleAnalysisService(
        tmp_path / "api-analysis", clock=lambda: NOW,
        context_provider=counted("context", context),
        dashboard_provider=counted("dashboard", dashboard(context)),
        feature_provider=counted("features", features()),
        visual_claim_provider=lambda _: None,
    )
    monkeypatch.setattr(main, "oracle_analysis_service", service)
    created = main.create_oracle_analysis(main.OracleAnalysisRequest(correlation_id="phase3-api-fixture"))
    decision_id = created["decision"]["decision_id"]
    analysis_id = created["analysis"]["analysis_id"]
    assert calls == {"context": 1, "dashboard": 1, "features": 1}
    before = {path: path.stat().st_mtime_ns for path in (tmp_path / "api-analysis").rglob("*.json")}
    assert main.oracle_analysis_record(analysis_id)["manifest"]["decision_id"] == decision_id
    assert main.oracle_decision_record(decision_id)["execution_authority"] is False
    assert main.oracle_decision_evidence(decision_id)["bundle_id"].startswith("evidence_")
    after = {path: path.stat().st_mtime_ns for path in (tmp_path / "api-analysis").rglob("*.json")}
    assert calls == {"context": 1, "dashboard": 1, "features": 1}
    assert after == before
