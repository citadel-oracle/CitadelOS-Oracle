"""Phase-6A TradingView identity, auto-sync, frontend binding and safety tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import asyncio
import json
from pathlib import Path
from time import perf_counter, sleep
from types import SimpleNamespace

import pytest

from src.oracle.contracts.tradingview import (
    TradingViewAvailability, TradingViewCaptureReference,
    TradingViewChartState, TradingViewContractError, TradingViewFreshness,
    TradingViewInstrumentIdentity, TradingViewLayoutIdentity,
    TradingViewOptionIdentity, TradingViewRoute, TradingViewSymbolIdentity, seal,
)
from src.oracle.contracts.analysis import Availability, FreshnessState
from src.oracle.exact_option import ExactOptionPremiumAnalysisService
from src.oracle.tradingview_sync import (
    PERFORMANCE_STAGES, PerformanceTelemetry, TradingViewAutoSyncService,
    TradingViewSyncError, normalize_timeframe,
    route_tradingview_symbol,
)


NOW = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


class Reader:
    def __init__(self, values):
        self.values = list(values)
        self.calls = 0

    def read(self):
        self.calls += 1
        value = self.values[min(self.calls - 1, len(self.values) - 1)]
        if isinstance(value, Exception):
            raise value
        return value


def pane(symbol="NSE:NIFTY", resolution="5", layout="s", active=0):
    return {"success": True, "layout": layout, "chart_count": 1, "active_index": active,
            "panes": [{"index": 0, "symbol": symbol, "resolution": resolution}]}


def analysis(chart):
    displayed = chart.option.trading_symbol if chart.option else None
    return {"decision": {
        "decision_id": "decision_fixture", "content_hash": "d" * 64, "action": "WAIT",
        "exact_contract": "NIFTY25080724500CE", "displayed_option": displayed,
        "current_contract_accepted": displayed == "NIFTY25080724500CE",
        "current_contract_rejected": bool(displayed and displayed != "NIFTY25080724500CE"),
        "better_option_found": bool(displayed and displayed != "NIFTY25080724500CE"),
        "setup_quality": 70, "visual_certainty": "UNAVAILABLE", "data_completeness": 80,
        "execution_quality": 60, "evidence_agreement": 75, "calibration_status": "NOT_AVAILABLE",
        "historical_probability": None, "trigger": "close above 24500", "entry_band": [100, 102],
        "structural_invalidation": "swing-low", "premium_stop": 90, "targets": [120, 130],
        "costs": 2, "resulting_rr": [1.8], "why": "canonical fixture evidence",
        "risk_conflict": "none", "freshness": "FRESH", "missing_evidence": ["VISUAL_UNAVAILABLE"],
        "reason_codes": ["TRIGGER_INCOMPLETE"], "execution_authority": False,
    }, "knowledge": {"references": ["card-1"], "conflicts": ["card-2"], "execution_influence": "ZERO"}}


def service(tmp_path, values, **kwargs):
    return TradingViewAutoSyncService(
        tmp_path, reader=Reader(values), analysis_provider=analysis,
        phase5_provider=lambda: {"condition_state": "WATCHING", "paper_only": True},
        personal_oracle_provider=lambda: {"trades_today": 0},
        option_identity_resolver=lambda option: "fixture-security-id",
        clock=lambda: NOW, debounce_seconds=0, **kwargs,
    )


class FixtureQuote(SimpleNamespace):
    def to_dict(self):
        return {key: (value.value if hasattr(value, "value") else value) for key, value in vars(self).items()}


def exact_chart(symbol="NSE:NIFTY260804C24400", security_id="65854"):
    identity, instrument, option = route_tradingview_symbol(
        symbol, option_identity_resolver=lambda candidate: security_id,
    )
    return seal(TradingViewChartState(
        event_id="exact-chart", correlation_id="exact-correlation",
        source_timestamp=NOW.isoformat(), received_timestamp=NOW.isoformat(),
        generated_timestamp=NOW.isoformat(), provenance={"source": "NON_LIVE_FIXTURE"},
        symbol=identity, instrument=instrument, option=option,
        layout=TradingViewLayoutIdentity(
            session_identity="fixture", browser_identity="fixture", chart_identity="pane-0",
            layout_identity="fixture", active_pane_index=0, chart_count=1,
        ),
        timeframe="3m", chart_state_version="fixture", availability=TradingViewAvailability.AVAILABLE,
        freshness=TradingViewFreshness.FRESH, previous_state_hash=None, change_reason="TEST",
    ))


def quote(contract_id="65854", *, spread_pct=1.5, rank=1, score=90.0,
          freshness=FreshnessState.FRESH, availability=Availability.AVAILABLE):
    return FixtureQuote(
        contract_id=contract_id, trading_symbol=f"NIFTY260804C{24400 if contract_id == '65854' else 24500}",
        expiry="2026-08-04", strike=24400.0 if contract_id == "65854" else 24500.0,
        option_type="CE", bid=99.0, ask=100.0, mid=99.5, ltp=99.5,
        spread_abs=1.0, spread_pct=spread_pct, bid_depth=1200, ask_depth=1000,
        volume=500000, oi=250000, iv=18.0, delta=.52, gamma=.002,
        theta=-.25, vega=2.1, authority_rank=rank, authority_score=score,
        authority_status="CANDIDATE", availability=availability, freshness_state=freshness,
        source_timestamp=NOW.isoformat(),
    )


def exact_result(*, current=None, alternative=None, eligible=("65854",), rejected=None):
    candidates = tuple(item for item in (current or quote(), alternative) if item is not None)
    return SimpleNamespace(
        snapshot=SimpleNamespace(
            symbol="NIFTY", candidate_contracts=candidates, source_timestamp=NOW.isoformat(),
            source_timestamps={"argus": NOW.isoformat()},
            source_records={"argus_tactical": {"status": "FRESH"},
                            "ose": {"duel": {"state": "CLEAR CALL ADVANTAGE"}},
                            "vob": {"status": "LIVE"}},
        ),
        option_capture=SimpleNamespace(
            eligible_contract_ids=tuple(eligible), rejected_contracts=rejected or {},
            selected_contract_id=(alternative.contract_id if alternative and alternative.contract_id in eligible else
                                  eligible[0] if eligible else None),
        ),
        underlying=SimpleNamespace(directional_posture="BULLISH"),
    )


def exact_technicals(status="AVAILABLE"):
    return {
        "status": status, "source": "DHAN_CANONICAL_OPTION_1M",
        "completed_1m_count": 300, "completed_3m_count": 100, "completed_5m_count": 60,
        "completed_5m_close_timestamp": NOW.isoformat(), "forming_candle_excluded": True,
        "latest_completed_5m_volume": 2500,
        "trend": {"state": "BULLISH", "ema_21": 98.0, "ema_50": 95.0, "atr": 3.0,
                  "supertrend_value": 94.0, "ema_21_zone": {"high": 99.0}},
        "vob_3m": {"state": "BREAKOUT", "breakout_trigger": 101.0,
                   "support": {"zone_low": 94.0}},
        "performance": {"refresh_1m_ms": 1.0, "refresh_3m_ms": .5, "refresh_5m_ms": .4,
                        "candle_retrieval_ms": 1.9, "feature_retrieval_ms": .7},
    }


@pytest.mark.unit
@pytest.mark.parametrize(("raw", "route", "underlying"), [
    ("NSE:NIFTY", "UNDERLYING_INDEX", "NIFTY"),
    ("NSE:BANKNIFTY", "UNDERLYING_INDEX", "BANKNIFTY"),
    ("BSE:SENSEX", "UNDERLYING_INDEX", "SENSEX"),
    ("NSE:RELIANCE", "UNDERLYING_STOCK", "RELIANCE"),
    ("NSE:NIFTY1!", "FUTURE", "NIFTY"),
    ("BINANCE:BTCUSDT", "CRYPTO", "BTCUSDT"),
])
def test_symbol_routing(raw, route, underlying):
    symbol, instrument, option = route_tradingview_symbol(raw)
    assert symbol.route.value == route
    assert instrument.underlying == underlying
    assert option is None
    assert instrument.analysis_supported is (underlying == "NIFTY" and route == "UNDERLYING_INDEX")


@pytest.mark.unit
@pytest.mark.parametrize(("raw", "expiry", "strike", "side"), [
    ("NSE:NIFTY25080724500CE", "2025-08-07", 24500, "CE"),
    ("NSE:NIFTY250807P24500", "2025-08-07", 24500, "PE"),
    ("NSE:NIFTY07AUG2524500PE", "2025-08-07", 24500, "PE"),
])
def test_exact_option_detection(raw, expiry, strike, side):
    symbol, instrument, option = route_tradingview_symbol(
        raw, option_identity_resolver=lambda candidate: "65854",
    )
    assert symbol.route is TradingViewRoute.EXACT_OPTION
    assert instrument.route is TradingViewRoute.EXACT_OPTION
    assert option and (option.expiry, option.strike, option.option_side) == (expiry, strike, side)
    assert option.security_id == "65854"


@pytest.mark.unit
def test_exact_option_without_authoritative_mapping_is_unsupported():
    symbol, instrument, option = route_tradingview_symbol("NSE:NIFTY260804C24400")
    assert symbol.route is TradingViewRoute.UNSUPPORTED
    assert instrument.route is TradingViewRoute.UNSUPPORTED
    assert instrument.mapping_status == "EXACT_SECURITY_MAPPING_UNAVAILABLE"
    assert instrument.analysis_supported is False
    assert option and option.security_id is None


@pytest.mark.unit
def test_exact_option_premium_first_keeps_verified_current_contract():
    current = quote()
    calls = []
    analyzer = ExactOptionPremiumAnalysisService(lambda contract, observed_at: calls.append(contract["security_id"]) or exact_technicals())
    value = analyzer.analyze(exact_chart(), exact_result(current=current))
    assert calls == ["65854"]
    assert value["verdict"] == "KEEP_CURRENT_CONTRACT"
    assert value["current_contract_analyzed_first"] is True
    assert value["premium_candles"]["completed_3m_count"] == 100
    assert value["premium_features"]["authority"] == "OPTIONS_STRUCTURE_ENGINE"
    assert value["executable_entry_band"] == [100.0, 100.5]
    assert value["confirmations"]["ose"]["confirmed"] is True
    assert value["alternative_contract"] is None
    assert value["execution_authority"] is False


@pytest.mark.unit
def test_exact_option_rejects_only_complete_material_evidence_then_compares_alternative():
    current = quote(spread_pct=12.0, rank=4, score=40)
    alternative = quote("65999", spread_pct=1.0, rank=1, score=95)
    calls = []
    value = ExactOptionPremiumAnalysisService(lambda contract, _: calls.append(contract["security_id"]) or exact_technicals()).analyze(
        exact_chart(), exact_result(
            current=current, alternative=alternative, eligible=("65999",),
            rejected={"65854": ("SPREAD_UNACCEPTABLE",)},
        ),
    )
    assert value["verdict"] == "REJECT_CURRENT_CONTRACT"
    assert value["comparison_sequence"] == ["65854", "ALTERNATIVES_AFTER_CURRENT"]
    assert calls == ["65854", "65999"]
    assert value["material_rejection_reasons"] == ["SPREAD_UNACCEPTABLE"]
    assert value["alternative_contract"]["contract_id"] == "65999"
    assert "TIGHTER_SPREAD" in value["alternative_contract"]["comparison_reasons"]
    assert value["alternative_contract"]["premium_verification"]["completed_3m_count"] == 100


@pytest.mark.unit
def test_alternative_is_hidden_when_its_premium_evidence_is_unavailable():
    current = quote(spread_pct=12.0, rank=4, score=40)
    alternative = quote("65999", spread_pct=1.0, rank=1, score=95)
    calls = []
    def technicals(contract, _):
        calls.append(contract["security_id"])
        return exact_technicals() if contract["security_id"] == "65854" else {"status": "UNAVAILABLE"}
    value = ExactOptionPremiumAnalysisService(technicals).analyze(
        exact_chart(), exact_result(current=current, alternative=alternative, eligible=("65999",),
                                    rejected={"65854": ("SPREAD_UNACCEPTABLE",)}),
    )
    assert calls == ["65854", "65999"]
    assert value["verdict"] == "REJECT_CURRENT_CONTRACT"
    assert value["alternative_contract"] is None


@pytest.mark.unit
@pytest.mark.parametrize(("current", "technicals", "expected_missing"), [
    (quote(freshness=FreshnessState.STALE), exact_technicals(), "STALE_OPTION_QUOTE"),
    (quote(), {"status": "UNAVAILABLE", "reason": "CANONICAL_CANDLES_UNAVAILABLE"}, "EXACT_PREMIUM_CANDLES_UNAVAILABLE"),
    (quote(), {**exact_technicals(), "trend": {}}, "EXACT_PREMIUM_FEATURES_UNAVAILABLE"),
])
def test_exact_option_unavailable_or_stale_is_insufficient_not_rejected(current, technicals, expected_missing):
    value = ExactOptionPremiumAnalysisService(lambda *_: technicals).analyze(
        exact_chart(), exact_result(current=current, eligible=()),
    )
    assert value["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert expected_missing in value["missing_evidence"]
    assert value["alternative_contract"] is None


@pytest.mark.unit
def test_exact_option_wrong_security_mapping_is_insufficient():
    value = ExactOptionPremiumAnalysisService(lambda *_: exact_technicals()).analyze(
        exact_chart(security_id="WRONG"), exact_result(),
    )
    assert value["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert "EXACT_OPTION_QUOTE_NOT_IN_CANONICAL_CANDIDATES" in value["missing_evidence"]


@pytest.mark.unit
def test_exact_option_identity_mismatch_fails_insufficient_without_comparison():
    value = ExactOptionPremiumAnalysisService(lambda *_: exact_technicals()).analyze(
        exact_chart(), SimpleNamespace(snapshot=SimpleNamespace(symbol="BANKNIFTY")),
    )
    assert value["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert value["missing_evidence"] == ["UNDERLYING_IDENTITY_MISMATCH"]


@pytest.mark.unit
def test_ambiguous_malformed_and_impossible_timeframe_rejected():
    assert route_tradingview_symbol("AAPL")[0].route is TradingViewRoute.AMBIGUOUS
    with pytest.raises(TradingViewSyncError, match="UNSUPPORTED_OPTION_FORMAT"):
        route_tradingview_symbol("NSE:NIFTY24500CE")
    with pytest.raises(TradingViewSyncError, match="TIMEFRAME"):
        normalize_timeframe("2")


@pytest.mark.unit
def test_contract_rejects_future_stale_available_cross_chart_and_unverified_capture():
    symbol = TradingViewSymbolIdentity(raw_symbol="NSE:NIFTY", normalized_symbol="NIFTY", exchange="NSE",
        route=TradingViewRoute.UNDERLYING_INDEX, ambiguity_status="RESOLVED")
    instrument = TradingViewInstrumentIdentity(route=TradingViewRoute.UNDERLYING_INDEX, instrument_id=None,
        security_id=None, underlying="NIFTY", analysis_supported=True, mapping_status="AVAILABLE")
    layout = TradingViewLayoutIdentity(session_identity="s", browser_identity="b", chart_identity="c",
        layout_identity="l", active_pane_index=0, chart_count=1)
    base = dict(event_id="event-123", correlation_id="corr-123", source_timestamp=NOW.isoformat(),
        received_timestamp=NOW.isoformat(), generated_timestamp=NOW.isoformat(), provenance={"source": "test"},
        symbol=symbol, instrument=instrument, option=None, layout=layout, timeframe="5m", chart_state_version="1",
        availability=TradingViewAvailability.AVAILABLE, freshness=TradingViewFreshness.FRESH,
        previous_state_hash=None, change_reason="TEST")
    assert seal(TradingViewChartState(**base)).verify_hash()
    with pytest.raises(TradingViewContractError, match="stale"):
        TradingViewChartState(**{**base, "freshness": TradingViewFreshness.STALE})
    with pytest.raises(TradingViewContractError, match="future"):
        TradingViewChartState(**{**base, "source_timestamp": (NOW + timedelta(seconds=1)).isoformat()})
    with pytest.raises(TradingViewContractError, match="zero"):
        TradingViewCaptureReference(event_id="capture-1", correlation_id="corr-123",
            source_timestamp=NOW.isoformat(), received_timestamp=NOW.isoformat(), generated_timestamp=NOW.isoformat(),
            provenance={"source": "test"}, chart_state_hash="x", capture_status="UNVERIFIED",
            artifact_reference=None, permission_status="UNAVAILABLE", actionable_evidence_weight=1.0)


@pytest.mark.unit
def test_unchanged_state_deduplicates_without_analysis(tmp_path):
    calls = []
    sync = service(tmp_path, [pane(), pane()])
    sync.analysis_provider = lambda chart: calls.append(chart.content_hash) or analysis(chart)
    first = sync.poll_once(force_debounce=True)
    second = sync.poll_once(force_debounce=True)
    assert first["sync_state"] == second["sync_state"] == "WATCHING"
    assert len(calls) == 1
    assert sync.health()["duplicates"] == 1
    assert len([row for row in sync.event_history() if row["event_type"] == "TRADINGVIEW_STATE_CHANGED"]) == 1


@pytest.mark.unit
def test_push_events_are_ordered_replayable_and_duplicate_poll_emits_nothing(tmp_path):
    sync = service(tmp_path, [pane(), pane()])
    sync.poll_once(force_debounce=True)
    emitted = list(sync._live_events)
    assert [row["event_type"] for row in emitted[:3]] == ["chart_detected", "context_loading", "decision_updated"]
    assert len({row["event_id"] for row in emitted}) == len(emitted)
    assert all(row["state_hash"] and row["projection"] for row in emitted)
    assert sync.live_events_since(emitted[0]["event_id"]) == emitted[1:]
    before = len(emitted)
    sync.poll_once(force_debounce=True)
    assert len(sync._live_events) == before


@pytest.mark.unit
def test_production_sse_endpoint_connects_and_emits_replayable_projection():
    import app.main as main

    published = main.oracle_tradingview_sync._publish_live_event(
        "decision_updated", main.oracle_tradingview_sync.projection(),
    )

    class RequestFixture:
        headers = {}
        async def is_disconnected(self):
            return False

    async def consume(request=None):
        response = await main.oracle_live_workspace_stream(request or RequestFixture(), once=True)
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        return response, "".join(chunks)

    response, body = asyncio.run(consume())
    assert response.media_type == "text/event-stream"
    assert response.headers["x-citadel-transport"] == "SSE_PRIMARY"
    assert f"id: {published['event_id']}" in body
    assert "event: oracle_projection" in body
    assert '"state_hash"' in body and '"projection"' in body
    assert '"delivery_mode":"INITIAL_STATE"' in body

    replayed = main.oracle_tradingview_sync._publish_live_event(
        "decision_updated", main.oracle_tradingview_sync.projection(),
    )
    class ReplayRequestFixture:
        headers = {"last-event-id": published["event_id"]}
        async def is_disconnected(self):
            return False
    _, replay_body = asyncio.run(consume(ReplayRequestFixture()))
    assert f"id: {replayed['event_id']}" in replay_body
    assert '"delivery_mode":"REPLAY"' in replay_body


@pytest.mark.unit
def test_stage_telemetry_reports_latest_mean_percentiles_max_count_and_errors():
    telemetry = PerformanceTelemetry(maximum_samples=16)
    telemetry.record("mcp_subprocess", 9)
    telemetry.record("mcp_subprocess", 1, error=True)
    snapshot = telemetry.snapshot()
    assert tuple(snapshot) == PERFORMANCE_STAGES
    assert snapshot["mcp_subprocess"] == {
        "latest_ms": 1.0, "mean_ms": 5.0, "p50_ms": 1.0, "p95_ms": 9.0,
        "maximum_ms": 9.0, "sample_count": 2, "error_count": 1,
    }
    for stage in PERFORMANCE_STAGES:
        assert set(snapshot[stage]) == {"latest_ms", "mean_ms", "p50_ms", "p95_ms", "maximum_ms", "sample_count", "error_count"}
    assert "deterministic_analysis" in snapshot


@pytest.mark.unit
def test_canonical_dependency_change_refreshes_decision_without_chart_change(tmp_path):
    dependency = {"context_hash": "a"}
    calls = []
    sync = TradingViewAutoSyncService(tmp_path, reader=Reader([pane(), pane()]),
        analysis_provider=lambda chart: calls.append(chart.content_hash) or analysis(chart),
        dependency_state_provider=lambda: dependency, clock=lambda: NOW, debounce_seconds=0)
    sync.poll_once(force_debounce=True)
    dependency["context_hash"] = "b"
    projection = sync.poll_once(force_debounce=True)
    assert projection["chart_state"]["change_reason"] == "CANONICAL_EVIDENCE_CHANGED"
    assert len(calls) == 2


@pytest.mark.unit
def test_phase5_change_updates_projection_without_rerunning_analysis(tmp_path):
    control = {"condition_state": None, "latest_event_hash": None}
    calls = []
    sync = TradingViewAutoSyncService(tmp_path, reader=Reader([pane(), pane()]),
        analysis_provider=lambda chart: calls.append(chart.content_hash) or analysis(chart),
        phase5_provider=lambda: control, clock=lambda: NOW, debounce_seconds=0)
    sync.poll_once(force_debounce=True)
    control.update({"condition_state": "REVALIDATING", "latest_event_hash": "event-2"})
    projection = sync.poll_once(force_debounce=True)
    assert projection["sync_state"] == "REVALIDATING"
    assert projection["phase5"]["latest_event_hash"] == "event-2"
    assert len(calls) == 1
    assert any(row["event_type"] == "ORACLE_CONTROL_PROJECTION_CHANGED" for row in sync.event_history())


@pytest.mark.unit
def test_triggered_condition_emits_distinct_critical_alert(tmp_path):
    sync = service(tmp_path, [pane()])
    sync.poll_once(force_debounce=True)
    chart = sync._last_chart
    assert chart is not None
    alert = sync._alert(
        "PHASE5_STATE_CHANGED", "REVALIDATING", chart,
        {"content_hash": "decision-hash"},
        {"condition_state": "TRIGGERED", "latest_event_hash": "trigger-event"},
    )
    assert alert["event_type"] == "CONDITION_TRIGGERED"
    assert alert["severity"] == "CRITICAL"


@pytest.mark.unit
def test_symbol_timeframe_layout_changes_and_exact_option_first(tmp_path):
    values = [pane(), pane(resolution="3"), pane(resolution="3", layout="2h"),
              pane(symbol="NSE:NIFTY25080724400PE", resolution="3", layout="2h")]
    sync = service(tmp_path, values)
    projections = [sync.poll_once(force_debounce=True) for _ in values]
    assert [row["chart_state"]["change_reason"] for row in projections] == [
        "INITIAL_CHART_DETECTED", "TIMEFRAME_CHANGED", "LAYOUT_CHANGED", "SYMBOL_CHANGED",
    ]
    exact = projections[-1]
    assert exact["chart_state"]["option"]["option_side"] == "PE"
    assert exact["decision"]["current_contract_rejected"] is True
    assert exact["decision"]["execution_authority"] is False
    assert exact["alert_event"]["event_type"] == "BETTER_OPTION_FOUND"


@pytest.mark.unit
def test_debounce_rapid_flip_and_hash_deduplication(tmp_path):
    reader = Reader([pane("NSE:NIFTY"), pane("NSE:BANKNIFTY"), pane("NSE:NIFTY")])
    sync = TradingViewAutoSyncService(tmp_path, reader=reader, analysis_provider=analysis,
                                      clock=lambda: NOW, debounce_seconds=5)
    assert sync.poll_once()["sync_state"] == "DETECTING"
    assert sync.poll_once()["sync_state"] == "DETECTING"
    assert sync.poll_once()["sync_state"] == "DETECTING"
    assert sync.health()["analysis_runs"] == 0


@pytest.mark.unit
def test_disconnect_fails_closed_with_alert_and_backoff(tmp_path):
    sync = service(tmp_path, [TradingViewSyncError("TRADINGVIEW_MCP_TIMEOUT")])
    projection = sync.poll_once(force_debounce=True)
    assert projection["sync_state"] == "UNAVAILABLE"
    assert projection["alert_event"]["event_type"] == "TRADINGVIEW_DISCONNECTED"
    assert projection["decision"]["execution_authority"] is False
    assert sync.health()["backoff_active"] is True


@pytest.mark.unit
def test_restart_restores_checkpoint_but_requires_reacquisition(tmp_path):
    first = service(tmp_path, [pane()])
    assert first.poll_once(force_debounce=True)["chart_state"]["symbol"]["normalized_symbol"] == "NIFTY"
    restored = service(tmp_path, [TradingViewSyncError("OFFLINE")])
    projection = restored.projection()
    assert projection["sync_state"] == "DETECTING"
    print('PROJECTION:', projection); assert projection["decision"]["why"] == "RESTART_REACQUISITION_REQUIRED"
    assert restored.health()["restart_recovered"] is True


@pytest.mark.unit
def test_performance_and_no_critical_path_forbidden_dependencies(tmp_path):
    sync = service(tmp_path, [pane()])
    sync.poll_once(force_debounce=True)
    started = perf_counter()
    for _ in range(100):
        sync.poll_once(force_debounce=True)
    p95_upper = (perf_counter() - started) * 1000 / 100
    assert p95_upper < 20
    assert sync.health()["analysis_runs"] == 1
    source = (ROOT / "src/oracle/tradingview_sync.py").read_text(encoding="utf-8")
    for forbidden in ("RiskAuthorizationService", "submit_order", "OpenAlgoAnalyzerClient", "IndependentPaperGuardian", "Codex", "LLM"):
        assert forbidden not in source


@pytest.mark.unit
def test_production_frontend_binding_preserves_frozen_orbital_design():
    panel = (ROOT / "citadel-dashboard/src/components/institutional/OracleWorkspacePanel.tsx").read_text(encoding="utf-8")
    css = (ROOT / "citadel-dashboard/src/app/oracle/oracle.module.css").read_text(encoding="utf-8")
    page = (ROOT / "citadel-dashboard/src/app/oracle/page.tsx").read_text(encoding="utf-8")
    assert "assessment?.live_workspace" in panel
    for state in ("DETECTING", "LOADING_CONTEXT", "WHY / PROOF", "PAPER ORDER", "GUARDIAN"):
        assert state in panel
    for exact_proof in ("EXACT OPTION · PREMIUM FIRST", "Current suitability", "Completed candles 1m / 3m / 5m",
                        "Executable ask band", "Underlying / ARGUS / OSE / VOB", "Verified alternative"):
        assert exact_proof in panel
    for alert in ("criticalOnly", "marketHoursOnly", "Alert volume", "deduplication_key",
                  "PAPER_ORDER_PARTIALLY_FILLED", "AUTHORITY_CONFIRMATION_LOST"):
        assert alert in panel
    assert "<OracleWorkspacePanel" in page and "useDashboardSelector(feedSelectors.oracle)" in page
    assert '<FlowMap' in panel
    assert "className={styles.graphShell}" in panel and "className={styles.oracleHub}" in panel
    assert ".alertOverlay" in css
    types = (ROOT / "citadel-dashboard/src/dashboard/types/index.ts").read_text(encoding="utf-8")
    provider = (ROOT / "citadel-dashboard/src/dashboard/providers/RestDashboardProvider.ts").read_text(encoding="utf-8")
    assert "live_trading_enabled: false" in types and "exact_option" in types
    assert "new EventSource" in provider and "/v1/oracle/live-workspace/stream" in provider
    assert "after_event_id" in provider and "POLLING_FALLBACK" in provider
    assert "event.state_hash === this.lastLiveHash" in provider
    assert "this.pendingOracleEvent = event" in provider
    assert "source.onerror" in provider and "void this.load(true)" in provider
    assert provider.count("fetch(") == 1


@pytest.mark.unit
def test_safety_projection_and_alert_history_are_persistent_and_non_trading(tmp_path):
    sync = service(tmp_path, [pane()])
    projection = sync.poll_once(force_debounce=True)
    assert projection["safety"] == {
        "paper_only": True, "live_trading_enabled": False, "broker_submission": False,
        "advisory_only": True, "execution_influence": "ZERO", "execution_authority": False,
    }
    assert projection["decision"]["historical_probability"] is None
    assert projection["phase5"]["condition_state"] == "WATCHING"
    assert (tmp_path / "events.jsonl").exists()
    assert any(row["event_type"] == "ORACLE_ALERT" for row in sync.event_history())
