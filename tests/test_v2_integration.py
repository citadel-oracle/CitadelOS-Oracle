import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from threading import Event, Thread
from time import perf_counter, sleep

import pytest

from src.api.v2_integration import (
    ProjectionProcessWorker,
    ProjectionValidationError,
    V2DashboardIntegration,
)


pytestmark = pytest.mark.unit


def test_uninitialized_serialized_dashboard_fails_closed_without_blocking_event_loop():
    service = V2DashboardIntegration()
    started = perf_counter()
    with pytest.raises(RuntimeError, match="V2_PROJECTION_NOT_READY"):
        service.serialized_dashboard()
    assert perf_counter() - started < 0.05


def test_optional_strategies_and_comparison_are_paused_off_live_hot_path():
    service, _ = _integration()
    calls = {"strategies": 0, "comparison": 0}

    def forbidden(name):
        def call():
            calls[name] += 1
            raise AssertionError(f"{name} entered live projection hot path")
        return call

    service.providers["strategies_command"] = forbidden("strategies")
    service.providers["comparison"] = forbidden("comparison")

    projection = service._build_dashboard("NIFTY")

    assert calls == {"strategies": 0, "comparison": 0}
    assert projection["feeds"]["strategies"]["error"]["code"] == "STRATEGIES_HOT_PATH_PAUSED"
    assert projection["feeds"]["comparison"]["error"]["code"] == "COMPARISON_HOT_PATH_PAUSED"


def test_slow_auxiliary_provider_never_reenters_critical_projection_hot_path():
    service, _ = _integration()
    service.dashboard("NIFTY")
    calls = {"risk": 0}

    def slow_risk():
        calls["risk"] += 1
        sleep(0.25)
        return {"status": "READY"}

    service.providers["risk_status"] = slow_risk
    started = perf_counter()
    projection = service._build_dashboard("NIFTY")

    assert perf_counter() - started < 0.15
    assert calls["risk"] == 0
    assert projection["feeds"]["risk_status"]["meta"]["projection_cache"]["refresh_in_background"] is True


def _integration(failing=None):
    calls = {"snapshot": 0}

    def snapshot():
        calls["snapshot"] += 1
        return {
            "status": {"health": "HEALTHY", "generated_at": "2026-07-12T09:00:00+00:00"},
            "journal_summary": {"total_trades": 2},
            "active_trade": None,
            "analytics": {"summary": {"total_pnl": 12.5}},
            "optimizer": {"suggestions": []},
            "scanner": [{"symbol": "NIFTY", "confidence": 70, "smart_score": 66}],
        }

    def provider(name, data=None):
        def call(*_args):
            if failing == name:
                raise RuntimeError("isolated module failure")
            return data if data is not None else {"status": "READY", "updated_at": "2026-07-12T09:00:00+00:00"}
        return call

    service = V2DashboardIntegration(
        snapshot=snapshot,
        kronos_alpha=provider("kronos_alpha"),
        chronos2=provider("chronos2"),
        oracle=provider("oracle"),
        athena=provider("athena"),
        hermes=provider("hermes"),
        argus=provider("argus"),
        risk_status=provider("risk_status"),
        kill_switch=provider("kill_switch"),
        paper_status=provider("paper_status"),
        personal_oracle=provider("personal_oracle"),
        aegis=provider("aegis", {"decision": "NO_TRADE", "execution_permission": False}),
        readiness=provider("readiness"),
        next_session_plan=provider("next_session_plan"),
        order_ledger=provider("order_ledger"),
        paper_trading=provider("paper_trading", {"timeline": {"events": []}}),
    )
    return service, calls


def test_v2_dashboard_is_single_versioned_authoritative_projection():
    service, calls = _integration()
    result = service.dashboard("nifty")

    assert calls["snapshot"] == 1
    assert result["api_version"] == "2.0"
    assert result["schema_version"] == 2
    assert result["release_contract"] == {
        "compatibility_id": "CITADEL_POST_E9_CANONICAL_V1",
        "canonical_release": "POST_E9_ARGUS_ORACLE_P0",
        "api_version": "2.0",
        "schema_version": 2,
        "frontend_schema_versions": [1],
        "backend_owner": "CITADEL_ORACLE_POST_E9_CANONICAL_BACKEND",
        "duplicate_backend_allowed": False,
        "activation_policy": "FRONTEND_AND_BACKEND_MUST_EMIT_MATCHING_COMPATIBILITY_ID",
    }
    assert result["symbol"] == "NIFTY"
    assert result["polling"]["recommended_interval_ms"] == 3000
    assert result["polling"]["single_request"] is True
    assert result["polling"]["frontend_side_effects"] is False
    assert len(result["feeds"]) == 21
    assert result["feeds"]["insights"]["data"] == []
    assert result["trace"]["immutable_audits"] == {"aegis": True, "order_fill_ledger": True, "paper_state": True}
    for feed in result["feeds"].values():
        assert feed["meta"]["api_version"] == "2.0"
        assert feed["meta"]["schema_version"] == 2
        assert feed["meta"]["authoritative"] is True
        assert feed["meta"]["fail_closed"] is True


def _coherent_boundary_feeds(boundary):
    timestamp = boundary.isoformat()
    contracts = {
        side: {
            "vob": {"evaluated_through": timestamp},
            "trend": {"evaluated_through": timestamp},
        }
        for side in ("CE", "PE")
    }
    return {
        "strategy_lab": {
            "data": {
                "execution": {
                    "options_structure": {"contracts": contracts},
                    "nifty_vob": {
                        "timeframes": {
                            "5m": {"evaluated_through": timestamp}
                        }
                    },
                }
            }
        },
        "oracle": {
            "data": {
                "timeframe": "5m",
                "market_data_as_of": timestamp,
            }
        },
    }


def test_v2_intelligence_boundary_is_coherent_and_excludes_forming_bucket():
    boundary = datetime(2026, 7, 27, 11, 35, tzinfo=timezone.utc)
    generated = boundary + timedelta(minutes=5, seconds=1)
    feeds = _coherent_boundary_feeds(boundary)

    result = V2DashboardIntegration._intelligence_boundary(
        feeds, generated.isoformat()
    )

    assert result["status"] == "COHERENT"
    assert result["completed_boundary"] == boundary.isoformat()
    assert set(result["modules"].values()) == {boundary.isoformat()}
    assert (
        feeds["oracle"]["data"]["decision_boundary_5m"]
        == boundary.isoformat()
    )

    # An optional/failed dashboard snapshot must not crash the canonical
    # intelligence projection worker during startup.
    feeds = _coherent_boundary_feeds(boundary)
    feeds["mission"] = {"ok": False, "data": None}
    assert V2DashboardIntegration._intelligence_boundary(
        feeds, generated.isoformat()
    )["status"] == "COHERENT"

    with pytest.raises(
        ProjectionValidationError,
        match="MODULE_LAG:OSE_VOB_OR_ORACLE_BOUNDARY_UNAVAILABLE",
    ):
        V2DashboardIntegration._intelligence_boundary(
            _coherent_boundary_feeds(generated),
            generated.isoformat(),
        )


def test_v2_lagging_intelligence_module_fails_closed_without_mixed_generation():
    boundary = datetime(2026, 7, 27, 11, 35, tzinfo=timezone.utc)
    feeds = _coherent_boundary_feeds(boundary)
    feeds["oracle"]["data"]["market_data_as_of"] = (
        boundary - timedelta(minutes=5)
    ).isoformat()

    with pytest.raises(ProjectionValidationError, match="MODULE_LAG:"):
        V2DashboardIntegration._intelligence_boundary(
            feeds, (boundary + timedelta(minutes=6)).isoformat()
        )


def test_v2_cached_projection_is_one_json_safe_generation_for_mission_reads():
    service, _ = _integration()
    marker = object()
    service.providers["snapshot"] = lambda: {
        "status": {"health": "HEALTHY"},
        "journal_summary": {},
        "active_trade": None,
        "analytics": {"summary": {}},
        "optimizer": {"suggestions": []},
        "scanner": [
            {
                "symbol": "NIFTY",
                "confidence": 70,
                "smart_score": 66,
                "context": marker,
            }
        ],
    }

    published = service.dashboard("NIFTY")
    cached = service.cached_dashboard()

    assert "context" not in published["feeds"]["matrix"]["data"][0]
    assert cached["trace_id"] == published["trace_id"]
    json.dumps(cached, sort_keys=True, allow_nan=False)


def test_unchanged_v2_reads_do_not_recompute_oracle_workspace_or_eye():
    service, _ = _integration()
    calls = {"oracle_workspace": 0}

    def oracle_workspace():
        calls["oracle_workspace"] += 1
        return {
            "sync_state": "READY",
            "chart_state": {"timeframe": "5m"},
        }

    service.providers["oracle_live_workspace"] = oracle_workspace
    published = service.dashboard("NIFTY")
    original_eye = published["feeds"]["eye_oracle_projection"]["data"]

    for _ in range(5):
        assert json.loads(service.serialized_dashboard()[0])["feeds"]["eye_oracle_projection"]["data"] == original_eye
        assert service.cached_dashboard()["feeds"]["eye_oracle_projection"]["data"] == original_eye

    assert calls["oracle_workspace"] == 1


def test_new_argus_revision_rebuilds_and_atomically_invalidates_cached_view():
    service, _ = _integration()
    revision = {"value": "argus-a"}
    service.providers["argus"] = lambda _symbol: {
        "status": "LIVE",
        "computed_snapshot_id": revision["value"],
        "receipt_timestamp": "2026-07-12T09:00:00+00:00",
        "timestamp_semantics": "RECEIPT_TIME_NO_PROVIDER_EVENT_TIME",
    }
    first = service.dashboard("NIFTY")
    assert first["feeds"]["argus"]["data"]["computed_snapshot_id"] == "argus-a"

    revision["value"] = "argus-b"
    assert service._refresh_once() is True
    second = service.cached_dashboard()
    assert second["feeds"]["argus"]["data"]["computed_snapshot_id"] == "argus-b"
    assert second["trace_id"] != first["trace_id"]


def test_argus_lineage_preserves_distinct_event_receipt_and_freshness_times():
    service, _ = _integration()
    received = datetime.now(timezone.utc) - timedelta(seconds=5)
    lineage = service._lineage(
        "argus",
        {
            "source_event_time": None,
            "receipt_timestamp": received.isoformat(),
            "timestamp_semantics": "RECEIPT_TIME_NO_PROVIDER_EVENT_TIME",
            "freshness_threshold_seconds": 20.0,
        },
    )

    assert lineage["source_timestamp"] is None
    assert lineage["source_event_time"] is None
    assert lineage["receipt_timestamp"] == received.isoformat()
    assert lineage["freshness_timestamp"] == received.isoformat()
    assert lineage["timestamp_semantics"] == "RECEIPT_TIME_NO_PROVIDER_EVENT_TIME"
    assert lineage["freshness"] == "FRESH"
    assert 4.0 <= lineage["freshness_age_seconds"] <= 7.0
    assert lineage["source_age_seconds"] is None
    assert lineage["receipt_age_seconds"] is not None
    assert lineage["freshness_basis"] == "RECEIPT_TIME_NO_PROVIDER_EVENT_TIME"


def test_v2_weekend_or_refetched_last_good_can_never_be_fresh():
    service, _ = _integration()
    friday = datetime(2026, 8, 7, 15, 25, tzinfo=timezone.utc)
    saturday_receipt = friday + timedelta(days=1)
    lineage = service._lineage(
        "argus",
        {
            "source_event_time": friday.isoformat(),
            "receipt_timestamp": saturday_receipt.isoformat(),
            "market_state": "WEEKEND",
            "timestamp_semantics": "PROVIDER_EVENT_TIME",
            "freshness_threshold_seconds": 20.0,
        },
    )
    assert lineage["market_input_state"] == "STALE"
    assert lineage["freshness"] == "STALE"
    assert lineage["source_event_time"] == friday.isoformat()
    assert lineage["receipt_timestamp"] == saturday_receipt.isoformat()
    assert lineage["freshness_basis"] == "PROVIDER_EVENT_TIME"


def test_v2_rejects_non_finite_rebuild_and_preserves_last_valid_projection():
    service, _ = _integration()
    valid = service.dashboard("NIFTY")
    service.providers["oracle"] = lambda _symbol: {
        "status": "READY",
        "confidence": float("nan"),
    }

    assert service._refresh_once() is False
    cached = service.cached_dashboard()
    assert cached["trace_id"] == valid["trace_id"]
    assert service._last_refresh_status == (
        "V2_SNAPSHOT_MALFORMED:root.feeds.oracle.data.confidence:"
        "NON_FINITE_NUMBER"
    )


def test_v2_aegis_uses_one_prepared_feed_snapshot_and_reports_unavailable_truthfully():
    captured=[]
    service,_=_integration()
    service.providers.pop("aegis")
    service.providers["aegis_prepared"]=lambda symbol, prepared: captured.append((symbol, prepared)) or {
        "mode":"ADVISORY","recommendation":"PAUSE","execution_influence":"ZERO",
        "input_status":"UNAVAILABLE","freshness":"UNAVAILABLE","unavailable_reason":"AEGIS_REQUIRED_INPUT_UNAVAILABLE",
    }
    result=service.dashboard("NIFTY")
    assert len(captured)==1 and captured[0][0]=="NIFTY"
    assert {"technical","argus","kronos_alpha","kronos_core","athena","hermes","personal_oracle","risk","paper","session"} <= set(captured[0][1])
    assert result["feeds"]["aegis"]["data"]["execution_influence"]=="ZERO"
    assert result["feeds"]["aegis"]["meta"]["authoritative"] is False


def test_v2_dashboard_isolates_module_failure_and_fails_that_feed_closed():
    service, _ = _integration(failing="hermes")
    result = service.dashboard()

    assert result["feeds"]["hermes"]["ok"] is False
    assert result["feeds"]["hermes"]["data"] is None
    assert result["feeds"]["hermes"]["meta"]["health"] == "UNAVAILABLE"
    assert result["feeds"]["hermes"]["meta"]["readiness"] == "NOT_READY"
    assert result["feeds"]["aegis"]["ok"] is True
    assert result["feeds"]["mission"]["ok"] is True


def test_frontend_polls_only_the_v2_aggregate():
    root = Path(__file__).parents[1] / "citadel-dashboard/src"
    provider = (root / "dashboard/providers/RestDashboardProvider.ts").read_text()
    page = (root / "app/page.tsx").read_text()

    assert provider.count("fetch(") == 1
    assert "/v2/dashboard?symbol=${encodeURIComponent(this.symbol)}" in provider
    assert provider.count("/v1/oracle/fast-lane") == 2
    assert provider.count("/v1/oracle/live-workspace/stream") == 1
    assert "this.inFlight" in provider
    assert "AbortController" in provider
    assert "dashboardActions.refresh()" in page
    assert "fetch(" not in page


def test_v2_strategy_lab_feed_preserves_execution_and_review_lineage():
    service, _ = _integration()
    service.providers["strategy_lab"] = lambda: {
        "status": {"health": "HEALTHY", "readiness": "READY"},
        "portfolio": {"current_capital": 50_000, "today_pnl": 125},
        "execution": {"order_count": 1, "fill_count": 1, "timeline": [{"record_id": "event-1"}]},
        "review": {"replay": [{"record_id": "replay-1"}], "evidence": [{"record_id": "evidence-1"}]},
        "generated_at": "2026-07-14T09:00:00+00:00",
    }

    result = service.dashboard("NIFTY")

    feed = result["feeds"]["strategy_lab"]
    assert feed["ok"] is True
    assert feed["data"]["portfolio"]["current_capital"] == 50_000
    assert feed["data"]["execution"]["order_count"] == 1
    assert feed["data"]["execution"]["timeline"][0]["record_id"] == "event-1"
    assert feed["data"]["review"]["replay"][0]["record_id"] == "replay-1"
    assert feed["meta"]["source_last_updated"] == "2026-07-14T09:00:00+00:00"


def test_v2_reuses_atomic_strategy_lab_snapshot_until_background_refresh():
    service, _ = _integration()
    calls = {"strategy_lab": 0}

    def strategy_lab():
        calls["strategy_lab"] += 1
        return {
            "status": {"health": "HEALTHY", "readiness": "READY"},
            "generated_at": "2026-07-14T09:00:00+00:00",
            "snapshot_version": calls["strategy_lab"],
        }

    service.providers["strategy_lab"] = strategy_lab

    first = service.dashboard("NIFTY")
    second = service.dashboard("NIFTY")

    assert calls["strategy_lab"] == 1
    assert first["feeds"]["strategy_lab"]["data"]["snapshot_version"] == 1
    assert second["feeds"]["strategy_lab"]["data"]["snapshot_version"] == 1
    assert second["feeds"]["strategy_lab"]["data"]["projection_cache"]["refresh_in_background"] is True


def test_intelligence_meta_exposes_shadow_lineage_and_never_marks_stale_input_ready():
    service, _ = _integration()
    service.providers["kronos_alpha"] = lambda: {
        "model_status": "READY",
        "symbol": "NIFTY",
        "timeframe": "5m",
        "input_candle_count": 64,
        "last_input_candle_at": "2026-07-14T09:00:00+00:00",
        "last_inference_at": "2026-07-14T09:00:01+00:00",
        "source_metadata": {"source": "DHAN_DATA_API", "fixture_data": False},
    }

    meta = service.dashboard("NIFTY")["feeds"]["kronos_alpha"]["meta"]

    assert meta["symbol"] == "NIFTY"
    assert meta["timeframe"] == "5m"
    assert meta["input_candle_count"] == 64
    assert meta["latest_completed_candle_at"] == "2026-07-14T09:00:00+00:00"
    assert meta["health"] == "STALE"
    assert meta["readiness"] == "STALE"
    assert meta["stale_reason"].startswith("SOURCE_CANDLE_AGE_")
    assert meta["advisory_only"] is True
    assert meta["execution_influence"] == 0


def test_five_minute_market_input_uses_interval_plus_grace_not_transport_threshold():
    service, _ = _integration()
    assert service._freshness_threshold("5m") == 360
    assert service._freshness_threshold("1m") == 90


def test_frontend_preserves_last_good_feed_data_when_one_v2_feed_fails():
    root = Path(__file__).parents[1] / "citadel-dashboard/src"
    provider = (root / "dashboard/providers/RestDashboardProvider.ts").read_text()
    adapter = (root / "dashboard/adapters/DashboardDataAdapter.ts").read_text()
    page = (root / "app/page.tsx").read_text()

    assert "private lastSnapshot: DashboardSourceSnapshot | null = null" in provider
    assert "this.lastSnapshot" in provider
    assert "health: 'STALE'" in provider
    assert "readiness: 'DEGRADED'" in provider
    assert "snapshot.feeds.strategy_lab" in adapter
    assert "execution?.order_count" in page
    assert "execution?.fill_count" in page


def test_frontend_marks_overaged_overlap_cache_stale_and_can_recover_on_next_fresh_snapshot():
    provider = (Path(__file__).parents[1] / "citadel-dashboard/src/dashboard/providers/RestDashboardProvider.ts").read_text()

    assert "cachedProjectionStale" in provider
    assert "projection_age_ms" in provider
    assert "health: 'STALE'" in provider
    assert "CACHED_PROJECTION_AGE_" in provider
    assert "this.lastSnapshot =" in provider


def test_mock_provider_is_used_only_when_explicitly_configured():
    context = (Path(__file__).parents[1] / "citadel-dashboard/src/dashboard/contexts/DashboardContext.tsx").read_text()

    assert "NEXT_PUBLIC_CITADEL_DATA_MODE === 'mock'" in context
    assert "new RestDashboardProvider()" in context


def test_overlapping_v2_projection_serves_bounded_last_good_projection_without_second_compute():
    service, _ = _integration()
    seeded = service.dashboard()
    entered = Event()
    release = Event()
    slow_calls = {"count": 0}

    def slow_argus(*_args):
        slow_calls["count"] += 1
        entered.set()
        assert release.wait(2)
        return {"status": "READY", "updated_at": "2026-07-12T09:00:00+00:00"}

    service.providers["argus"] = slow_argus
    completed = {}
    thread = Thread(target=lambda: completed.setdefault("result", service.dashboard()))
    thread.start()
    assert entered.wait(1)

    started = perf_counter()
    overlap = service.dashboard()
    elapsed = perf_counter() - started
    release.set()
    thread.join(timeout=2)

    assert elapsed < 0.2
    assert overlap["trace_id"] == seeded["trace_id"]
    assert overlap["polling"]["delivery"] == "CACHED_WHILE_REFRESHING"
    assert overlap["polling"]["served_from_cache"] is True
    assert overlap["polling"]["overlap_skipped"] is True
    assert overlap["polling"]["projection_age_ms"] >= 0
    assert slow_calls["count"] == 1
    assert completed["result"]["polling"]["delivery"] == "FRESH"


def test_overlapping_v2_projection_never_expires_last_good_state_while_refreshing():
    service, _ = _integration()
    seeded = service.dashboard()
    service._last_projection_at -= 300
    assert service._projection_lock.acquire(blocking=False)
    try:
        overlap = service.dashboard()
    finally:
        service._projection_lock.release()

    assert overlap["trace_id"] == seeded["trace_id"]
    assert overlap["polling"]["delivery"] == "CACHED_WHILE_REFRESHING"
    assert overlap["polling"]["projection_age_ms"] >= 300_000


def test_precomputed_v2_snapshot_performance_gate_and_single_refresh_worker():
    service, calls = _integration()
    service.REFRESH_INTERVAL_SECONDS = 60.0
    assert service.start(wait_for_initial=True) is True
    initial_refresh_count = service.refresh_count
    assert initial_refresh_count == 1

    entered = Event()
    release = Event()
    expensive_calls = {"count": 0}

    def expensive_strategy_lab():
        expensive_calls["count"] += 1
        entered.set()
        assert release.wait(2)
        return {
            "status": {"health": "HEALTHY", "readiness": "READY"},
            "snapshot_version": 2,
            "generated_at": "2026-07-14T09:00:00+00:00",
        }

    # Exercise overlap behavior with an intentionally synchronous provider.
    service.providers["strategy_lab"] = expensive_strategy_lab
    refresh = Thread(target=service._refresh_once)
    refresh.start()
    assert entered.wait(1)

    duplicate_refreshes = [Thread(target=service._refresh_once) for _ in range(5)]
    for thread in duplicate_refreshes:
        thread.start()

    durations = []
    payloads = []
    for _ in range(20):
        started = perf_counter()
        body, _metadata = service.serialized_dashboard()
        payloads.append(json.loads(body))
        durations.append(perf_counter() - started)

    release.set()
    refresh.join(timeout=2)
    for thread in duplicate_refreshes:
        thread.join(timeout=2)

    ordered = sorted(durations)
    p95 = ordered[18]
    assert median(durations) < 0.5
    assert p95 < 1.0
    assert max(durations) < 2.0
    assert all(payload["feeds"]["mission"]["ok"] is True for payload in payloads)
    assert all(payload["polling"]["request_path"] == "ATOMIC_PRECOMPUTED_SNAPSHOT" for payload in payloads)
    assert expensive_calls["count"] == 1
    assert service.refresh_count == initial_refresh_count + 1

    with service._state_lock:
        service._last_projection_at -= service.STALE_SNAPSHOT_AGE_SECONDS + 1
    stale_body, _metadata = service.serialized_dashboard()
    stale = json.loads(stale_body)
    assert stale["polling"]["snapshot_status"] == "STALE"
    assert stale["polling"]["projection_age_ms"] >= service.STALE_SNAPSHOT_AGE_SECONDS * 1000
    service.stop()


def test_nonblocking_v2_start_returns_before_initial_provider_hydration():
    service, _ = _integration()
    entered = Event()
    release = Event()

    def slow_snapshot():
        entered.set()
        assert release.wait(2)
        return {
            "status": {"health": "HEALTHY"}, "journal_summary": {},
            "active_trade": None, "analytics": {"summary": {}},
            "optimizer": {"suggestions": []}, "scanner": [],
        }

    service.providers["snapshot"] = slow_snapshot
    started = perf_counter()
    assert service.start(wait_for_initial=False) is True
    assert perf_counter() - started < 0.05
    assert entered.wait(1)
    with pytest.raises(RuntimeError, match="V2_PROJECTION_NOT_READY"):
        service.serialized_dashboard()
    release.set()
    assert service._initial_snapshot_ready.wait(2)
    assert json.loads(service.serialized_dashboard()[0])["api_version"] == "2.0"
    service.stop()


def test_app_lifespan_binds_publishers_before_restart_hydration_thread():
    source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text()
    startup = source[source.index('def start_kronos_alpha_scheduler():'):source.index('def _hydrate_oracle_runtime():')]
    assert "v2_integration.start(wait_for_initial=False)" in startup
    assert "oracle_fast_lane.start()" in startup
    assert 'target=_hydrate_oracle_runtime' in startup
    assert "_recover_flow_pulse_session_context()" not in startup


def _development_worker_payload(evidence_bytes=b""):
    return {
        "generated_at": "2026-07-17T09:00:00+00:00",
        "status": {"state": "MONITORING", "broker_submission": False},
        "position": {"status": "available", "position": None},
        "pnl": {"status": "available", "total_daily_pnl": 0},
        "ledger": {"orders": 0, "fills": 0},
        "timeline": {"status": "available", "events": []},
        "evidence_bytes": evidence_bytes,
    }


def test_process_worker_isolates_cpu_coalesces_and_keeps_atomic_http_snapshot_responsive():
    service, _ = _integration()
    service.dashboard()
    worker = ProjectionProcessWorker(timeout_seconds=5)
    heavy_evidence = (b'{"schema_version":1}\n' * 250_000)
    payload = _development_worker_payload(heavy_evidence)
    results = []
    threads = [Thread(target=lambda: results.append(worker.run("development_dashboard", payload))) for _ in range(4)]
    threads[0].start()
    for _ in range(100):
        if worker.status()["active"]:
            break
        sleep(0.005)
    for thread in threads[1:]:
        thread.start()

    durations = []
    for _ in range(20):
        started = perf_counter()
        body, metadata = service.serialized_dashboard()
        assert json.loads(body)["polling"]["request_path"] == "ATOMIC_PRECOMPUTED_SNAPSHOT"
        assert metadata["status"] == "FRESH"
        durations.append(perf_counter() - started)
    for thread in threads:
        thread.join(timeout=5)

    status = worker.status()
    assert len(results) == 4
    assert status["max_workers"] == 1
    assert status["pending"] == 0
    assert status["submissions"] == 1
    assert status["coalesced"] == 3
    assert status["worker_pid"] != os.getpid()
    assert max(durations) < 0.2
    assert all(result["evidence"]["integrity"]["valid"] is False for result in results)
    worker.stop()


def test_process_worker_timeout_recovers_without_publishing_partial_projection():
    worker = ProjectionProcessWorker(timeout_seconds=0.001, backoff_seconds=0.01)
    with pytest.raises(RuntimeError, match="PROJECTION_WORKER_FAILED"):
        worker.run(
            "development_dashboard",
            _development_worker_payload(b'{"schema_version":1}\n' * 100_000),
        )
    assert worker.status()["failures"] == 1
    assert worker.status()["pending"] == 0
    assert worker.status()["backoff_active"] is True

    worker.timeout_seconds = 5
    sleep(0.02)
    recovered = worker.run("development_dashboard", _development_worker_payload())
    assert recovered["evidence"]["integrity"]["valid"] is True
    assert recovered["evidence"]["integrity"]["records"] == 0
    worker.stop()


def test_worker_failure_retains_last_atomic_snapshot_with_truthful_refresh_status():
    service, _ = _integration()
    service._refresh_once()
    original_trace = json.loads(service.serialized_dashboard()[0])["trace_id"]
    service.providers["argus"] = lambda *_args: (_ for _ in ()).throw(
        RuntimeError("PROJECTION_WORKER_FAILED")
    )

    assert service._refresh_once() is False
    retained = json.loads(service.serialized_dashboard()[0])

    assert retained["trace_id"] == original_trace
    assert retained["polling"]["projection_status"] == "WORKER_REFRESH_FAILED"


def test_optional_development_worker_contention_does_not_stale_live_projection():
    service, _ = _integration()
    service.providers["development"] = lambda: (_ for _ in ()).throw(
        RuntimeError("PROJECTION_WORKER_BUSY")
    )

    assert service._refresh_once() is True
    published = json.loads(service.serialized_dashboard()[0])

    assert published["feeds"]["development"]["ok"] is False
    assert published["polling"]["projection_status"] == "READY"
    assert published["polling"]["snapshot_status"] == "FRESH"


def test_nested_development_status_is_classified_from_runtime_state_not_embedded_decision_text():
    health, readiness = V2DashboardIntegration._states({
        "status": {"state": "MONITORING", "last_decision": {"decision": "BLOCK"}}
    })

    assert health == "HEALTHY"
    assert readiness == "READY"


def test_legacy_display_fallbacks_are_not_fabricated():
    source = (Path(__file__).parents[1] / "app/main.py").read_text()

    assert '"System Stable"' not in source
    assert '"T-4"' not in source
    assert '"W1"' not in source


def test_model_freshness_uses_candle_close_and_exposes_audit_fields():
    service, _ = _integration()
    data = {
        "context_end": "2026-07-21T13:00:00+05:30",
        "timeframe": "5m",
        "generated_at": "2026-07-21T13:05:13+05:30",
    }
    from datetime import datetime, timezone
    import src.api.v2_integration

    original_datetime = src.api.v2_integration.datetime
    mock_now = datetime(2026, 7, 21, 7, 35, 30, tzinfo=timezone.utc)
    
    class MockDatetime:
        @classmethod
        def now(cls, tz=None):
            return mock_now.astimezone(tz) if tz else mock_now
        @classmethod
        def fromisoformat(cls, value):
            return datetime.fromisoformat(value)
            
    src.api.v2_integration.datetime = MockDatetime
    try:
        lineage = service._lineage("chronos2", data)
        assert lineage["source_candle_open"] == "2026-07-21T13:00:00+05:30"
        assert lineage["source_candle_close"] == "2026-07-21T13:05:00+05:30"
        assert lineage["calculated_at"] == "2026-07-21T13:05:13+05:30"
        assert lineage["age_seconds"] == 30.0
        assert lineage["freshness"] == "FRESH"
        assert lineage["market_input_state"] == "READY"
    finally:
        src.api.v2_integration.datetime = original_datetime
