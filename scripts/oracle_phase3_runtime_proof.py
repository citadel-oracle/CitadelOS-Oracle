#!/usr/bin/env python3
"""Phase-3 advisory runtime proof over persisted NIFTY data and non-live fixtures."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from statistics import quantiles
import sys
from time import perf_counter
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.oracle.analysis import AnalysisSnapshotAssembler
from src.oracle.context import ContextEngine
from src.oracle.decision import OracleAnalysisService


def _load_dashboard(url: str, path: str | None):
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    with urlopen(url, timeout=5) as response:  # read-only cached dashboard route
        return json.loads(response.read().decode())


def _sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _candidate(security_id, side, rank, *, bid=99.0, ask=99.2, spread=.2, score=90.0):
    delta = .5 if side == "CE" else -.5
    return {
        "security_id": security_id, "trading_symbol": f"NIFTY2026080424400{side}",
        "expiry": "2026-08-04", "strike": 24400, "option_type": side, "side": side,
        "bid": bid, "ask": ask, "premium": ask, "spread_abs": spread,
        "spread_pct": round(spread / ask * 100, 4), "delta": delta,
        "gamma_value": .0017, "iv": 12.0, "oi": 500000, "volume": 1000000,
        "distance_atm": 0, "rank": rank, "contract_score": score,
        "status": "CANDIDATE", "rejection_reason": None, "stretch_state": "NORMAL",
    }


def _fixture_dashboard(context, now, *, trigger, wide=False):
    lanes = {lane.timeframe: lane for lane in context.lanes}
    five = lanes["5m"].candle.bar_end
    three = lanes["3m"].candle.bar_end
    ce = _candidate("FIXTURE_CE_PRIMARY", "CE", 1, bid=99 if not wide else 90, ask=99.2, spread=.2 if not wide else 9.2)
    ce["spread_pct"] = round(ce["spread_abs"] / ce["ask"] * 100, 4)
    alternative = _candidate("FIXTURE_CE_ALTERNATIVE", "CE", 2, bid=79.8, ask=80.0, spread=.2, score=82)
    pe = _candidate("FIXTURE_PE", "PE", 3, bid=89.8, ask=90.0, spread=.2, score=80)
    candidates = [ce, pe] if wide else [ce, alternative, pe]
    source = (now - timedelta(seconds=5)).isoformat()
    broken = [{"zone_id": "fixture-break", "role": "RESISTANCE", "broken_at": three,
               "zone_low": 24399.5, "zone_high": 24400.0}] if trigger else []
    return {
        "symbol": "NIFTY", "generated_at": now.isoformat(), "trace_id": "phase3-non-live-fixture",
        "feeds": {
            "argus": {"data": {"data": {
                "underlying": {"symbol": "NIFTY", "security_id": 13, "ltp": 24400.0,
                               "expiry": "2026-08-04", "market_state": "NON_LIVE_FIXTURE",
                               "fetched_at": source, "trading_date": now.date().isoformat()},
                "atm_window": [{"strike": row["strike"], row["option_type"].lower(): {
                    "security_id": row["security_id"], "ltp": row["premium"],
                    "top_bid_quantity": 500, "top_ask_quantity": 500,
                    "theta": -1.0, "vega": 4.0,
                }} for row in candidates],
                "tactical_edge": {"calculation_id": "phase3-fixture-argus", "schema_version": "existing",
                    "source_timestamp": source, "option_chain_source_timestamp": source,
                    "spot_source_timestamp": five, "freshness": "FRESH",
                    "entry_lifecycle": {"state": "NORMAL"},
                    "contract_selection": {"expiry": "2026-08-04", "all_candidate_ranks": candidates,
                                           "directive_contract": ce}},
            }}},
            "oracle": {"data": {"symbol": "NIFTY", "directional_bias": "BULLISH",
                "signal": "WAIT", "regime": "TRENDING", "market_data_as_of": five,
                "decision_boundary_5m": five}},
            "strategy_lab": {"data": {"execution": {
                "nifty_vob": {"schema_version": "existing", "symbol": "NIFTY",
                    "current_nifty_spot": 24400.0, "decision_boundary_5m": five,
                    "strongest_confluence": {"bullish": {"side": "BULLISH", "tier": "STRONG"}, "bearish": None},
                    "timeframes": {
                        "5m": {"evaluated_through": five, "current_nifty_price": 24400.0,
                               "nearest_bullish_support": {"zone_id": "fixture-support", "zone_low": 24390.0, "zone_high": 24392.0},
                               "nearest_bearish_resistance": {"zone_id": "fixture-target", "zone_low": 24448.0, "zone_high": 24450.0}},
                        "3m": {"evaluated_through": three, "recently_broken": broken}}},
                "options_structure": {"schema_version": "existing", "symbol": "NIFTY", "expiry": "2026-08-04",
                    "source_timestamp": source, "decision_boundary_5m": five, "status": "LIVE",
                    "duel": {"state": "CLEAR CALL ADVANTAGE", "ce_score": 80, "pe_score": 20, "delta": 60}},
            }}},
        },
    }


def _feature_fixture(now):
    return {"feature_snapshot_id": "phase3-fixture-features", "source_timestamp": (now-timedelta(seconds=5)).isoformat(),
            "supertrend": {"direction": "BULLISH"}, "atr_value": 15, "vwap_value": 24398}


def _p95(values):
    return round(quantiles(values, n=100, method="inclusive")[94], 3)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dashboard-url", default="http://127.0.0.1:8000/v2/dashboard")
    parser.add_argument("--dashboard-json")
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()
    state_root = Path(os.environ.get("CITADEL_STATE_ROOT", "/Users/ayushmudgal/Developer/CitadelOS/logs"))
    protected = [state_root / name for name in (
        "paper_state.json", "risk_control_state.json", "oracle_missions/mission_state.json",
        "development_paper_state.json", "oracle_dev/oracle_dev_guardian_state.json",
    )]
    before = {str(path): _sha(path) for path in protected}
    context_engine = ContextEngine(state_root / "oracle_perception/context", candle_path=state_root / "vob_1m_candles.json")
    context = context_engine.latest_snapshot() or context_engine.bootstrap_from_persisted(correlation_id="phase3-runtime")
    if context is None:
        raise RuntimeError("CONTEXT_UNAVAILABLE")
    dashboard = _load_dashboard(args.dashboard_url, args.dashboard_json)
    now = datetime.now(timezone.utc)
    assembler = AnalysisSnapshotAssembler(clock=lambda: now)
    service = OracleAnalysisService(state_root / "oracle_analysis", clock=lambda: now, snapshot_assembler=assembler)

    historical_snapshot = assembler.assemble(
        context=context, dashboard=dashboard, canonical_features=None,
        visual_claims=(), correlation_id="phase3-runtime-historical",
    )
    historical = service.analyze_snapshot(historical_snapshot, persist=True)
    fixture_feature = _feature_fixture(now)
    wait_snapshot = assembler.assemble(
        context=context, dashboard=_fixture_dashboard(context, now, trigger=False),
        canonical_features=fixture_feature, visual_claims=(), correlation_id="phase3-runtime-wait-non-live-fixture",
    )
    wait = service.analyze_snapshot(wait_snapshot, persist=True)
    reject_snapshot = assembler.assemble(
        context=context, dashboard=_fixture_dashboard(context, now, trigger=True, wide=True),
        canonical_features=fixture_feature, visual_claims=(), correlation_id="phase3-runtime-reject-non-live-fixture",
    )
    rejected = service.analyze_snapshot(reject_snapshot, persist=True)
    buy_snapshot = assembler.assemble(
        context=context, dashboard=_fixture_dashboard(context, now, trigger=True),
        canonical_features=fixture_feature, visual_claims=(), correlation_id="phase3-runtime-buy-non-live-fixture",
    )
    buy = service.analyze_snapshot(buy_snapshot, persist=True)

    stage_ms = {name: [] for name in ("snapshot_assembly", "underlying", "timing", "option_capture", "evidence", "decision", "warm_end_to_end")}
    fixture_dashboard = _fixture_dashboard(context, now, trigger=True)
    for index in range(max(5, args.iterations)):
        started = perf_counter()
        snapshot = assembler.assemble(context=context, dashboard=fixture_dashboard,
            canonical_features=fixture_feature, visual_claims=(), correlation_id=f"phase3-perf-{index}")
        stage_ms["snapshot_assembly"].append((perf_counter() - started) * 1000)
        started = perf_counter(); underlying = service.analyst.assess_underlying(snapshot)
        stage_ms["underlying"].append((perf_counter() - started) * 1000)
        started = perf_counter(); timing = service.analyst.assess_timing(snapshot, underlying)
        stage_ms["timing"].append((perf_counter() - started) * 1000)
        started = perf_counter(); options = service.analyst.assess_option_capture(snapshot, underlying)
        stage_ms["option_capture"].append((perf_counter() - started) * 1000)
        started = perf_counter(); evidence = service.evidence_engine.build(snapshot, underlying, timing, options)
        stage_ms["evidence"].append((perf_counter() - started) * 1000)
        started = perf_counter(); service._decide(snapshot, underlying, timing, options, evidence)
        stage_ms["decision"].append((perf_counter() - started) * 1000)
        started = perf_counter(); service.analyze_snapshot(snapshot, persist=False)
        stage_ms["warm_end_to_end"].append((perf_counter() - started) * 1000)
    performance = {name: {"p95_ms": _p95(values), "max_ms": round(max(values), 3)} for name, values in stage_ms.items()}
    performance["target"] = {"p95_ms": 1000, "met": performance["warm_end_to_end"]["p95_ms"] <= 1000,
                             "excludes": ["TradingView", "LLM", "persistence"]}
    after = {str(path): _sha(path) for path in protected}
    proof = {
        "historical_persisted": {"label": "HISTORICAL_STALE_PERSISTED_NIFTY", "analysis_id": historical.snapshot.analysis_id,
            "decision_id": historical.decision.decision_id, "action": historical.decision.action,
            "market_state": historical.snapshot.market_state, "freshness": historical.snapshot.freshness_state.value,
            "reason_codes": list(historical.decision.reason_codes)},
        "wait": {"label": "NON_LIVE_FIXTURE", "action": wait.decision.action,
                 "timing": wait.timing.timing_state, "reason_codes": list(wait.decision.reason_codes)},
        "no_trade": {"label": "NON_LIVE_FIXTURE", "action": rejected.decision.action,
                     "reason_codes": list(rejected.decision.reason_codes),
                     "rejected_contracts": dict(rejected.option_capture.rejected_contracts)},
        "buy_eligible": {"label": "NON_LIVE_FIXTURE", "action": buy.decision.action,
            "contract": buy.decision.contract_label, "setup_quality": buy.decision.setup_quality,
            "entry_band": buy.decision.entry_band, "premium_stop": buy.decision.premium_hard_stop_candidate,
            "targets": buy.decision.target_premiums, "resulting_rr": buy.decision.resulting_rr,
            "estimated_cost": buy.decision.estimated_cost, "execution_authority": buy.decision.execution_authority},
        "contract_comparison": [{"contract_id": row.contract_id, "rank": row.authority_rank, "ask": row.ask,
            "spread_pct": row.spread_pct, "delta": row.delta,
            "eligible": row.contract_id in buy.option_capture.eligible_contract_ids,
            "reasons": list(buy.option_capture.rejected_contracts.get(row.contract_id, ())) }
            for row in buy.snapshot.candidate_contracts],
        "evidence": {
            "historical": {"bundle_id": historical.evidence.bundle_id,
                "supporting": historical.evidence.supporting_count,
                "conflicting": historical.evidence.contradicting_count,
                "missing": historical.evidence.missing_count,
                "items": [{"claim": row.claim, "classification": row.classification,
                           "source_record_id": row.source_record_id, "source_record_hash": row.source_record_hash}
                          for row in historical.evidence.items],
                "conflicts": [row.to_dict() for row in historical.evidence.conflicts]},
            "buy_fixture": {"bundle_id": buy.evidence.bundle_id, "supporting": buy.evidence.supporting_count,
                "conflicting": buy.evidence.contradicting_count, "missing": buy.evidence.missing_count,
                "conflicts": [row.to_dict() for row in buy.evidence.conflicts]},
        },
        "explicit_unavailable": {"tradingview": buy.decision.visual_certainty,
                                 "4h": "4H_UNAVAILABLE_PARITY_UNPROVEN" in buy.underlying.blockers},
        "performance": performance,
        "trading_state": {"unchanged": before == after, "before": before, "after": after},
        "safety": {"paper_only": True, "live_trading_enabled": False, "broker_submission": False,
                   "advisory_only": True, "execution_influence": "ZERO", "execution_authority": False},
    }
    print(json.dumps(proof, sort_keys=True, indent=2))
    return 0 if (
        historical.decision.action == "NO_TRADE" and wait.decision.action == "WAIT"
        and rejected.decision.action == "NO_TRADE" and buy.decision.action == "BUY"
        and before == after and performance["target"]["met"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
