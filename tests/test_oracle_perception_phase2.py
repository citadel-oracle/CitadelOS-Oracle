"""Phase-2 Oracle perception, cache, visual and safety acceptance tests."""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, time, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.oracle.context import ContextEngine, ContextStateError
from src.oracle.contracts.perception import (
    Availability, CanonicalCandleRef, CompletionStatus, ContractValidationError,
    FreshnessState, SUPPORTED_TIMEFRAMES, VisualClaimCandidate, seal,
)
from src.oracle.visual import TradingViewMCPAdapter, VisualClaimVerifier, VisualObservationStore


IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)


def metadata(*, timeframe="3m", source=None, freshness=FreshnessState.FRESH):
    source = source or (NOW - timedelta(minutes=3))
    return dict(
        correlation_id="corr-phase2", instrument_id="NSE:IDX_I:13", symbol="NIFTY", timeframe=timeframe,
        source_timestamp=source.isoformat(), generated_at=NOW.isoformat(), as_of=source.isoformat(),
        availability=Availability.AVAILABLE, freshness_state=freshness,
        source_ids={"canonical": "fixture"}, dependency_versions={"policy": "2.0.0"},
        completion_status=CompletionStatus.COMPLETE,
        provenance={"source": "TEST_CANONICAL", "advisory_only": True, "execution_influence": "ZERO"},
    )


def candle(index, *, timeframe="3m", close=101.0, high=None, low=None, symbol="NIFTY", freshness=FreshnessState.FRESH):
    start = NOW - timedelta(minutes=3 * (4 - index))
    raw = CanonicalCandleRef(
        **{**metadata(timeframe=timeframe, source=start + timedelta(minutes=3), freshness=freshness), "symbol": symbol},
        candle_id=f"candle-{index}", security_id="13", bar_start=start.isoformat(),
        bar_end=(start + timedelta(minutes=3)).isoformat(), open=100.0,
        high=float(high if high is not None else max(101.0, close)),
        low=float(low if low is not None else min(99.0, close)), close=float(close), volume=1000.0,
        trading_date=start.date().isoformat(),
    )
    return seal(raw)


def candidate(claim_type, direction, predicates, tolerance=0.0):
    return seal(VisualClaimCandidate(
        **metadata(), claim_id=f"claim-{claim_type.lower()}", claim_type=claim_type, direction=direction,
        predicates=predicates, declared_tolerance=tolerance, observation_id="observation-1",
    ))


def minute_rows(day=datetime(2026, 7, 31, tzinfo=IST), sessions=1):
    rows = []
    for session_index in range(sessions):
        date = (day - timedelta(days=sessions - session_index - 1)).date()
        start = datetime.combine(date, datetime.min.time(), IST).replace(hour=9, minute=15)
        for offset in range(375):
            price = 24000 + session_index * 100 + offset * 0.1
            rows.append({"time": (start + timedelta(minutes=offset)).timestamp(), "open": price,
                         "high": price + 1, "low": price - 1, "close": price + 0.2, "volume": 1000 + offset})
    return rows


def engine(tmp_path, rows, *, now=datetime(2026, 8, 1, 10, 0, tzinfo=IST)):
    path = tmp_path / "candles.json"
    path.write_text(json.dumps({"candles": rows}), encoding="utf-8")
    return ContextEngine(tmp_path / "context", candle_path=path, clock=lambda: now)


def build(context, rows, *, parity=False):
    return context.build(
        instrument_id="NSE:IDX_I:13", symbol="NIFTY", candles_1m=rows,
        correlation_id="corr-phase2", parity_4h=parity,
        source_ids={"canonical": "fixture"}, dependency_versions={"policy": "2.0.0", "vob": "authority"},
    )


@pytest.mark.unit
def test_contract_rejects_missing_lineage_future_forming_and_corrupt_hash():
    with pytest.raises(ContractValidationError, match="lineage"):
        CanonicalCandleRef(**{**metadata(), "source_ids": {}}, candle_id="x", security_id="13",
            bar_start=(NOW-timedelta(minutes=3)).isoformat(), bar_end=NOW.isoformat(), open=1, high=1, low=1, close=1, volume=1, trading_date="2026-08-01")
    with pytest.raises(ContractValidationError, match="future"):
        CanonicalCandleRef(**{**metadata(), "source_timestamp": (NOW+timedelta(seconds=1)).isoformat()}, candle_id="x", security_id="13",
            bar_start=(NOW-timedelta(minutes=3)).isoformat(), bar_end=NOW.isoformat(), open=1, high=1, low=1, close=1, volume=1, trading_date="2026-08-01")
    with pytest.raises(ContractValidationError, match="forming"):
        CanonicalCandleRef(**{**metadata(), "completion_status": CompletionStatus.FORMING}, candle_id="x", security_id="13",
            bar_start=(NOW-timedelta(minutes=3)).isoformat(), bar_end=NOW.isoformat(), open=1, high=1, low=1, close=1, volume=1, trading_date="2026-08-01")
    valid = candle(1)
    with pytest.raises(ContractValidationError, match="hash"):
        replace(valid, content_hash="0" * 64)
    with pytest.raises(ContractValidationError, match="security"):
        replace(valid, content_hash="", security_id="")


@pytest.mark.unit
def test_context_builds_all_lanes_marks_partial_4h_and_unproven_parity(tmp_path):
    rows = minute_rows()
    context = engine(tmp_path, rows)
    snapshot = build(context, rows)
    assert tuple(lane.timeframe for lane in snapshot.lanes) == SUPPORTED_TIMEFRAMES
    lane4h = next(lane for lane in snapshot.lanes if lane.timeframe == "4H")
    assert lane4h.completion_status is CompletionStatus.PARTIAL_SESSION_BAR
    assert lane4h.provisional is True
    assert lane4h.availability is Availability.UNAVAILABLE
    assert "TRADINGVIEW_CANONICAL_4H_PARITY_UNPROVEN" in lane4h.invalidation_reasons
    assert snapshot.lane_hashes["4H"] == lane4h.content_hash
    with pytest.raises(ContractValidationError, match="dependency"):
        replace(lane4h, content_hash="", dependency_versions={**dict(lane4h.dependency_versions), "candle_hash": "0" * 64})


@pytest.mark.unit
def test_cache_reuses_all_lanes_without_recomputation(tmp_path):
    rows = minute_rows()
    context = engine(tmp_path, rows)
    first = build(context, rows)
    before = dict(context.diagnostics()["cache"]["lane_builds"])
    second = build(context, rows)
    assert first.content_hash == second.content_hash
    assert context.diagnostics()["cache"]["lane_builds"] == before
    assert context.diagnostics()["cache"]["hits"] == 7


@pytest.mark.unit
def test_cache_rebuilds_when_a_lane_crosses_its_freshness_boundary(tmp_path):
    rows = minute_rows()
    clock = [datetime(2026, 7, 31, 15, 31, tzinfo=IST)]
    path = tmp_path / "candles.json"
    path.write_text(json.dumps({"candles": rows}), encoding="utf-8")
    context = ContextEngine(tmp_path / "context", candle_path=path, clock=lambda: clock[0])
    first = build(context, rows)
    assert next(lane for lane in first.lanes if lane.timeframe == "1m").freshness_state is FreshnessState.FRESH
    clock[0] += timedelta(minutes=3)
    second = build(context, rows)
    assert next(lane for lane in second.lanes if lane.timeframe == "1m").freshness_state is FreshnessState.STALE
    assert second.content_hash != first.content_hash


@pytest.mark.unit
def test_dependency_change_and_explicit_invalidation_rebuild(tmp_path):
    rows = minute_rows()
    context = engine(tmp_path, rows)
    build(context, rows)
    context.invalidate("15m", "VERIFIED_STRUCTURE_BREAK")
    assert context.latest_lane("15m") is None
    build(context, rows)
    assert context.latest_lane("15m") is not None
    assert context.diagnostics()["cache"]["lane_builds"]["15m"] == 2


@pytest.mark.unit
def test_restart_recovery_and_corrupt_index_fail_closed(tmp_path):
    rows = minute_rows()
    first = engine(tmp_path, rows)
    snapshot = build(first, rows)
    restored = ContextEngine(tmp_path / "context", candle_path=tmp_path / "candles.json", clock=lambda: datetime(2026, 8, 1, 10, 0, tzinfo=IST))
    assert restored.latest_snapshot().content_hash == snapshot.content_hash
    (tmp_path / "context" / "latest_valid.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(ContextStateError, match="CORRUPT"):
        ContextEngine(tmp_path / "context", candle_path=tmp_path / "candles.json")


@pytest.mark.unit
def test_current_and_prior_sessions_do_not_mix(tmp_path):
    rows = minute_rows(sessions=2)
    context = engine(tmp_path, rows)
    snapshot = build(context, rows)
    assert all(lane.candle is None or lane.candle.trading_date == "2026-07-31" for lane in snapshot.lanes)
    daily = next(lane for lane in snapshot.lanes if lane.timeframe == "1D")
    assert daily.candle.open >= 24100


@pytest.mark.unit
def test_daily_lane_uses_prior_completed_session_while_current_session_is_forming(tmp_path):
    rows = minute_rows(sessions=2)
    current_date = datetime(2026, 7, 31, tzinfo=IST).date()
    rows = [row for row in rows if datetime.fromtimestamp(row["time"], IST).date() != current_date
            or datetime.fromtimestamp(row["time"], IST).time() < time(11, 0)]
    context = engine(tmp_path, rows, now=datetime(2026, 7, 31, 11, 1, tzinfo=IST))
    daily = next(lane for lane in build(context, rows).lanes if lane.timeframe == "1D")
    assert daily.candle.trading_date == "2026-07-30"
    assert daily.completion_status is CompletionStatus.COMPLETE


@pytest.mark.unit
def test_adapter_unavailable_ambiguous_mismatch_and_provenance():
    unavailable = TradingViewMCPAdapter(lambda *_: (_ for _ in ()).throw(TimeoutError())).capture(
        correlation_id="c", instrument_id="NSE:IDX_I:13", symbol="NIFTY", timeframe="3m")
    assert unavailable.failure_reason.startswith("VISUAL_UNAVAILABLE")
    ambiguous = TradingViewMCPAdapter(lambda tool, _: {} if tool in {"tv_health_check", "chart_get_state"} else {}).capture(
        correlation_id="c", instrument_id="NSE:IDX_I:13", symbol="NIFTY", timeframe="3m")
    assert ambiguous.availability is Availability.AMBIGUOUS
    mismatch = TradingViewMCPAdapter(lambda tool, _: {"symbol": "BANKNIFTY", "timeframe": "3"} if tool in {"tv_health_check", "chart_get_state"} else {}).capture(
        correlation_id="c", instrument_id="NSE:IDX_I:13", symbol="NIFTY", timeframe="3m")
    assert "MISMATCH" in mismatch.failure_reason
    timeframe_mismatch = TradingViewMCPAdapter(lambda tool, _: {"symbol": "NIFTY", "timeframe": "5"} if tool in {"tv_health_check", "chart_get_state"} else {}).capture(
        correlation_id="c", instrument_id="NSE:IDX_I:13", symbol="NIFTY", timeframe="3m")
    assert "MISMATCH" in timeframe_mismatch.failure_reason
    def caller(tool, _):
        if tool in {"tv_health_check", "chart_get_state"}:
            return {"symbol": "NIFTY", "timeframe": "3", "indicators": [{"name": "Volume"}],
                    "visual_claim_candidates": [{"claim_type": "STRUCTURE_BREAK", "direction": "BULLISH",
                                                  "predicates": {"level": 100}, "declared_tolerance": 0.1}]}
        if tool == "capture_screenshot":
            return {"path": "/tmp/chart.png"}
        return {"items": []}
    observed = TradingViewMCPAdapter(caller).capture(correlation_id="c", instrument_id="NSE:IDX_I:13", symbol="NIFTY", timeframe="3m")
    assert observed.availability is Availability.AVAILABLE
    assert observed.provenance["mcp_version"] == "2.0.0"
    assert observed.artifact_reference == "/tmp/chart.png"
    assert "Volume" in observed.visible_indicators
    assert len(observed.claim_candidates) == 1
    assert observed.claim_candidates[0].provenance["requires_citadel_verification"] is True
    assert "ohlc" not in observed.to_dict() and "indicator_values" not in observed.to_dict()


@pytest.mark.unit
def test_visual_observation_store_recovers_nested_candidate_hashes(tmp_path):
    def caller(tool, _):
        if tool in {"tv_health_check", "chart_get_state"}:
            return {"symbol": "NIFTY", "timeframe": "3", "visual_claim_candidates": [
                {"claim_type": "STRUCTURE_BREAK", "direction": "BULLISH", "predicates": {"level": 100}}
            ]}
        return {}
    observed = TradingViewMCPAdapter(caller, clock=lambda: NOW).capture(
        correlation_id="c", instrument_id="NSE:IDX_I:13", symbol="NIFTY", timeframe="3m")
    store = VisualObservationStore(tmp_path)
    store.save_observation(observed)
    restored = store.observation(observed.observation_id)
    assert restored.content_hash == observed.content_hash
    assert restored.claim_candidates[0].verify_hash()


@pytest.mark.unit
@pytest.mark.parametrize("claim,expected", [
    (lambda cs: candidate("TREND", "BULLISH", {"lookback": 3}), "VERIFIED"),
    (lambda cs: candidate("STRUCTURE_BREAK", "BULLISH", {"level": 101.5}), "VERIFIED"),
    (lambda cs: candidate("STRUCTURE_BREAK", "BEARISH", {"level": 99.0}), "REJECTED"),
    (lambda cs: candidate("LEVEL_ACCEPTANCE", "ABOVE", {"level": 100.5, "min_closes": 2}), "VERIFIED"),
    (lambda cs: candidate("LEVEL_REJECTION", "BEARISH", {"level": 102.5}), "VERIFIED"),
])
def test_visual_claim_verification_types(claim, expected):
    candles = [candle(1, close=101), candle(2, close=102), candle(3, close=103, high=104)]
    if claim(candles).claim_type == "LEVEL_REJECTION":
        candles[-1] = candle(3, close=102, high=104)
    result = VisualClaimVerifier(clock=lambda: NOW).verify(claim(candles), candles)
    assert result.status == expected
    assert result.actionable_evidence_weight == 0.0
    assert result.predicates_evaluated


@pytest.mark.unit
def test_genuine_sweep_wick_only_and_no_reclaim():
    prior = candle(1, close=101, low=100)
    sweep = candidate("LIQUIDITY_SWEEP", "BULLISH", {"level": 100, "prior_level_candle_id": prior.candle_id, "window": 2}, 0.1)
    verified = VisualClaimVerifier(clock=lambda: NOW).verify(sweep, [prior, candle(2, close=101, low=99)])
    assert verified.status == "VERIFIED"
    wick_only = VisualClaimVerifier(clock=lambda: NOW).verify(sweep, [prior, candle(2, close=99.5, low=99)])
    assert wick_only.status == "REJECTED"
    assert "WICK_ONLY_NO_RECLAIM" in wick_only.conflicting_evidence
    no_reclaim = VisualClaimVerifier(clock=lambda: NOW).verify(
        sweep, [prior, candle(2, close=99.0, low=98.5), candle(3, close=99.8, low=99.5)])
    assert no_reclaim.status == "REJECTED"
    assert "WICK_ONLY_NO_RECLAIM" in no_reclaim.conflicting_evidence


@pytest.mark.unit
def test_stale_and_cross_timeframe_claim_inputs_are_unverifiable():
    c = candidate("STRUCTURE_BREAK", "BULLISH", {"level": 100})
    stale = VisualClaimVerifier(clock=lambda: NOW).verify(c, [candle(1, close=102, freshness=FreshnessState.STALE)])
    assert stale.status == "UNVERIFIABLE"
    cross = VisualClaimVerifier(clock=lambda: NOW).verify(c, [candle(1, timeframe="5m", close=102)])
    assert cross.status == "UNVERIFIABLE"
    assert "CROSS_SYMBOL_OR_TIMEFRAME_INPUT_REJECTED" in cross.conflicting_evidence
    cross_symbol = VisualClaimVerifier(clock=lambda: NOW).verify(c, [candle(1, symbol="BANKNIFTY", close=102)])
    assert cross_symbol.status == "UNVERIFIABLE"
    assert "CROSS_SYMBOL_OR_TIMEFRAME_INPUT_REJECTED" in cross_symbol.conflicting_evidence


@pytest.mark.unit
def test_historical_proof_is_explicit_and_still_has_zero_actionable_weight():
    c = candidate("STRUCTURE_BREAK", "BULLISH", {"level": 100})
    result = VisualClaimVerifier(clock=lambda: NOW).verify(c, [candle(1, close=102, freshness=FreshnessState.STALE)], allow_historical=True)
    assert result.status == "VERIFIED"
    assert result.availability is Availability.HISTORICAL
    assert result.freshness_state is FreshnessState.STALE
    assert result.provenance["historical_proof"] is True
    assert result.actionable_evidence_weight == 0.0


@pytest.mark.safety
def test_perception_modules_have_no_forbidden_control_dependencies():
    forbidden = ("src.risk", "src.execution", "src.broker", "openalgo", "paper_autopilot", "guardian")
    root = Path("src/oracle")
    files = [*root.glob("contracts/*.py"), *root.glob("context/*.py"), *root.glob("visual/*.py")]
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imports.extend(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom): imports.append(node.module or "")
        assert not any(any(name.startswith(item) or item in name.lower() for item in forbidden) for name in imports), (path, imports)


@pytest.mark.safety
def test_phase2_api_surface_is_read_only_and_safety_locks_remain_literal():
    source = Path("app/main.py").read_text(encoding="utf-8")
    phase2_lines = [line.strip() for line in source.splitlines() if "/v1/oracle/perception" in line]
    assert phase2_lines and all(line.startswith('@app.get(') for line in phase2_lines)
    for path in (Path("src/oracle/context/engine.py"), Path("src/oracle/visual/adapter.py"), Path("src/oracle/visual/verifier.py")):
        text = path.read_text(encoding="utf-8")
        assert "execution_influence" in text and "ZERO" in text
    mission = Path("src/oracle/mission.py").read_text(encoding="utf-8")
    assert '"paper_only": True' in mission
    assert '"live_trading_enabled": False' in mission
    assert '"broker_submission": False' in mission
